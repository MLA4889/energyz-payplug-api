import requests
import json
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"
HEADERS = {
    "Authorization": settings.MONDAY_API_KEY,
    "Content-Type": "application/json"
}


# --- Récupère les colonnes d'un item ---
def get_item_columns(item_id: int | str, column_ids: list[str]) -> dict:
    """
    Retourne les valeurs texte des colonnes demandées.
    Supporte aussi les colonnes de formule (récupère .text proprement).
    """
    query = """
    query ($item_id: ID!) {
        items (ids: [$item_id]) {
            column_values {
                id
                text
                value
            }
        }
    }
    """
    variables = {"item_id": str(item_id)}  # 🔧 cast en string pour type ID!
    response = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    response.raise_for_status()
    data = response.json()

    # Gestion d’erreurs Monday
    if "errors" in data:
        raise Exception(f"Erreur Monday: {data['errors']}")

    cols = data.get("data", {}).get("items", [])[0].get("column_values", [])
    result = {}

    for col in cols:
        if col["id"] in column_ids:
            result[col["id"]] = {
                "text": (col.get("text") or "").strip(),
                "value": col.get("value")
            }

    return result


# --- Récupère la valeur affichée d’une formule ---
def get_formula_display_value(item_id: int | str, column_id: str) -> str:
    """
    Récupère la valeur texte affichée d'une colonne formule Monday.
    Utilise le champ .text pour récupérer la valeur visible dans l’UI.
    """
    query = """
    query ($item_id: ID!, $column_id: String!) {
        items (ids: [$item_id]) {
            column_values(ids: [$column_id]) {
                id
                text
            }
        }
    }
    """
    variables = {"item_id": str(item_id), "column_id": column_id}
    response = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    response.raise_for_status()
    data = response.json()

    if "errors" in data:
        raise Exception(f"Erreur formule Monday: {data['errors']}")

    try:
        text_value = data["data"]["items"][0]["column_values"][0].get("text")
        return text_value.strip() if text_value else ""
    except Exception:
        return ""


# --- Met à jour un lien dans une colonne ---
def set_link_in_column(item_id: int | str, board_id: int | str, column_id: str, url: str, text: str = "Payer"):
    """
    Écrit un lien cliquable dans Monday.
    Exemple : set_link_in_column(12345, 67890, "link_col_id", "https://...", "Payer")
    """
    mutation = """
    mutation ($item_id: ID!, $board_id: ID!, $column_id: String!, $value: JSON!) {
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
    variables = {
        "item_id": str(item_id),
        "board_id": str(board_id),
        "column_id": column_id,
        "value": value
    }

    res = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": mutation, "variables": variables})
    res.raise_for_status()

    data = res.json()
    if "errors" in data:
        raise Exception(f"Erreur écriture lien Monday: {data['errors']}")
    return data


# --- Change un statut dans une colonne Monday ---
def set_status(item_id: int | str, board_id: int | str, column_id: str, label: str):
    """
    Met à jour un statut simple dans Monday (ex: “Payé acompte 1”)
    """
    mutation = """
    mutation ($item_id: ID!, $board_id: ID!, $column_id: String!, $value: String!) {
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
    variables = {
        "item_id": str(item_id),
        "board_id": str(board_id),
        "column_id": column_id,
        "value": label
    }

    res = requests.post(MONDAY_API_URL, headers=HEADERS, json={"query": mutation, "variables": variables})
    res.raise_for_status()

    data = res.json()
    if "errors" in data:
        raise Exception(f"Erreur changement statut Monday: {data['errors']}")
    return data
