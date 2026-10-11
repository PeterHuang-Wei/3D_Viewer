"""變數與公式:安全的算式求值(僅允許數字、運算、已定義的變數與數學函式)。"""
import ast
import math
import operator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
FUNCS = {n: getattr(math, n) for n in ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
                                       "exp", "log", "log10", "radians", "degrees", "floor", "ceil", "hypot")}
FUNCS.update(abs=abs, min=min, max=max, round=round, pow=pow)
CONSTS = {"pi": math.pi, "e": math.e}


def evaluate(expr: str, names: dict | None = None) -> float:
    """求值算式,例如 '板厚 / 2 + 1'。出錯時丟出 ValueError(附說明)。"""
    names = {**CONSTS, **(names or {})}
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise ValueError(f"算式語法錯誤:{expr}") from e

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
            return _UN[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Name):
            if n.id not in names:
                raise ValueError(f"未定義的變數:{n.id}")
            return names[n.id]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
            return FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError(f"不支援的算式內容:{expr}")

    try:
        return float(ev(tree))
    except ZeroDivisionError as e:
        raise ValueError("算式除以零") from e
    except (OverflowError, TypeError) as e:
        raise ValueError(f"算式無法計算:{expr}") from e


def evaluate_all(variables: dict) -> dict:
    """依序求值 {名稱: 數字或算式},後面的變數可引用前面的。"""
    values: dict = {}
    for name, ex in variables.items():
        values[name] = float(ex) if isinstance(ex, (int, float)) else evaluate(str(ex).lstrip("="), values)
    return values


def resolve_params(params: dict, values: dict) -> dict:
    """把參數中以 '=' 開頭的字串換成算式結果(其餘不變),回傳新 dict。"""
    out = dict(params)
    for k, v in params.items():
        if isinstance(v, str) and v.startswith("="):
            try:
                out[k] = evaluate(v[1:], values)
            except ValueError as e:
                raise ValueError(f"參數「{k}」{e}") from e
    return out
