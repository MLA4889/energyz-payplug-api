import json
import re
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

# ---------- LECTURE DE BASE ----------
def _extract_text_from_column(col: dict) -> str:
    # 1) text
    if col.get("text"):
        return str(col["text"])
    # 2) value (JSON)
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
    """
    Retourne un dict {col_id: texte_lisible, col_id+'__raw': value_brut_json}
    """
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
    item = data["data"]["items"][0]
    result = {"name": item["name"]}
    for col in item["column_values"]:
        if col["id"] in column_ids:
            result[col["id"]] = _extract_text_from_column(col)
            result[col["id"] + "__raw"] = col.get("value") or ""
    return result

# ---------- Board columns map (id <-> title) + formula expr ----------
def get_board_columns_map():
    """
    Retourne:
      - columns: liste de colonnes {id, title, type, settings_str}
      - id_to_title: dict
      - title_to_id: dict
      - formulas: dict {column_id: formula_expression}
    """
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
        return [], {}, {}, {}
    cols = boards[0]["columns"]
    id_to_title, title_to_id, formulas = {}, {}, {}
    for c in cols:
        cid = c["id"]
        ct = c.get("title") or ""
        id_to_title[cid] = ct
        title_to_id[ct] = cid
        if c.get("type") == "formula":
            try:
                s = c.get("settings_str") or ""
                j = json.loads(s) if s else {}
                if isinstance(j, dict) and "formula" in j:
                    formulas[cid] = j["formula"]
            except Exception:
                pass
    return cols, id_to_title, title_to_id, formulas

def get_formula_expression(column_id: str) -> str | None:
    _, _, _, formulas = get_board_columns_map()
    return formulas.get(column_id)

# ---------- Calcul local d'une formula ----------
def _clean_num(text: str) -> str:
    if not text:
        return "0"
    t = str(text).replace("\u202f", "").replace(" ", "").replace("€", "")
    t = t.replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", t)
    return m.group(0) if m else "0"

def _safe_eval_arith(expr: str) -> float:
    import ast, operator as op
    allowed_ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.USub: op.neg, ast.UAdd: op.pos, ast.Pow: op.pow}
    def _eval(node):
        if hasattr(ast, "Constant") and isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Constante non numérique")
        if isinstance(node, ast.Num):
            return node.n
        if isinstance(node, ast.BinOp):
            return allowed_ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return allowed_ops[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Fonction non autorisée")
            fname = node.func.id.lower()
            if fname == "round":
                args = [_eval(a) for a in node.args]
                if len(args) == 1:
                    return round(args[0])
                if len(args) >= 2:
                    return round(args[0], int(args[1]))
                raise ValueError("Arguments round invalides")
            raise ValueError("Fonction non autorisée")
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        raise ValueError("Expression non autorisée")
    tree = ast.parse(expr, mode='eval')
    return float(_eval(tree))

def compute_formula_value_for_item(formula_col_id: str, item_id: int) -> float | None:
    """
    1) Lit l'expression de la formula (board.settings_str)
    2) Remplace chaque {token} par la valeur de l'item
       - token peut être un id de colonne ou un titre de colonne
    3) Support ROUND()
    """
    expr = get_formula_expression(formula_col_id)
    if not expr:
        return None

    # Map colonnes id <-> titre pour interpréter les tokens
    _, id_to_title, title_to_id, _ = get_board_columns_map()

    # Lire toutes les valeurs de l'item (sans 'title', l'API ne le supporte pas ici)
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

    # Construire id -> nombre
    id_to_num: dict[str, float] = {}
    for col in item_cols:
        val_txt = None
        if col.get("text"):
            val_txt = col["text"]
        else:
            rv = col.get("value")
            if rv:
                try:
                    j = json.loads(rv) if isinstance(rv, str) else rv
                    if isinstance(j, dict):
                        val_txt = j.get("text") or j.get("value")
                    else:
                        val_txt = str(j)
                except Exception:
                    val_txt = str(rv)
        num = float(_clean_num(val_txt or "0"))
        id_to_num[col["id"]] = num

    # Tokens { ... }
    tokens = re.findall(r"\{([^}]+)\}", expr)

    # Remplacement tokens par valeurs
    def repl(m: re.Match) -> str:
        token = m.group(1)  # peut être id ou titre
        # Si titre → map vers id
        col_id = token
        if token not in id_to_num and token in title_to_id:
            col_id = title_to_id[token]
        value = id_to_num.get(col_id, 0.0)
        return str(value)

    expr_py = re.sub(r"\bROUND\s*\(", "round(", expr, flags=re.IGNORECASE)
    expr_py = re.sub(r"\{([^}]+)\}", repl, expr_py)
    expr_py = expr_py.replace(",", ".")

    try:
        return _safe_eval_arith(expr_py)
    except Exception:
        return None

# ---------- Écritures ----------
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
