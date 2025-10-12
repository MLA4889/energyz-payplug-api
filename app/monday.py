# app/monday.py
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
    """Poste une requête GraphQL sur Monday et lève une erreur si 'errors' présent."""
    r = requests.post(MONDAY_API_URL, json={"query": query, "variables": variables}, headers=_headers())
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        # Log verbeux pour diagnostiquer facilement dans Render
        print(f"🧭 Monday API response ({tag}): {data}")
        # Lève une exception lisible (remontera 500 côté FastAPI, visible dans les logs)
        raise RuntimeError(data["errors"][0].get("message", "Unknown Monday error"))
    return data.get("data", {})

def get_item_columns(item_id: int, column_ids: list[str]) -> Dict[str, Any]:
    query = """
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        column_values {
          id
          text
          value
          type
        }
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
    # lecture fiable du display_value d'une colonne Formula, ciblée par id
    query = """
    query ($itemId: [ID!], $columnId: [String!]) {
      items (ids: $itemId) {
        column_values(ids: $columnId) {
          ... on FormulaValue {
            id
            display_value
          }
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
    # IMPORTANT: Monday attend une *chaîne* JSON dans column_values, pas un dict Python
    col_values = {column_id: {"url": url, "text": text}}
    mutation = """
    mutation ($itemId: ID!, $boardId: ID!, $columnValues: JSON!) {
      change_multiple_column_values(item_id: $itemId, board_id: $boardId, column_values: $columnValues) { id }
    }"""
    variables = {
        "itemId": item_id,
        "boardId": board_id,
        "columnValues": _json.dumps(col_values)  # <-- stringify obligatoire
    }
    _post(mutation, variables, tag="set_link_in_column")

def set_status(item_id: int, board_id: int, status_column_id: str, label: str) -> None:
    col_values = {status_column_id: {"label": label}}
    mutation = """
    mutation ($itemId: ID!, $boardId: ID!, $columnValues: JSON!) {
      change_multiple_column_values(item_id: $itemId, board_id: $boardId, column_values: $columnValues) { id }
    }"""
    variables = {
        "itemId": item_id,
        "boardId": board_id,
        "columnValues": _json.dumps(col_values)  # <-- stringify obligatoire
    }
    _post(mutation, variables, tag="set_status")
