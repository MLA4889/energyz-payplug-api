# app/monday.py
from typing import Any, Dict
import json
import requests
from fastapi import HTTPException

from .config import settings

MONDAY_API_URL = "https://api.monday.com/v2"


def _headers() -> Dict[str, str]:
    return {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }


def get_item_columns(item_id: int, column_ids: list[str]) -> Dict[str, Any]:
    """
    Récupère les colonnes 'text/value/type' (utile pour Email/Adresse/etc.).
    """
    query = """
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        column_values {
          id
          text
          value
          type
        }
      }
    }"""
    data = {"query": query, "variables": {"itemId": [item_id]}}
    r = requests.post(MONDAY_API_URL, json=data, headers=_headers())
    r.raise_for_status()
    items = r.json().get("data", {}).get("items", [])
    if not items:
        return {}
    out: Dict[str, Any] = {}
    for col in items[0].get("column_values", []):
        if col["id"] in column_ids:
            out[col["id"]] = {
                "text": col.get("text"),
                "value": col.get("value"),
                "type": col.get("type"),
            }
    return out


def get_formula_display_value(item_id: int, formula_column_id: str) -> str:
    """
    Lecture FIABLE du display_value d'une colonne Formula :
    - on cible la colonne par 'ids:'
    - on caste avec le fragment '... on FormulaValue'
    """
    query = """
    query ($itemId: [ID!], $columnId: [String!]) {
      items(ids: $itemId) {
        column_values(ids: $columnId) {
          ... on FormulaValue {
            id
            display_value
          }
        }
      }
    }"""
    data = {"query": query, "variables": {"itemId": [item_id], "columnId": [formula_column_id]}}
    r = requests.post(MONDAY_API_URL, json=data, headers=_headers())
    r.raise_for_status()
    items = r.json().get("data", {}).get("items", [])
    if not items:
        return ""
    cvs = items[0].get("column_values", [])
    return (cvs[0].get("display_value") if cvs else "") or ""


def _raise_if_graphql_error(resp_json: Dict[str, Any]) -> None:
    """
    Monday peut renvoyer HTTP 200 avec 'errors': [...]
    On remonte l'erreur pour la voir dans les logs/réponses.
    """
    if "errors" in resp_json and resp_json["errors"]:
        raise HTTPException(status_code=500, detail=f"Monday error: {resp_json['errors']}")


def set_link_in_column(item_id: int, board_id: int, column_id: str, url: str, text: str = "Payer") -> None:
    """
    Écrit un lien dans une colonne Link.
    IMPORTANT : Monday attend column_values en CHAÎNE JSON, pas en objet Python.
    """
    col_values = {column_id: {"url": url, "text": text}}
    col_values_str = json.dumps(col_values)

    mutation = """
    mutation ($itemId: Int!, $boardId: Int!, $columnValues: JSON!) {
      change_multiple_column_values(
        item_id: $itemId,
        board_id: $boardId,
        column_values: $columnValues
      ) { id }
    }"""
    payload = {
        "query": mutation,
        "variables": {
            "itemId": item_id,
            "boardId": board_id,
            "columnValues": col_values_str
        },
    }
    r = requests.post(MONDAY_API_URL, json=payload, headers=_headers())
    r.raise_for_status()
    data = r.json()
    _raise_if_graphql_error(data)

    # Optionnel : on s'assure qu'un id est bien renvoyé
    try:
        _ = data["data"]["change_multiple_column_values"]["id"]
    except Exception:
        raise HTTPException(status_code=500, detail=f"Unexpected Monday response: {data}")


def set_status(item_id: int, board_id: int, status_column_id: str, label: str) -> None:
    """
    Met à jour une colonne Status avec un label donné.
    On passe aussi column_values en chaîne JSON.
    """
    col_values = {status_column_id: {"label": label}}
    col_values_str = json.dumps(col_values)

    mutation = """
    mutation ($itemId: Int!, $boardId: Int!, $columnValues: JSON!) {
      change_multiple_column_values(
        item_id: $itemId,
        board_id: $boardId,
        column_values: $columnValues
      ) { id }
    }"""
    payload = {
        "query": mutation,
        "variables": {
            "itemId": item_id,
            "boardId": board_id,
            "columnValues": col_values_str
        },
    }
    r = requests.post(MONDAY_API_URL, json=payload, headers=_headers())
    r.raise_for_status()
    data = r.json()
    _raise_if_graphql_error(data)

    try:
        _ = data["data"]["change_multiple_column_values"]["id"]
    except Exception:
        raise HTTPException(status_code=500, detail=f"Unexpected Monday response: {data}")
