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
        # remonter l'erreur Monday lisible
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
            # on prend text si dispo, sinon value brut
            result[col["id"]] = col.get("text") or ""
    return result

def set_link_in_column(item_id: int, column_id: str, url: str, text: str):
    """
    Pour une colonne de type LINK, utiliser change_column_value
    et passer value sous forme de JSON stringifié {"url":..,"text":..}
    """
    mutation = """
    mutation ($item_id: ID!, $column_id: String!, $value: JSON!) {
      change_column_value(item_id: $item_id, column_id: $column_id, value: $value) {
        id
      }
    }
    """
    # ATTENTION: Monday attend une string JSON dans "value", pas un objet Python
    link_value = json.dumps({"url": url, "text": text}, ensure_ascii=False)
    _post(mutation, {"item_id": item_id, "column_id": column_id, "value": link_value})

def set_status(item_id: int, column_id: str, label: str):
    """
    Pour les status simples, change_simple_column_value fonctionne bien.
    """
    mutation = """
    mutation ($item_id: ID!, $column_id: String!, $value: String!) {
      change_simple_column_value(item_id: $item_id, column_id: $column_id, value: $value) {
        id
      }
    }
    """
    _post(mutation, {"item_id": item_id, "column_id": column_id, "value": label})
