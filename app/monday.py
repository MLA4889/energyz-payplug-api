import json
import re
import math
import requests
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"
HEADERS = {
    "Authorization": settings.MONDAY_API_KEY,
    "Content-Type": "application/json"
}

def _post(query: str, variables: dict):
    resp = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data and data["errors"]:
        raise Exception(f"Erreur Monday: {data['errors']}")
    return data

def _extract_text_from_column(col: dict) -> str:
    if col.get("text"):
        return str(col["text"])
    raw_val = col.get("value")
    if raw_val is None or raw_val == "":
        return ""
    try:
        parsed = json.loads(raw_val) if isinstance(raw_val, str) else raw_val
    except Exception:
        return str(raw_val)
    if isinstance(parsed, dict):
        if parsed.get("text"):
            return str(parsed["text"])
        if parsed.get("value"):
            return str(parsed["value"])
        return json.dumps(parsed, ensure_ascii=False)
    return str(parsed)

def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
    query = """
    query ($item_id: ID!) {
      items (ids: [$item_id]) {
        name
        column_values {
          id
          type
          text
          value
        }
      }
    }
    """
    data = _post(query, {"item_id": item_id})
    items = data["data"]["items"]
    if not items:
        return {}
    item = items[0]
    result = {"name": item["name"]}
    for col in item["column_values"]:
        if col["id"] in column_ids:
            result[col["id"]] = _extract_text_from_column(col)
            result[col["id"] + "__raw"] = col.get("value") or ""
    return result

def get_board_columns_map():
    query = """
    query ($board_id: [ID!]) {
      boards (ids: $board_id) {
        id
        columns {
          id
          title
          type
          settings_str
        }
      }
    }
    """
    data = _post(query, {"board_id": settings.MONDAY_BOARD_ID})
    boards = data["data"]["boards"]
    if not boards:
        return [], {}, {}, {}, {}
    cols = boards[0]["columns"]
    id_to_title, title_to_id, formulas, col_types = {}, {}, {}, {}
    for c in cols:
        cid = c["id"]
        title = c.get("title") or ""
        ctype = c.get("type") or ""
        id_to_title[cid] = title
        title_to_id[title] = cid
        col_types[cid] = ctype
        if ctype == "formula":
            try:
                s = c.get("settings_str") or ""
                j = json.loads(s) if s else {}
                if isinstance(j, dict) and "formula" in j:
                    formulas[cid] = j["formula"]
            except Exception:
                pass
    return cols, id_to_title, title_to_id, formulas, col_types

def get_formula_expression(column_id: str) -> str | None:
    _, _, _, formulas, _ = get_board_columns_map()
    return formulas.get(column_id)

def _translate_monday_expr(expr: str) -> str:
    if expr is None:
        return ""
    out = expr
    out = re.sub(r"\bROUND\s*\(", "round(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bIF\s*\(", "if_(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bAND\s*\(", "and_(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bOR\s*\(", "or_(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bNOT\s*\(", "not_(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bMIN\s*\(", "min(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bMAX\s*\(", "max(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bABS\s*\(", "abs(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bFLOOR\s*\(", "floor(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bCEILING\s*\(", "ceil(", out, flags=re.IGNORECASE)
    out = re.sub(r"\bTRUE\b", "True", out, flags=re.IGNORECASE)
    out = re.sub(r"\bFALSE\b", "False", out, flags=re.IGNORECASE)
    out = out.replace("<>", "!=")
    out = re.sub(r"(?<![<>!=])=(?!=)", "==", out)
    return out

def _safe_eval_arith_bool(expr: str) -> float:
    import ast, operator as op
    allowed_binops = {
        ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
        ast.Pow: op.pow, ast.Mod: op.mod
    }
    allowed_unary = {ast.UAdd: op.pos, ast.USub: op.neg, ast.Not: op.not_}
    allowed_cmp = {
        ast.Eq: op.eq, ast.NotEq: op.ne, ast.Gt: op.gt, ast.GtE: op.ge, ast.Lt: op.lt, ast.LtE: op.le
    }
    def if_(*args):
        if len(args) < 2:
            raise ValueError("IF() requiert au moins 2 arguments")
        cond = bool(args[0])
        a = args[1]
        b = args[2] if len(args) >= 3 else 0
        return a if cond else b
    def and_(*args): return float(all(bool(x) for x in args))
    def or_(*args):  return float(any(bool(x) for x in args))
    def not_(x):     return float(not bool(x))
    safe_funcs = {
        'round': round, 'if_': if_, 'min': min, 'max': max,
        'abs': abs, 'floor': math.floor, 'ceil': math.ceil,
        'and_': and_, 'or_': or_, 'not_': not_,
        'True': True, 'False': False,
    }
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if hasattr(ast, "Constant") and isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, bool, str)):
                return node.value
            raise ValueError("Constante non autorisée")
        if isinstance(node, ast.Str):  # < Py3.8
            return node.s
        if isinstance(node, ast.Num):  # < Py3.8
            return node.n
        if isinstance(node, ast.BinOp):
            return allowed_binops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return allowed_unary[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.BoolOp):
            vals = [_eval(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(bool(v) for v in vals)
            if isinstance(node.op, ast.Or):
                return any(bool(v) for v in vals)
            raise ValueError("BoolOp non autorisé")
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for opnode, comp in zip(node.ops, node.comparators):
                right = _eval(comp)
                if not allowed_cmp[type(opnode)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Appel non autorisé")
            fname = node.func.id
            if fname not in safe_funcs:
                raise ValueError(f"Fonction non autorisée: {fname}")
            args = [_eval(a) for a in node.args]
            return safe_funcs[fname](*args)
        if isinstance(node, ast.Name):
            if node.id in safe_funcs:
                return safe_funcs[node.id]
            raise ValueError(f"Nom non autorisé: {node.id}")
        raise ValueError("Expression non autorisée")
    tree = ast.parse(expr, mode='eval')
    val = _eval(tree)
    return float(val) if isinstance(val, (int, float, bool)) else 0.0

def compute_formula_value_for_item(formula_col_id: str, item_id: int) -> float | None:
    _, id_to_title, title_to_id, formulas, col_types = get_board_columns_map()
    query = """
    query ($item_id: ID!) {
      items (ids: [$item_id]) {
        column_values {
          id
          type
          text
          value
        }
      }
    }
    """
    data = _post(query, {"item_id": item_id})
    item_cols = data["data"]["items"][0]["column_values"]
    id_to_numeric: dict[str, float] = {}
    id_to_string: dict[str, str] = {}
    for col in item_cols:
        ctype = col_types.get(col["id"], col.get("type"))
        val_txt = _extract_text_from_column(col)
        if ctype == "numbers":
            id_to_numeric[col["id"]] = float(re.sub(r"[^0-9\.\-]", "", val_txt.replace(",", ".")) or 0)
        else:
            id_to_string[col["id"]] = val_txt
    seen: set[str] = set()
    cache_num: dict[str, float] = {}
    def resolve_token(token: str):
        col_id = token
        if col_id not in col_types and token in title_to_id:
            col_id = title_to_id[token]
        if col_id in id_to_numeric:
            return id_to_numeric[col_id]
        if col_id in id_to_string:
            return json.dumps(id_to_string[col_id], ensure_ascii=False)
        if col_types.get(col_id) == "formula":
            if col_id in cache_num:
                return cache_num[col_id]
            if col_id in seen:
                return 0.0
            seen.add(col_id)
            child_expr = formulas.get(col_id)
            if not child_expr:
                seen.discard(col_id); return 0.0
            child_expr = _translate_monday_expr(child_expr)
            def repl_child(m: re.Match) -> str:
                tk = m.group(1)
                val = resolve_token(tk)
                return str(val)
            child_expr = re.sub(r"\{([^}]+)\}", repl_child, child_expr)
            try:
                val = _safe_eval_arith_bool(child_expr)
            except Exception:
                val = 0.0
            cache_num[col_id] = val
            seen.discard(col_id)
            return val
        return 0.0
    root = formulas.get(formula_col_id)
    if not root:
        return None
    root_expr = _translate_monday_expr(root)
    def repl_root(m: re.Match) -> str:
        tk = m.group(1)
        val = resolve_token(tk)
        return str(val)
    root_expr = re.sub(r"\{([^}]+)\}", repl_root, root_expr)
    try:
        return _safe_eval_arith_bool(root_expr)
    except Exception:
        return None

def set_link_in_column(item_id: int, column_id: str, url: str, text: str):
    mutation = """
    mutation ($board_id: ID!, $item_id: ID!, $column_id: String!, $value: JSON!) {
      change_column_value(board_id: $board_id, item_id: $item_id, column_id: $column_id, value: $value) {
        id
      }
    }
    """
    link_value = json.dumps({"url": url, "text": text}, ensure_ascii=False)
    _post(mutation, {
        "board_id": settings.MONDAY_BOARD_ID,
        "item_id": item_id,
        "column_id": column_id,
        "value": link_value
    })

def set_status(item_id: int, column_id: str, label: str):
    mutation = """
    mutation ($board_id: ID!, $item_id: ID!, $column_id: String!, $value: String!) {
      change_simple_column_value(board_id: $board_id, item_id: $item_id, column_id: $column_id, value: $value) {
        id
      }
    }
    """
    _post(mutation, {
        "board_id": settings.MONDAY_BOARD_ID,
        "item_id": item_id,
        "column_id": column_id,
        "value": label
    })
