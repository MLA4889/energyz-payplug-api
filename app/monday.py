import json as _json
import requests
from typing import Any, Dict
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"

def _headers() -> Dict[str, str]:
    return {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }

def _post(query: str, variables: Dict[str, Any], tag: str) -> Dict[str, Any]:
    """Post GraphQL to Monday and raise on errors."""
    r = requests.post(MONDAY_API_URL, json={"query": query, "variables": variables}, headers=_headers())
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        print(f"❌ Monday API error ({tag}): {data}")
        raise RuntimeError(data["errors"][0].get("message", "Unknown Monday error"))
    return data.get("data", {})

def get_item_columns(item_id: int, column_ids: list[str]) -> Dict[str, Any]:
    query = """
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        column_values { id text value type }
      }
    }"""
    data = _post(query, {"itemId": [item_id]}, tag="get_item_columns")
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
    data = _post(query, {"itemId": [item_id], "columnId": [formula_column_id]}, tag="get_formula_display_value")
    items = data.get("items", [])
    if not items:
        return ""
    cvs = items[0].get("column_values", [])
    return (cvs[0].get("display_value") if cvs else "") or ""

def set_link_in_column(item_id: int, board_id: int, column_id: str, url: str, text: str = "Payer") -> None:
    """
    Écrit un lien cliquable dans une colonne de type Link sur Monday.
    """
    col_values = {
        column_id: _json.dumps({"url": url, "text": text})
    }
    mutation = """
    mutation ($itemId: ID!, $boardId: ID!, $columnValues: JSON!) {
      change_multiple_column_values(item_id: $itemId, board_id: $boardId, column_values: $columnValues) {
        id
      }
    }"""
    vars = {
        "itemId": item_id,
        "boardId": board_id,
        "columnValues": _json.dumps(col_values)
    }
    print(f"🧩 set_link_in_column → {vars}")
    _post(mutation, vars, tag="set_link_in_column")

def set_status(item_id: int, board_id: int, status_column_id: str, label: str) -> None:
    """
    Change un statut dans une colonne Monday.
    """
    col_values = {
        status_column_id: _json.dumps({"label": label})
    }
    mutation = """
    mutation ($itemId: ID!, $boardId: ID!, $columnValues: JSON!) {
      change_multiple_column_values(item_id: $itemId, board_id: $boardId, column_values: $columnValues) {
        id
      }
    }"""
    vars = {
        "itemId": item_id,
        "boardId": board_id,
        "columnValues": _json.dumps(col_values)
    }
    print(f"🧩 set_status → {vars}")
    _post(mutation, vars, tag="set_status")
