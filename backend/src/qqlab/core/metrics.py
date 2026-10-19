"""进程内 Prometheus 指标注册表 + 文本渲染（阶段 8 · D8-1 / D8-2）。

D8-1：手写 exposition 0.0.4 文本渲染，**纯标准库**，不引入 prometheus_client ——
全平台只需要「进程内 RED 计数 + scrape 时现查队列/心跳」两类指标，为一个渲染
函数引三方件不划算（多一份依赖面与版本审计）。

D8-2 指标三分（本文件只负责第一类）：

- **RED**（请求量/时延/错误）：进程内累加，RequestContextMiddleware 记录，
  route 取 FastAPI 路由模板（``scope["route"].path``），未匹配归 ``unmatched``；
- **队列深度/时延/失败率**：scrape 时现查 jobs 表（见 api/v1/metrics.py）——
  队列是持久状态，存进程内会随重启失真；
- **worker 心跳/回收计数**：scrape 时读 CacheProvider（单副本固定键）。
"""

from __future__ import annotations

import threading

#: HTTP 时延直方图桶（毫秒）：覆盖 5ms 网关级到 5s 慢查询
DEFAULT_DURATION_BUCKETS_MS: tuple[float, ...] = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)

#: 单指标序列数上限：label 全来自路由模板/方法/状态码等有界集合，仍设硬顶防失控
_MAX_SERIES = 500

_UNFLOORED_ROUTE = "other"


def escape_label_value(value: str) -> str:
    """Prometheus label 值转义（反斜杠 / 引号 / 换行）。"""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{key}="{escape_label_value(val)}"' for key, val in labels)
    return "{" + inner + "}"


def _sorted_labels(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((labels or {}).items()))


class MetricsRegistry:
    """线程安全的进程内注册表（计数器 + 时延直方图）。"""

    def __init__(self, *, max_series: int = _MAX_SERIES) -> None:
        self._lock = threading.Lock()
        self._max_series = max_series
        #: name -> {labels_key -> value}
        self._counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = {}
        #: name -> {labels_key -> {"buckets": [...], "sum": x, "count": n}}
        self._histograms: dict[str, dict[tuple[tuple[str, str], ...], dict[str, object]]] = {}

    # ------------------------------------------------------------- 记录侧
    def _resolve(
        self,
        table: dict[tuple[tuple[str, str], ...], object],
        name: str,
        labels: dict[str, str] | None,
    ) -> tuple[tuple[tuple[str, str], ...], bool]:
        """取序列键；真实路由超过 max_series 时折叠进 route=other（骨架有限 → 有界）。

        无 route 维度的指标没有可折叠维度，超限直接丢弃（保进程安全）。
        """
        key = _sorted_labels(labels)
        if key in table:
            return key, True
        if labels and "route" in labels:
            real_routes = sum(1 for k in table if dict(k).get("route") != _UNFLOORED_ROUTE)
            if real_routes < self._max_series:
                return key, True
            return _sorted_labels({**labels, "route": _UNFLOORED_ROUTE}), True
        return key, len(table) < self._max_series

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        with self._lock:
            table = self._counters.setdefault(name, {})
            key, ok = self._resolve(table, name, labels)
            if not ok:
                return
            table[key] = table.get(key, 0.0) + value

    def observe_ms(
        self,
        name: str,
        value_ms: float,
        labels: dict[str, str] | None = None,
        buckets: tuple[float, ...] = DEFAULT_DURATION_BUCKETS_MS,
    ) -> None:
        with self._lock:
            table = self._histograms.setdefault(name, {})
            key, ok = self._resolve(table, name, labels)
            if not ok:
                return
            hist = table.get(key)
            if hist is None:
                hist = {"buckets": [0] * len(buckets), "sum": 0.0, "count": 0, "edges": buckets}
                table[key] = hist
            edges: tuple[float, ...] = hist["edges"]  # type: ignore[assignment]
            bucket_counts: list[int] = hist["buckets"]  # type: ignore[assignment]
            for idx, edge in enumerate(edges):
                if value_ms <= edge:
                    bucket_counts[idx] += 1
            hist["sum"] = float(hist["sum"]) + value_ms  # type: ignore[operator]
            hist["count"] = int(hist["count"]) + 1  # type: ignore[operator]

    def reset(self) -> None:
        """测试用：清空全部序列。"""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()

    # ------------------------------------------------------------- 渲染侧
    def render(self) -> list[str]:
        """渲染为 Prometheus 文本行（不含结尾空行，调用方负责拼接）。"""
        with self._lock:
            lines: list[str] = []
            for name in sorted(self._counters):
                lines.append(f"# HELP {name} {name}（进程内累计）")
                lines.append(f"# TYPE {name} counter")
                for key in sorted(self._counters[name]):
                    value = self._counters[name][key]
                    lines.append(f"{name}{_format_labels(key)} {_fmt_value(value)}")
            for name in sorted(self._histograms):
                lines.append(f"# HELP {name} {name}（进程内直方图）")
                lines.append(f"# TYPE {name} histogram")
                for key in sorted(self._histograms[name]):
                    hist = self._histograms[name][key]
                    edges: tuple[float, ...] = hist["edges"]  # type: ignore[assignment]
                    bucket_counts: list[int] = hist["buckets"]  # type: ignore[assignment]
                    cumulative = 0
                    for edge, count in zip(edges, bucket_counts, strict=True):
                        cumulative += count
                        bucket_key = _format_labels(tuple(sorted(key + (("le", _fmt_value(edge)),))))
                        lines.append(f"{name}_bucket{bucket_key} {cumulative}")
                    inf_key = _format_labels(tuple(sorted(key + (("le", "+Inf"),))))
                    lines.append(f"{name}_bucket{inf_key} {int(hist['count'])}")  # type: ignore[arg-type]
                    lines.append(f"{name}_sum{_format_labels(key)} {_fmt_value(float(hist['sum']))}")  # type: ignore[arg-type]
                    lines.append(f"{name}_count{_format_labels(key)} {int(hist['count'])}")  # type: ignore[arg-type]
            return lines


def _fmt_value(value: float) -> str:
    """计数/桶值渲染：整数不带小数点（Prometheus 友好），小数保留 3 位。"""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}"
