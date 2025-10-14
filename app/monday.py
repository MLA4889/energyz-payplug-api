# app/monday.py
import json
import mimetypes
import re
from typing import Any, Dict, Optional

import requests

from .config import settings

# ---- Auth header Monday ----
MONDAY_HEADERS = {"Authorization": settings.MONDAY_API_KEY}


# ---- Low-level GraphQL call ----
def _gql(query: str, variables: dict | None = None) -> dict:
    """
    Envoie une requête GraphQL vers Monday. Lève RuntimeError si Monday renvoie "errors".
    """
    r = requests.post(
        settings.MONDAY_API_URL,  # ex: https://api.monday.com/v2
        headers={**MONDAY_HEADERS, "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"Monday GraphQL error: {data['errors']}")
    return data["data"]


# ---- Lecture d'un item + toutes ses column_values ----
def get_item_columns(item_id: int) -> Dict[str, Any]:
    """
    Retourne: {
      'item_id': int,
      'name': str,
      'columns': { '<col_id>': {id, text, value, type}, ... }
    }
    """
    q = """
    query ($item_id: [ID!]) {
      items(ids: $item_id) {
        id
        name
        column_values { id text value type }
      }
    }
    """
    data = _gql(q, {"item_id": [str(item_id)]})
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"Item {item_id} introuvable.")
    item = items[0]
    colmap = {cv["id"]: cv for cv in (item.get("column_values") or [])}
    return {"item_id": int(item["id"]), "name": item.get("name", ""), "columns": colmap}


# ---- Lecture "formula" tolérante: d'abord text, sinon value (JSON) ----
def get_formula_display_value(columns: Dict[str, Any], formula_col_id: str) -> Optional[str]:
    """
    Monday renvoie parfois text="" pour les colonnes formula, mais la vraie
    valeur est dans "value" (souvent une chaîne JSON).
    On tente d'abord `text`, puis on parse `value`.
    """
    cv = columns.get(formula_col_id)
    if not cv:
        return None

    # 1) préférer .text quand il est fourni
    txt = cv.get("text")
    if txt:
        return txt

    # 2) fallback: parser .value
    raw = cv.get("value")
    if not raw:
        return None

    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, str) else str(parsed)
    except Exception:
        return str(raw).strip('"').strip()


# ---- Ecrire un status simple ----
def set_status(item_id: int, status_column_id: str, label: str) -> None:
    q = """
    mutation($item_id: Int!, $column_id: String!, $label: String!) {
      change_simple_column_value(item_id: $item_id, column_id: $column_id, value: $label) { id }
    }
    """
    _gql(q, {"item_id": int(item_id), "column_id": status_column_id, "label": label})


# ---- Ecrire un lien (colonne Link) ----
def set_link_in_column(item_id: int, column_id: str, url: str, text: str = "Ouvrir") -> None:
    value = json.dumps({"url": url, "text": text})
    q = """
    mutation($item_id:Int!, $column_id:String!, $value: JSON!) {
      change_column_value(item_id:$item_id, column_id:$column_id, value:$value) { id }
    }
    """
    _gql(q, {"item_id": int(item_id), "column_id": column_id, "value": value})


# ---- Extraction adresse, CP, ville ----
def extract_address_fields(columns: Dict[str, Any]) -> dict:
    def _cv_text(col_id: str) -> str:
        cv = columns.get(col_id)
        return (cv.get("text") if cv else "") or ""

    addr_txt = _cv_text(settings.ADDRESS_COLUMN_ID) if settings.ADDRESS_COLUMN_ID else ""
    postcode = _cv_text(settings.POSTCODE_COLUMN_ID) if settings.POSTCODE_COLUMN_ID else ""
    city = _cv_text(settings.CITY_COLUMN_ID) if settings.CITY_COLUMN_ID else ""

    if (not postcode or not city) and addr_txt:
        m = re.search(r"\b(\d{5})\s+([A-Za-zÀ-ÿ\-\s']+)$", addr_txt.strip())
        if m:
            postcode = postcode or m.group(1).strip()
            city = city or m.group(2).strip()

    return {"address": addr_txt.strip(), "postcode": postcode.strip(), "city": city.strip()}


# ---- Upload d'un fichier dans une colonne Files ----
def upload_file_to_files_column(item_id: int, column_id: str, filename: str, content: bytes) -> None:
    """
    Upload GraphQL multipart OBLIGATOIRE sur /v2/file.
    """
    if not column_id:
        raise RuntimeError("Aucune colonne Files (column_id) fournie pour l'upload.")

    mtype, _ = mimetypes.guess_type(filename)
    if not mtype:
        mtype = "application/pdf"

    operations = {
        "query": """
          mutation ($file: File!, $item: Int!, $column: String!) {
            add_file_to_column(file: $file, item_id: $item, column_id: $column) { id }
          }
        """,
        "variables": {"file": None, "item": int(item_id), "column": column_id},
    }
    files = {
        "operations": (None, json.dumps(operations), "application/json"),
        "map": (None, json.dumps({"0": ["variables.file"]}), "application/json"),
        "0": (filename, content, mtype),
    }

    url = f"{settings.MONDAY_API_URL}/file"  # IMPORTANT
    r = requests.post(url, headers=MONDAY_HEADERS, files=files, timeout=90)

    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"Upload fichier Monday échoué ({r.status_code}): {detail}")
