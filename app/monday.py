import json as _json
import requests
from typing import Any, Dict
from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"


# ---------------------- Utils ----------------------
def _headers() -> Dict[str, str]:
    """Prépare les headers de requête pour l’API Monday."""
    return {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }


def _post(query: str, variables: Dict[str, Any], tag: str) -> Dict[str, Any]:
    """
    Envoie une requête GraphQL vers Monday.
    Affiche les erreurs détaillées si la requête échoue.
    """
    try:
        r = requests.post(MONDAY_API_URL, json={"query": query, "variables": variables}, headers=_headers())
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            print(f"🧭 Erreur Monday API ({tag}): {data}")
            raise RuntimeError(data["errors"][0].get("message", "Erreur inconnue Monday"))
        return data.get("data", {})
    except Exception as e:
        print(f"❌ Exception dans _post ({tag}): {e}")
        raise


# ---------------------- Récupération ----------------------
def get_item_columns(item_id: int, column_ids: list[str]) -> Dict[str, Any]:
    """Récupère les valeurs de colonnes d’un item spécifique sur Monday."""
    query = """
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        column_values { id text value type }
      }
    }"""
    data = _post(query, {"itemId": [item_id]}, tag="get_item_columns")
    items = data.get("items", [])
    if not items:
        return {}
    out = {}
    for col in items[0].get("column_values", []):
        if col["id"] in column_ids:
            out[col["id"]] = {"text": col.get("text"), "value": col.get("value"), "type": col.get("type")}
    return out


def get_formula_display_value(item_id: int, formula_column_id: str) -> str:
    """Récupère la valeur affichée (display_value) d’une colonne Formula."""
    query = """
    query ($itemId: [ID!], $columnId: [String!]) {
      items (ids: $itemId) {
        column_values(ids: $columnId) {
          ... on FormulaValue { id display_value }
        }
      }
    }"""
    data = _post(query, {"itemId": [item_id], "columnId": [formula_column_id]}, tag="get_formula_display_value")
    items = data.get("items", [])
    if not items:
        return ""
    cvs = items[0].get("column_values", [])
    return (cvs[0].get("display_value") if cvs else "") or ""


# ---------------------- Écriture ----------------------
def set_link_in_column(item_id: int, board_id: int, column_id: str, url: str, text: str = "Payer") -> None:
    """
    ✅ Corrigé : écrit un lien cliquable "Payer" dans une colonne Link sur Monday.
    Assure que 'url' soit bien dans le champ du lien et 'text' dans le texte à afficher.
    """
    mutation = """
    mutation ($itemId: ID!, $boardId: ID!, $columnValues: JSON!) {
      change_multiple_column_values(item_id: $itemId, board_id: $boardId, column_values: $columnValues) {
        id
      }
    }"""

    # 🩵 Correction : inversion text/url pour compatibilité Monday
    column_values = {
        column_id: {"text": text, "url": url}
    }

    vars = {
        "itemId": item_id,
        "boardId": board_id,
        "columnValues": _json.dumps(column_values)  # JSON encodé une seule fois ✅
    }

    print(f"🔗 set_link_in_column (fix inversion) → {vars}")
    _post(mutation, vars, tag="set_link_in_column")


def set_status(item_id: int, board_id: int, status_column_id: str, label: str) -> None:
    """✅ Met à jour une colonne de statut sur Monday."""
    mutation = """
    mutation ($itemId: ID!, $boardId: ID!, $columnValues: JSON!) {
      change_multiple_column_values(item_id: $itemId, board_id: $boardId, column_values: $columnValues) {
        id
      }
    }"""
    column_values = {status_column_id: {"label": label}}

    vars = {
        "itemId": item_id,
        "boardId": board_id,
        "columnValues": _json.dumps(column_values)
    }

    print(f"🎨 set_status (final) → {vars}")
    _post(mutation, vars, tag="set_status")
