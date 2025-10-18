import json
import requests
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"
HEADERS = {
    "Authorization": settings.MONDAY_API_KEY,
    "Content-Type": "application/json",
}

def _post(query: str, variables: dict | None = None):
    r = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query, "variables": variables or {}})
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise Exception(f"Erreur Monday: {data['errors']}")
    return data

def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
    """
    Retourne: { "name": ..., "<id>": <text>, "<id>__raw": <value JSON string> }
    (la clé __raw est indispensable pour récupérer la valeur des formules)
    """
    query = """
    query ($item_id: ID!) {
        items (ids: [$item_id]) {
            name
            column_values { id text value }
        }
    }
    """
    data = _post(query, {"item_id": item_id})
    item = data["data"]["items"][0]
    result = {"name": item["name"]}
    wanted = set(column_ids)

    for col in item["column_values"]:
        cid = col["id"]
        if cid in wanted:
            result[cid] = col.get("text") or ""
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

# (si tu utilises l’upload de fichiers plus tard)
def upload_file_to_column(item_id: int, column_id: str, filename: str, content: bytes):
    mutation = """
    mutation($file: File!, $item_id: Int!, $column_id: String!) {
      add_file_to_column (file: $file, item_id: $item_id, column_id: $column_id) { id }
    }
    """
    operations = json.dumps({
        "query": mutation,
        "variables": {"item_id": int(item_id), "column_id": column_id, "file": None},
    })
    map_ = json.dumps({"0": ["variables.file"]})
    files = {
        "operations": (None, operations),
        "map": (None, map_),
        "0": (filename, content, "application/pdf"),
    }
    r = requests.post(MONDAY_API_URL, headers={"Authorization": settings.MONDAY_API_KEY}, files=files)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise Exception(f"Erreur Monday upload: {data['errors']}")
