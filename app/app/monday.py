import requests
from typing import Any, Dict
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"

def _headers() -> Dict[str, str]:
    return {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }

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
    data = {"query": query, "variables": {"itemId": [item_id]}}
    r = requests.post(MONDAY_API_URL, json=data, headers=_headers())
    r.raise_for_status()
    items = r.json().get("data", {}).get("items", [])
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
          ... on FormulaValue {
            id
            display_value
          }
        }
      }
    }"""
    data = {"query": query, "variables": {"itemId": [item_id], "columnId": [formula_column_id]}}
    r = requests.post(MONDAY_API_URL, json=data, headers=_headers())
    r.raise_for_status()
    items = r.json().get("data", {}).get("items", [])
    if not items:
        return ""
    cvs = items[0].get("column_values", [])
    return (cvs[0].get("display_value") if cvs else "") or ""

def set_link_in_column(item_id: int, board_id: int, column_id: str, url: str, text: str = "Payer") -> None:
    col_values = {column_id: {"url": url, "text": text}}
    mutation = """
    mutation ($itemId: Int!, $boardId: Int!, $columnValues: JSON!) {
      change_multiple_column_values(item_id: $itemId, board_id: $boardId, column_values: $columnValues) { id }
    }"""
    payload = {"query": mutation, "variables": {"itemId": item_id, "boardId": board_id, "columnValues": col_values}}
    r = requests.post(MONDAY_API_URL, json=payload, headers=_headers())
    r.raise_for_status()

def set_status(item_id: int, board_id: int, status_column_id: str, label: str) -> None:
    col_values = {status_column_id: {"label": label}}
    mutation = """
    mutation ($itemId: Int!, $boardId: Int!, $columnValues: JSON!) {
      change_multiple_column_values(item_id: $itemId, board_id: $boardId, column_values: $columnValues) { id }
    }"""
    payload = {"query": mutation, "variables": {"itemId": item_id, "boardId": board_id, "columnValues": col_values}}
    r = requests.post(MONDAY_API_URL, json=payload, headers=_headers())
    r.raise_for_status()
