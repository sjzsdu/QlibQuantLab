"""进程内指标注册表的文本渲染（阶段 8 · D8-1，纯标准库 exposition 0.0.4）。"""

from __future__ import annotations

from qqlab.core.metrics import MetricsRegistry, escape_label_value


def test_counter_render_sorted_labels_and_type_lines() -> None:
    reg = MetricsRegistry()
    reg.inc("qqlab_http_requests_total", {"route": "/a", "method": "GET", "status": "200"})
    reg.inc("qqlab_http_requests_total", {"route": "/a", "method": "GET", "status": "200"})
    reg.inc("qqlab_http_requests_total", {"route": "/a", "method": "POST", "status": "422"})
    lines = reg.render()
    assert "# TYPE qqlab_http_requests_total counter" in lines
    # label 按字典序输出（method < route < status），值为整数形态
    assert 'qqlab_http_requests_total{method="GET",route="/a",status="200"} 2' in lines
    assert 'qqlab_http_requests_total{method="POST",route="/a",status="422"} 1' in lines


def test_histogram_buckets_are_cumulative_with_sum_and_count() -> None:
    reg = MetricsRegistry()
    for value in (1.0, 6.0, 60.0):  # 桶：5,10,25,50,100…
        reg.observe_ms("qqlab_http_request_duration_ms", value, {"route": "/x"})
    lines = reg.render()
    assert "# TYPE qqlab_http_request_duration_ms histogram" in lines
    bucket_line = next(
        ln for ln in lines if ln.startswith('qqlab_http_request_duration_ms_bucket{le="5",route="/x"}')
    )
    assert bucket_line.endswith(" 1")  # 1ms 落入 le=5
    inf = next(ln for ln in lines if 'le="+Inf",route="/x"' in ln)
    assert inf.endswith(" 3")
    count = next(ln for ln in lines if ln.startswith("qqlab_http_request_duration_ms_count"))
    assert count.endswith(" 3")
    total = next(ln for ln in lines if ln.startswith("qqlab_http_request_duration_ms_sum"))
    assert total.endswith(" 67")  # 整数值不带小数点（_fmt_value）


def test_label_escaping() -> None:
    assert escape_label_value('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_series_overflow_folds_route_to_other() -> None:
    reg = MetricsRegistry(max_series=2)
    for route in ("/1", "/2", "/3", "/4"):
        reg.inc("m", {"route": route, "method": "GET", "status": "200"})
    lines = [ln for ln in reg.render() if ln.startswith("m{")]
    # 真实路由最多 2 条，其余（/3 /4）折叠进 route=other 并累计
    assert len(lines) == 3
    assert any('route="/1"' in ln for ln in lines)
    assert any('route="/2"' in ln for ln in lines)
    other = next(ln for ln in lines if 'route="other"' in ln)
    assert other.endswith(" 2")
    assert not any('route="/3"' in ln or 'route="/4"' in ln for ln in lines)


def test_no_route_label_series_dropped_at_cap() -> None:
    reg = MetricsRegistry(max_series=1)
    reg.inc("m", {"a": "1"})
    reg.inc("m", {"a": "2"})  # 无 route 可折叠 → 丢弃，不炸
    lines = [ln for ln in reg.render() if ln.startswith("m{")]
    assert lines == ['m{a="1"} 1']


def test_reset_clears_everything() -> None:
    reg = MetricsRegistry()
    reg.inc("m", {"x": "1"})
    reg.observe_ms("h", 1.0, {"x": "1"})
    reg.reset()
    assert reg.render() == []
