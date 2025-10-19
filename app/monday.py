import json
import re
import math
import requests
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"
HEADERS = {
    "Authorization": settings.MONDAY_API_KEY,
    "Content-Type": "application/json",
}

# ================== HTTP / GraphQL ==================

def _post(query: str, variables: dict):
    resp = requests.post(
        MONDAY_API_URL,
        headers=HEADERS,
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("errors"):
        raise Exception(f"Erreur Monday: {data['errors']}")
    return data


def _extract_text_from_column(col: dict) -> str:
    """Renvoie le texte 'humain' d'une colonne Monday."""
    if col.get("text"):
        return str(col["text"])
    raw_val = col.get("value")
    if raw_val in (None, ""):
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

# ================== Lecture d’item ==================

def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
    """
    Récupère name + un sous-ensemble de colonnes (par id),
    et renvoie un dict {col_id: texte}.
    """
    col_ids = [c for c in (column_ids or []) if c]
    col_ids = list(dict.fromkeys(col_ids))

    query = """
    query ($item_id: ID!, $col_ids: [String!]) {
      items(ids: [$item_id]) {
        name
        column_values(ids: $col_ids) {
          id
          type
          text
          value
        }
      }
    }
    """
    data = _post(query, {"item_id": str(item_id), "col_ids": col_ids})
    items = (data.get("data") or {}).get("items") or []
    if not items:
        return {}

    item = items[0]
    result = {"name": item.get("name", "")}
    for col in item.get("column_values", []):
        cid = col["id"]
        result[cid] = _extract_text_from_column(col)
        result[cid + "__raw"] = col.get("value") or ""
    return result


# ================== Métadonnées de board ==================

def get_board_columns_map():
    """
    Renvoie:
      - cols: liste brute des colonnes
      - id_to_title: {id -> titre}
      - title_to_id: {titre -> id}
      - formulas: {id -> expression formula}
      - col_types: {id -> type}
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
    boards = (data.get("data") or {}).get("boards") or []
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

# ================== Formules: numérique & texte ==================

def _translate_monday_expr(expr: str) -> str:
    """Petit traducteur d'expressions Monday -> Python safe (arith/booleen)."""
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


# ================== Mutations ==================

def set_link_in_column(item_id: int, column_id: str, url: str, text: str):
    """
    Met à jour une colonne Lien sur Monday avec un lien cliquable.
    ⚠️ Très important : ne pas envoyer tout l’objet PayPlug, seulement {url, text}.
    """
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
        "item_id": str(item_id),
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
        "item_id": str(item_id),
        "column_id": column_id,
        "value": label
    })
