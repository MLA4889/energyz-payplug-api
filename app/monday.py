import requests
import json
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"
HEADERS = {
    "Authorization": settings.MONDAY_API_KEY,
    "Content-Type": "application/json"
}


# --- Récupère les colonnes d'un item ---
def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
    """Retourne les valeurs texte des colonnes demandées"""
    query = """
    query ($item_id: Int!) {
        items (ids: [$item_id]) {
            column_values {
                id
                text
                value
            }
        }
    }
    """
    response = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query, "variables": {"item_id": item_id}})
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise Exception(f"Erreur Monday: {data['errors']}")
    cols = data["data"]["items"][0]["column_values"]
    result = {}
    for col in cols:
        if col["id"] in column_ids:
            result[col["id"]] = {"text": col.get("text") or "", "value": col.get("value")}
    return result


# --- Récupère la valeur affichée d’une formule ---
def get_formula_display_value(item_id: int, column_id: str) -> str:
    """Récupère le texte visible d'une formule Monday"""
    query = """
    query ($item_id: Int!, $column_id: String!) {
        items (ids: [$item_id]) {
            column_values(ids: [$column_id]) {
                id
                text
            }
        }
    }
    """
    variables = {"item_id": item_id, "column_id": column_id}
    response = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    response.raise_for_status()
    data = response.json()
    try:
        text_value = data["data"]["items"][0]["column_values"][0]["text"]
        return text_value.strip() if text_value else ""
    except Exception:
        return ""


# --- Met à jour un lien dans une colonne ---
def set_link_in_column(item_id: int, board_id: int, column_id: str, url: str, text: str = "Payer"):
    """Écrit un lien cliquable dans Monday"""
    mutation = """
    mutation ($item_id: Int!, $board_id: Int!, $column_id: String!, $value: JSON!) {
        change_simple_column_value(
            item_id: $item_id,
            board_id: $board_id,
            column_id: $column_id,
            value: $value
        ) {
            id
        }
    }
    """
    value = json.dumps({"url": url, "text": text})
    variables = {"item_id": item_id, "board_id": board_id, "column_id": column_id, "value": value}
    res = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": mutation, "variables": variables})
    res.raise_for_status()
    return res.json()


# --- Change un statut ---
def set_status(item_id: int, board_id: int, column_id: str, label: str):
    mutation = """
    mutation ($item_id: Int!, $board_id: Int!, $column_id: String!, $value: String!) {
        change_simple_column_value(
            item_id: $item_id,
            board_id: $board_id,
            column_id: $column_id,
            value: $value
        ) {
            id
        }
    }
    """
    variables = {"item_id": item_id, "board_id": board_id, "column_id": column_id, "value": label}
    res = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": mutation, "variables": variables})
    res.raise_for_status()
    return res.json()
