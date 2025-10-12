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


# -----------------------------
# READ HELPERS
# -----------------------------
def get_item_columns(item_id: int, column_ids: list[str]) -> Dict[str, Any]:
    """
    Récupère les colonnes 'text/value/type' (Email, Adresse, etc.)
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
      - on cible par ids:
      - on caste avec ... on FormulaValue
    """
    if not formula_column_id:
        return ""
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


# -----------------------------
# WRITE HELPERS
# -----------------------------
def _raise_if_graphql_error(resp_json: Dict[str, Any]) -> None:
    """
    Monday peut renvoyer HTTP 200 mais 'errors': [...]
    On remonte clairement l'erreur.
    """
    if "errors" in resp_json and resp_json["errors"]:
        raise HTTPException(status_code=500, detail=f"Monday error: {resp_json['errors']}")


def set_link_in_column(item_id: int, board_id: int, column_id: str, url: str, text: str = "Payer") -> None:
    """
    Écrit un lien dans une colonne Link.
    IMPORTANT :
      - column_values doit être une CHAÎNE JSON.
      - $itemId et $boardId doivent être typés ID! côté GraphQL et envoyés en str côté variables.
    Log la réponse pour débogage.
    """
    col_values = {column_id: {"url": url, "text": text}}
    col_values_str = json.dumps(col_values)

    mutation = """
    mutation ($itemId: ID!, $boardId: ID!, $columnValues: JSON!) {
      change_multiple_column_values(
        item_id: $itemId,
        board_id: $boardId,
        column_values: $columnValues
      ) { id }
    }"""
    payload = {
        "query": mutation,
        "variables": {
            # envoyer en str pour respecter ID!
            "itemId": str(item_id),
            "boardId": str(board_id),
            "columnValues": col_values_str
        },
    }

    r = requests.post(MONDAY_API_URL, json=payload, headers=_headers())
    try:
        r.raise_for_status()
    except Exception:
        print("❌ HTTP ERROR from Monday:", r.text)
        raise

    data = r.json()
    print("📬 Monday API response (link):", json.dumps(data, indent=2, ensure_ascii=False))
    _raise_if_graphql_error(data)

    try:
        _ = data["data"]["change_multiple_column_values"]["id"]
    except Exception:
        raise HTTPException(status_code=500, detail=f"Unexpected Monday response: {data}")


def set_status(item_id: int, board_id: int, status_column_id: str, label: str) -> None:
    """
    Met à jour une colonne Status avec un label donné.
    IMPORTANT :
      - column_values doit être une CHAÎNE JSON.
      - $itemId et $boardId typés ID! et envoyés en str.
    """
    col_values = {status_column_id: {"label": label}}
    col_values_str = json.dumps(col_values)

    mutation = """
    mutation ($itemId: ID!, $boardId: ID!, $columnValues: JSON!) {
      change_multiple_column_values(
        item_id: $itemId,
        board_id: $boardId,
        column_values: $columnValues
      ) { id }
    }"""
    payload = {
        "query": mutation,
        "variables": {
            "itemId": str(item_id),
            "boardId": str(board_id),
            "columnValues": col_values_str
        },
    }

    r = requests.post(MONDAY_API_URL, json=payload, headers=_headers())
    try:
        r.raise_for_status()
    except Exception:
        print("❌ HTTP ERROR from Monday:", r.text)
        raise

    data = r.json()
    print("📬 Monday API response (status):", json.dumps(data, indent=2, ensure_ascii=False))
    _raise_if_graphql_error(data)

    try:
        _ = data["data"]["change_multiple_column_values"]["id"]
    except Exception:
        raise HTTPException(status_code=500, detail=f"Unexpected Monday response: {data}")
