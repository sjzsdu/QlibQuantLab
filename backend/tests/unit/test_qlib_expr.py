"""表达式静态校验器单测：词法 / 语法 / 白名单 / 边界。"""

from __future__ import annotations

from qqlab.core.qlib_expr import check_expression

VALID_CASES = [
    "$close / $open - 1",
    "Ref($close, 10) / $close - 1",
    "Mean($close, 20)",
    "Std($close, 20)",
    "-$close",
    "($close + $open) / 2",
    "If($close > $open, 1, 0)",
    "Rank($close)",
    "Rank($close, None)",
    "Ref($close, 5) > Mean($close, 20)",
    "$close * 1.5 + $open / 2 - 0.3",
    "If(Ref($close, 1) > Mean($close, 20), Std($close, 10), 0)",
    "Abs($close - $open) / $low",
    "Power($close / $open, 2)",
    "IsNull(Ref($close, 1), 0)",
]

INVALID_CASES = [
    ("", "为空"),
    ("$close /", "缺少操作数"),
    ("($close + $open", "括号不配对"),
    ("Ref($close, 10", "括号不配对"),
    ("Ref()", "个参数"),
    ("Ref($close)", "个参数"),
    ("Mean($close, 10, 20)", "个参数"),
    ("$close_price / $open", "未知字段"),
    ("Foo($close)", "未知函数"),
    ("$close; $open", "非法字符"),
    ('Concat("a", "b")', "非法字符"),
    ("close / open", "函数或合法关键字"),
    ("Ref(close, 10)", "不是函数"),
    ("$close @ 2", "非法字符"),
    ("a" * 501, "超长"),
]


def test_valid_expressions() -> None:
    for expr in VALID_CASES:
        result = check_expression(expr)
        assert result.valid, f"{expr!r} 应合法，却报 {result.errors}"
        assert result.errors == []


def test_invalid_expressions() -> None:
    for expr, hint in INVALID_CASES:
        result = check_expression(expr)
        assert not result.valid, f"{expr!r} 应非法"
        assert any(hint in e for e in result.errors), f"{expr!r} 的错误应包含 {hint!r}：{result.errors}"


def test_field_and_function_extraction() -> None:
    result = check_expression("If(Ref($close, 5) > Mean($open, 20), Std($volume, 10), 0)")
    assert result.valid
    assert result.fields == ["close", "open", "volume"]
    assert result.functions == ["If", "Mean", "Ref", "Std"]


def test_depth_limit() -> None:
    expr = "Mean(" * 12 + "$close" + ", 5)" * 12
    result = check_expression(expr)
    assert not result.valid
    assert any("嵌套" in e for e in result.errors)


def test_never_raises_on_garbage() -> None:
    for junk in ("$", "$$$", "...", "(((", ")))", "1..2", "$close $", None, "   "):
        result = check_expression(junk)  # type: ignore[arg-type]
        assert result.valid is False
        assert result.errors
