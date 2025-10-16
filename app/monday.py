import requests
from fastapi import HTTPException
from .config import settings
import json


# --- Récupérer les colonnes d’un item ---
def get_item_columns(item_id: int, column_ids: list[str]) -> dict:
    """
    Récupère les colonnes d’un élément Monday (email, adresse, etc.)
    """
    query = {
        "query": f"""
        query {{
            items (ids: {item_id}) {{
                id
                name
                column_values {{
                    id
                    text
                    value
                }}
            }}
        }}
        """
    }

    headers = {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post("https://api.monday.com/v2", headers=headers, json=query)
    res = r.json()
    print("🔍 Monday response:", json.dumps(res, indent=2))

    # --- Gestion des erreurs ---
    if "data" not in res:
        raise HTTPException(500, f"Erreur Monday: {res}")

    items = res["data"]["items"]
    if not items:
        return {}

    result = {}
    for col in items[0]["column_values"]:
        if col["id"] in column_ids:
            result[col["id"]] = col
    return result


# --- Récupérer la valeur d’une formule (montant) ---
def get_formula_display_value(item_id: int, formula_column_id: str) -> str:
    """
    Retourne la valeur affichée d’une colonne formule (ex: montant acompte)
    """
    query = {
        "query": f"""
        query {{
            items (ids: {item_id}) {{
                column_values (ids: ["{formula_column_id}"]) {{
                    text
                }}
            }}
        }}
        """
    }

    headers = {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post("https://api.monday.com/v2", headers=headers, json=query)
    res = r.json()
    print(f"🔢 Formula response for {formula_column_id}:", json.dumps(res, indent=2))

    try:
        return res["data"]["items"][0]["column_values"][0]["text"]
    except Exception:
        return ""


# --- Écrire un lien dans une colonne (PayPlug ou Devis) ---
def set_link_in_column(item_id: int, board_id: int, column_id: str, url: str, text: str):
    """
    Met à jour une colonne lien sur Monday
    """
    mutation = {
        "query": f"""
        mutation {{
            change_column_value (
                board_id: {board_id},
                item_id: {item_id},
                column_id: "{column_id}",
                value: "{{\\"url\\": \\"{url}\\", \\"text\\": \\"{text}\\"}}"
            ) {{
                id
            }}
        }}
        """
    }

    headers = {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post("https://api.monday.com/v2", headers=headers, json=mutation)
    res = r.json()
    print("🔗 Monday link update:", json.dumps(res, indent=2))

    if "errors" in res:
        raise HTTPException(500, f"Erreur Monday lors de l’écriture du lien: {res}")


# --- Mettre à jour le statut d’un item (ex: payé) ---
def set_status(item_id: int, board_id: int, column_id: str, label: str):
    """
    Change un statut sur Monday (ex: 'Payé acompte')
    """
    mutation = {
        "query": f"""
        mutation {{
            change_simple_column_value (
                board_id: {board_id},
                item_id: {item_id},
                column_id: "{column_id}",
                value: "{label}"
            ) {{
                id
            }}
        }}
        """
    }

    headers = {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post("https://api.monday.com/v2", headers=headers, json=mutation)
    res = r.json()
    print("🟩 Monday status update:", json.dumps(res, indent=2))

    if "errors" in res:
        raise HTTPException(500, f"Erreur Monday lors du changement de statut: {res}")
