import json as _json
import requests
from typing import Any, Dict
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"


# --- Base HTTP ---
def _headers() -> Dict[str, str]:
    return {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }


def _post(query: str, variables: Dict[str, Any], tag: str) -> Dict[str, Any]:
    r = requests.post(MONDAY_API_URL, json={"query": query, "variables": variables}, headers=_headers())
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        print(f"🧭 Monday API error ({tag}): {data}")
        raise RuntimeError(data["errors"][0].get("message", "Unknown Monday error"))
    return data.get("data", {})


# --- Lecture ---
def get_item_columns(item_id: int, column_ids: list[str]) -> Dict[str, Any]:
    query = """
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        column_values { id text value type }
      }
    }"""
    data = _post(query, {"itemId": [str(item_id)]}, tag="get_item_columns")
    items = data.get("items", [])
    if not items:
        return {}
    out = {}
    for col in items[0].get("column_values", []):
        if col["id"] in column_ids:
            out[col["id"]] = {"text": col.get("text"), "value": col.get("value"), "type": col.get("type")}
    return out


def get_formula_display_value(item_id: int, formula_column_id: str) -> str:
    query = """
    query ($itemId: [ID!], $columnId: [String!]) {
      items (ids: $itemId) {
        column_values(ids: $columnId) {
          ... on FormulaValue { id display_value }
        }
      }
    }"""
    data = _post(query, {"itemId": [str(item_id)], "columnId": [formula_column_id]}, tag="get_formula_display_value")
    items = data.get("items", [])
    if not items:
        return ""
    cvs = items[0].get("column_values", [])
    return (cvs[0].get("display_value") if cvs else "") or ""


# --- Écriture du lien ---
def set_link_in_column(item_id: int, board_id: int, column_id: str, url: str, text: str = "Payer") -> None:
    """Écrit un lien cliquable dans une colonne Link (format correct Monday)"""
    column_values = _json.dumps({column_id: {"url": url, "text": text}})

    # ⚠️ Monday n’aime pas JSON dans les variables — on injecte directement
    query = f"""
    mutation {{
      change_multiple_column_values(
        item_id: {item_id},
        board_id: {board_id},
        column_values: {column_values}
      ) {{
        id
      }}
    }}
    """

    r = requests.post(MONDAY_API_URL, json={"query": query}, headers=_headers())
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        print(f"🧭 Monday API error (set_link_in_column): {data}")
        raise RuntimeError(data["errors"][0].get("message", "Unknown Monday error"))


# --- Écriture du statut ---
def set_status(item_id: int, board_id: int, status_column_id: str, label: str) -> None:
    """Change un statut dans une colonne de type status"""
    column_values = _json.dumps({status_column_id: {"label": label}})

    query = f"""
    mutation {{
      change_multiple_column_values(
        item_id: {item_id},
        board_id: {board_id},
        column_values: {column_values}
      ) {{
        id
      }}
    }}
    """

    r = requests.post(MONDAY_API_URL, json={"query": query}, headers=_headers())
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        print(f"🧭 Monday API error (set_status): {data}")
        raise RuntimeError(data["errors"][0].get("message", "Unknown Monday error"))
