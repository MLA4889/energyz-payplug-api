import json
import requests
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"
HEADERS = {
    "Authorization": settings.MONDAY_API_KEY,
    "Content-Type": "application/json"
}

def _post(query: str, variables: dict):
    r = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise Exception(f"Erreur Monday: {data['errors']}")
    return data

def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
    # On ramène name + column_values (id, text, value) puis on expose aussi __raw
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
        cid = col["id"]
        if cid in column_ids:
            result[cid] = col.get("text") or ""
        # on expose toujours le RAW (JSON) si on en a besoin
        result[f"{cid}__raw"] = col.get("value") or ""
    return result

def set_link_in_column(item_id: int, column_id: str, url: str, text: str):
    mutation = """
    mutation ($item_id: ID!, $column_id: String!, $value: JSON!) {
      change_simple_column_value(item_id: $item_id, column_id: $column_id, value: $value) { id }
    }
    """
    value = json.dumps({"url": url, "text": text})
    _post(mutation, {"item_id": item_id, "column_id": column_id, "value": value})

def set_status(item_id: int, column_id: str, label: str):
    mutation = """
    mutation ($item_id: ID!, $column_id: String!, $value: String!) {
      change_simple_column_value(item_id: $item_id, column_id: $column_id, value: $value) { id }
    }
    """
    _post(mutation, {"item_id": item_id, "column_id": column_id, "value": label})
