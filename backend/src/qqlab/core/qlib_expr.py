"""Qlib 因子表达式**静态校验器**（纯标准库，API 进程不 import qlib）。

分层约定（阶段 4 决策）：
- 阶段 4 在 API 侧做「词法 + 语法 + 白名单」静态校验，**不执行计算**；
- 真实计算（D.features 表达式求值）在阶段 5 由 worker 用 qlib 完成；
- 校验器只保证表达式**结构合法**，不保证数值意义正确。

支持的语法（对齐 qlib Expression 解析器的子集）：
- 字段引用：``$close``、``$open``、``$volume`` …（白名单 FIELD_WHITELIST）
- 数字字面量：整数 / 小数 / 负号
- 算术与比较：``+ - * / > < >= <=``
- 函数调用：``Ref($close, 10)``、``Mean($close, 20)``、``If($close > 0, 1, 0)`` …
  （白名单 FUNCTION_WHITELIST，含一元/变参函数的参数个数约束）
- 括号嵌套（深度上限 MAX_DEPTH）与 ``None`` 默认参数（如 ``Rank($close, None)``）

不支持且会被明确拒绝：字符串、属性访问 ``a.b``、下标 ``a[0]``、赋值、分号等。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 表达式最大长度（防滥用与解析爆炸）
MAX_LENGTH = 500
#: 括号/函数嵌套深度上限
MAX_DEPTH = 10

#: 允许的数据字段（qlib dump_bin 标准列；不含 $vwap 的数据集会由执行期报错，静态层不拦）
FIELD_WHITELIST = frozenset({"open", "high", "low", "close", "volume", "factor", "vwap"})

#: 函数白名单：名称 → (最少参数, 最多参数；None=不限)。对齐 qlib operations 常用算子子集。
FUNCTION_WHITELIST: dict[str, tuple[int, int | None]] = {
    "Ref": (2, 2),
    "Mean": (2, 2),
    "Std": (2, 2),
    "Max": (2, 2),
    "Min": (2, 2),
    "Sum": (2, 2),
    "Rank": (1, 2),
    "MedRank": (1, 2),
    "Quantile": (1, 2),
    "Argmax": (1, 2),
    "Argmin": (1, 2),
    "Abs": (1, 1),
    "Sign": (1, 1),
    "Log": (1, 1),
    "Power": (2, 2),
    "If": (3, 3),
    "Gt": (2, 2),
    "Ge": (2, 2),
    "Lt": (2, 2),
    "Le": (2, 2),
    "Eq": (2, 2),
    "Ne": (2, 2),
    "And": (2, 2),
    "Or": (2, 2),
    "Not": (1, 1),
    "DayOfWeek": (1, 1),
    "Date": (1, 1),
    "Month": (1, 1),
    "Year": (1, 1),
    "Week": (1, 1),
    "Minute": (1, 1),
    "Hour": (1, 1),
    "IsNull": (1, 2),
    "NotNull": (1, 2),
    "FFill": (1, 1),
    "BFill": (1, 1),
}

#: 允许的比较运算符（二元）
_COMPARISONS = frozenset({">", "<", ">=", "<="})
#: 允许的算术运算符（二元）
_ARITHMETICS = frozenset({"+", "-", "*", "/"})
_MULTI_CHAR_OPS = (">=", "<=")


@dataclass
class ExpressionCheck:
    """静态校验结果。``valid=False`` 时 ``errors`` 逐条给出可读原因。"""

    valid: bool
    errors: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------- 词法
@dataclass(frozen=True)
class _Token:
    kind: str  # field | number | ident | op | none
    text: str
    pos: int


_FIELD_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IDENT_KEYWORDS = frozenset({"None"})


def _tokenize(expr: str) -> tuple[list[_Token], list[str]]:
    tokens: list[_Token] = []
    errors: list[str] = []
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "$":
            m = _FIELD_RE.match(expr, i)
            if not m:
                errors.append(f"第 {i + 1} 列：`$` 后不是合法字段名")
                break
            tokens.append(_Token("field", m.group(1), i))
            i = m.end()
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and expr[i + 1].isdigit()):
            m = _NUMBER_RE.match(expr, i)
            if not m:  # pragma: no cover - 正则已保证可匹配
                errors.append(f"第 {i + 1} 列：数字字面量格式错误")
                break
            tokens.append(_Token("number", m.group(0), i))
            i = m.end()
            continue
        pair = expr[i : i + 2]
        if pair in _MULTI_CHAR_OPS:
            tokens.append(_Token("op", pair, i))
            i += 2
            continue
        if ch in "()":
            tokens.append(_Token("op", ch, i))
            i += 1
            continue
        if ch in "+-*/><,":
            tokens.append(_Token("op", ch, i))
            i += 1
            continue
        m = _IDENT_RE.match(expr, i)
        if m:
            name = m.group(0)
            kind = "none" if name in _IDENT_KEYWORDS else "ident"
            tokens.append(_Token(kind, name, i))
            i = m.end()
            continue
        errors.append(f"第 {i + 1} 列：非法字符 `{ch}`")
        i += 1
    return tokens, errors


# ---------------------------------------------------------------------- 语法
class _Parser:
    """递归下降：expression → term → factor → unary → primary。"""

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0
        self.fields: set[str] = set()
        self.functions: set[str] = set()

    # ---- 基础游标 ----
    def _peek(self) -> _Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _next(self) -> _Token | None:
        tok = self._peek()
        if tok is not None:
            self._pos += 1
        return tok

    def _expect_op(self, text: str) -> bool:
        tok = self._peek()
        if tok is not None and tok.kind == "op" and tok.text == text:
            self._pos += 1
            return True
        return False

    # ---- 文法 ----
    def parse(self) -> list[str]:
        errors: list[str] = []
        if not self._tokens:
            return ["表达式为空"]
        try:
            self._expression(0)
        except ValueError as exc:
            errors.append(str(exc))
        if not errors and self._peek() is not None:
            tok = self._peek()
            assert tok is not None
            errors.append(f"第 {tok.pos + 1} 列：意外的记号 `{tok.text}`")
        return errors

    def _expression(self, depth: int) -> None:
        self._check_depth(depth)
        self._term(depth)
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "op" and tok.text in _COMPARISONS:
                self._pos += 1
                self._term(depth)
            else:
                return

    def _term(self, depth: int) -> None:
        self._factor(depth)
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "op" and tok.text in _ARITHMETICS:
                self._pos += 1
                self._factor(depth)
            else:
                return

    def _factor(self, depth: int) -> None:
        tok = self._peek()
        if tok is not None and tok.kind == "op" and tok.text == "-":  # 一元负号
            self._pos += 1
        self._primary(depth)

    def _primary(self, depth: int) -> None:
        tok = self._next()
        if tok is None:
            raise ValueError("表达式意外结束（运算符后缺少操作数）")
        if tok.kind == "number":
            return
        if tok.kind == "field":
            if tok.text not in FIELD_WHITELIST:
                raise ValueError(
                    f"第 {tok.pos + 1} 列：未知字段 `${tok.text}`（允许："
                    f"{'/'.join(sorted(FIELD_WHITELIST))}）"
                )
            self.fields.add(tok.text)
            return
        if tok.kind == "none":
            return  # Rank($close, None) 之类的默认参数
        if tok.kind == "ident":
            self._function_call(tok, depth)
            return
        if tok.kind == "op" and tok.text == "(":
            self._expression(depth + 1)
            if not self._expect_op(")"):
                raise ValueError("括号不配对：缺少 `)`")
            return
        raise ValueError(f"第 {tok.pos + 1} 列：意外的记号 `{tok.text}`")

    def _function_call(self, name_tok: _Token, depth: int) -> None:
        if not self._expect_op("("):
            raise ValueError(
                f"第 {name_tok.pos + 1} 列：`{name_tok.text}` 不是函数或合法关键字（函数后需跟 `(`）"
            )
        name = name_tok.text
        if name not in FUNCTION_WHITELIST:
            raise ValueError(
                f"第 {name_tok.pos + 1} 列：未知函数 `{name}()`（白名单见 API 文档 /factors/validate）"
            )
        self.functions.add(name)
        lo, hi = FUNCTION_WHITELIST[name]
        argc = 0
        if self._expect_op(")"):
            argc = 0
        else:
            while True:
                self._expression(depth + 1)
                argc += 1
                if self._expect_op(","):
                    continue
                if not self._expect_op(")"):
                    raise ValueError(f"函数 `{name}()` 括号不配对：缺少 `)`")
                break
        if argc < lo or (hi is not None and argc > hi):
            raise ValueError(f"函数 `{name}()` 需要 {lo}~{hi if hi is not None else '∞'} 个参数，实际 {argc} 个")

    @staticmethod
    def _check_depth(depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ValueError(f"嵌套层数超过上限 {MAX_DEPTH} 层")


# ---------------------------------------------------------------------- 入口
def check_expression(expression: str) -> ExpressionCheck:
    """静态校验一段 qlib 因子表达式。永不抛异常，错误全部收进 ``errors``。"""
    expr = (expression or "").strip()
    if not expr:
        return ExpressionCheck(valid=False, errors=["表达式为空"])
    if len(expr) > MAX_LENGTH:
        return ExpressionCheck(valid=False, errors=[f"表达式超长（{len(expr)} > {MAX_LENGTH} 字符）"])
    if not re.fullmatch(r"[A-Za-z0-9_$.+\-*/()<>,\s]+", expr):
        bad = next(c for c in expr if not re.fullmatch(r"[A-Za-z0-9_$.+\-*/()<>,\s]", c))
        return ExpressionCheck(valid=False, errors=[f"包含非法字符 `{bad}`（只允许字段/数字/运算符/括号）"])

    tokens, lex_errors = _tokenize(expr)
    if lex_errors:
        return ExpressionCheck(valid=False, errors=lex_errors)

    parser = _Parser(tokens)
    parse_errors = parser.parse()
    if parse_errors:
        return ExpressionCheck(valid=False, errors=parse_errors)
    return ExpressionCheck(
        valid=True,
        fields=sorted(parser.fields),
        functions=sorted(parser.functions),
    )


__all__ = [
    "ExpressionCheck",
    "FIELD_WHITELIST",
    "FUNCTION_WHITELIST",
    "MAX_DEPTH",
    "MAX_LENGTH",
    "check_expression",
]
