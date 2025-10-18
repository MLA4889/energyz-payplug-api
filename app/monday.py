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

# ---------- LECTURE DE BASE (inchangé sauf extraction text/value) ----------
def _extract_text_from_column(col: dict) -> str:
    # 1) text direct si dispo
    if col.get("text"):
        return str(col["text"])
    # 2) sinon parser value
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

# ---------- NOUVEAU : lire l'expression d'une colonne Formula ----------
def get_formula_expression(column_id: str) -> str | None:
    """
    Récupère l'expression (string) d'une colonne Formula à partir du board settings_str.
    Ex: settings_str -> {"formula":"({numeric_mkwq2s74} * 0.6667)"}
    """
    query = """
    query ($board_id: [ID!]) {
      boards (ids: $board_id) {
        id
        columns {
          id
          type
          settings_str
        }
      }
    }
    """
    data = _post(query, {"board_id": settings.MONDAY_BOARD_ID})
    boards = data["data"]["boards"]
    if not boards:
        return None
    for col in boards[0]["columns"]:
        if col["id"] == column_id and col["type"] == "formula":
            try:
                s = col.get("settings_str")
                if not s:
                    return None
                j = json.loads(s)
                return j.get("formula")
            except Exception:
                return None
    return None

# ---------- NOUVEAU : calculer la valeur d'une Formula pour un item ----------
def _clean_num(text: str) -> str:
    if not text:
        return "0"
    t = str(text).replace("\u202f", "").replace(" ", "").replace("€", "")
    t = t.replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", t)
    return m.group(0) if m else "0"

def _safe_eval_arith(expr: str) -> float:
    """
    Évalue une expression arithmétique simple en Python en autorisant seulement
    chiffres, + - * / ( ) et la fonction round(x, n).
    """
    import ast, operator as op
    allowed_ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.USub: op.neg, ast.UAdd: op.pos, ast.Pow: op.pow}
    def _eval(node):
        if isinstance(node, ast.Num):  # py<3.8
            return node.n
        if isinstance(node, ast.Constant):  # py>=3.8
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Constante non numérique")
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
    1) Récupère l'expression de la Formula (settings_str.formula)
    2) Remplace chaque {<col_id_ou_nom>} par la valeur numérique de la ligne
    3) Supporte ROUND(x, n)
    4) Évalue l'expression et retourne un float
    """
    expr = get_formula_expression(formula_col_id)
    if not expr:
        return None

    # Trouver tous les tokens { ... }
    tokens = re.findall(r"\{([^}]+)\}", expr)

    # Récupérer toutes les colonnes nécessaires de l'item
    # On tente d'abord les IDs vus dans l'expression ; si l'auteur a mis des noms de colonnes
    # (rare dans settings_str), on récupèrera tout et on fera au mieux.
    needed_ids = set()
    for t in tokens:
        # si l'auteur a mis un id "numeric_..." on l'utilise tel quel
        if re.match(r"^[a-z_0-9]+$", t):
            needed_ids.add(t)
    needed_list = list(needed_ids) if needed_ids else []  # si vide, on prendra tout et on construira un mapping nom->val plus bas

    # Lire l'item
    query = """
    query ($item_id: ID!) {
      items (ids: [$item_id]) {
        name
        column_values {
          id
          text
          value
          title
        }
      }
    }
    """
    data = _post(query, {"item_id": item_id})
    item = data["data"]["items"][0]
    # Construire mapping id -> valeur numérique
    id_to_num: dict[str, float] = {}
    title_to_num: dict[str, float] = {}
    for col in item["column_values"]:
        # on ne filtre pas si needed_list vide (on veut tout)
        if needed_list and col["id"] not in needed_list:
            continue
        # try text/value -> number
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
        if col.get("title"):
            title_to_num[col["title"]] = num

    # Remplacer tokens dans l'expression
    expr_py = expr
    # remapper ROUND -> round
    expr_py = re.sub(r"\bROUND\s*\(", "round(", expr_py, flags=re.IGNORECASE)

    def repl_token(m: re.Match) -> str:
        key = m.group(1)
        # essai par id exact
        if key in id_to_num:
            return str(id_to_num[key])
        # essai par titre (entre accolades dans expr peu probable, mais on tente)
        if key in title_to_num:
            return str(title_to_num[key])
        # sinon 0
        return "0"

    expr_py = re.sub(r"\{([^}]+)\}", repl_token, expr_py)

    # nettoyer éventuels séparateurs français
    expr_py = expr_py.replace(",", ".")
    # Eval sécurisé
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
