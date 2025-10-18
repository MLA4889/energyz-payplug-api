import json
import requests
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"
HEADERS = {
    "Authorization": settings.MONDAY_API_KEY,
    "Content-Type": "application/json",
}


def _post(query: str, variables: dict):
    r = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise Exception(f"Erreur Monday: {data['errors']}")
    return data


def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
    """
    Ramène le name + toutes les colonnes,
    expose `text` et le JSON brut en suffixe `__raw`.
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
        cid = col["id"]
        if cid in column_ids:
            result[cid] = col.get("text") or ""
        result[f"{cid}__raw"] = col.get("value") or ""
    return result


def set_link_in_column(item_id: int, column_id: str, url: str, text: str):
    """
    Utilise change_column_value (avec board_id) et envoie une CHAÎNE JSON.
    """
    mutation = """
    mutation ($board_id: ID!, $item_id: ID!, $column_id: String!, $value: JSON!) {
      change_column_value(board_id: $board_id, item_id: $item_id, column_id: $column_id, value: $value) {
        id
      }
    }
    """
    # IMPORTANT : value doit être une chaîne JSON
    value = json.dumps({"url": url, "text": text})
    variables = {
        "board_id": settings.MONDAY_BOARD_ID,
        "item_id": item_id,
        "column_id": column_id,
        "value": value,
    }
    _post(mutation, variables)


def set_status(item_id: int, column_id: str, label: str):
    """
    Pour un Status, change_column_value attend aussi une CHAÎNE JSON : {"label": "Mon statut"}.
    """
    mutation = """
    mutation ($board_id: ID!, $item_id: ID!, $column_id: String!, $value: JSON!) {
      change_column_value(board_id: $board_id, item_id: $item_id, column_id: $column_id, value: $value) {
        id
      }
    }
    """
    value = json.dumps({"label": label})
    variables = {
        "board_id": settings.MONDAY_BOARD_ID,
        "item_id": item_id,
        "column_id": column_id,
        "value": value,
    }
    _post(mutation, variables)
