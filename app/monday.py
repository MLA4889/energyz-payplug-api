import json
import requests
from .config import settings


MONDAY_API_URL = "https://api.monday.com/v2"
HEADERS = {
    "Authorization": settings.MONDAY_API_KEY,
    "Content-Type": "application/json"
}


# --- Récupère les valeurs des colonnes importantes ---
def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
    """Retourne les valeurs texte des colonnes demandées pour un item Monday."""
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
    variables = {"item_id": item_id}
    response = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    response.raise_for_status()
    data = response.json()

    if "errors" in data:
        raise Exception(f"Erreur Monday: {data['errors']}")

    item = data["data"]["items"][0]
    result = {"name": item["name"]}

    for col in item["column_values"]:
        if col["id"] in column_ids:
            result[col["id"]] = col.get("text") or ""
    return result


# --- Écrit un lien de paiement dans une colonne ---
def set_link_in_column(item_id: int, column_id: str, url: str, text: str):
    """Met à jour une colonne 'Lien' avec le lien PayPlug."""
    mutation = """
    mutation ($item_id: ID!, $column_id: String!, $value: JSON!) {
        change_simple_column_value(item_id: $item_id, column_id: $column_id, value: $value) {
            id
        }
    }
    """
    value = json.dumps({"url": url, "text": text})
    variables = {"item_id": item_id, "column_id": column_id, "value": value}
    response = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": mutation, "variables": variables})
    response.raise_for_status()


# --- Met à jour un statut de paiement ---
def set_status(item_id: int, column_id: str, label: str):
    """Met à jour la colonne 'Statut' dans Monday."""
    mutation = """
    mutation ($item_id: ID!, $column_id: String!, $value: String!) {
        change_simple_column_value(item_id: $item_id, column_id: $column_id, value: $value) {
            id
        }
    }
    """
    variables = {"item_id": item_id, "column_id": column_id, "value": label}
    response = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": mutation, "variables": variables})
    response.raise_for_status()
