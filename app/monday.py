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

def _post(query: str):
    resp = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("errors"):
        raise Exception(f"Erreur Monday: {data['errors']}")
    return data

def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
    query = """
    query {
      items (ids: [%d]) {
        name
        column_values {
          id
          text
          value
        }
      }
    }
    """ % item_id
    data = _post(query)
    items = (data.get("data") or {}).get("items") or []
    if not items:
        return {}
    item = items[0]
    result = {"name": item.get("name", "")}
    for col in item.get("column_values", []):
        result[col["id"]] = col.get("text") or ""
    return result

def set_link_in_column(item_id: int, column_id: str, url: str, text: str):
    mutation = f"""
    mutation {{
      change_column_value (
        board_id: {settings.MONDAY_BOARD_ID},
        item_id: {item_id},
        column_id: "{column_id}",
        value: "{{\\"url\\":\\"{url}\\",\\"text\\":\\"{text}\\"}}"
      ) {{
        id
      }}
    }}
    """
    _post(mutation)

def set_status(item_id: int, column_id: str, label: str):
    mutation = f"""
    mutation {{
      change_simple_column_value (
        board_id: {settings.MONDAY_BOARD_ID},
        item_id: {item_id},
        column_id: "{column_id}",
        value: "{label}"
      ) {{
        id
      }}
    }}
    """
    _post(mutation)
