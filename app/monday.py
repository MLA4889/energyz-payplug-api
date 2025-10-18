import json
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

def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
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
            result[col["id"]] = col.get("text") or ""
    return result

def set_link_in_column(item_id: int, column_id: str, url: str, text: str):
    """
    For LINK columns, use change_column_value with board_id and a JSON-stringified value.
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
        "item_id": item_id,
        "column_id": column_id,
        "value": link_value
    })

def set_status(item_id: int, column_id: str, label: str):
    """
    Status update with board_id for compatibility.
    """
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
