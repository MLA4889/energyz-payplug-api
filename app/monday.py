import json
import mimetypes
import re
from typing import Any, Dict, Optional

import requests
from .config import settings

MONDAY_HEADERS = {"Authorization": settings.MONDAY_API_KEY}


def _gql(query: str, variables: dict | None = None) -> dict:
    r = requests.post(
        settings.MONDAY_API_URL,
        headers={**MONDAY_HEADERS, "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"Monday GraphQL error: {data['errors']}")
    return data["data"]


def get_item_columns(item_id: int) -> Dict[str, Any]:
    # IMPORTANT: type ID! (sinon erreur)
    q = """
    query($item_id: ID!) {
      items(ids: [$item_id]) {
        id
        name
        column_values { id text value type }
      }
    }
    """
    data = _gql(q, {"item_id": str(item_id)})
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"Item {item_id} introuvable.")
    item = items[0]
    return {
        "item_id": int(item["id"]),
        "name": item["name"],
        "columns": {cv["id"]: cv for cv in (item.get("column_values") or [])},
    }


def _cv_text(columns: Dict[str, Any], col_id: str) -> str:
    cv = columns.get(col_id)
    if not cv:
        return ""
    # 1) souvent ok
    if cv.get("text"):
        return str(cv["text"]).strip()
    # 2) parfois Monday met le "text" dans value (JSON)
    try:
        if cv.get("value"):
            v = cv["value"]
            if isinstance(v, str):
                v = json.loads(v)
            if isinstance(v, dict):
                t = v.get("text")
                if t:
                    return str(t).strip()
    except Exception:
        pass
    return ""


def get_formula_text(columns: Dict[str, Any], formula_col_id: str) -> Optional[str]:
    if not formula_col_id:
        return None
    return _cv_text(columns, formula_col_id) or None


def get_formula_number(columns: Dict[str, Any], formula_col_id: str) -> float:
    """Renvoie un nombre (float) à partir d'une colonne formula."""
    txt = get_formula_text(columns, formula_col_id) or ""
    if not txt:
        return 0.0
    # nettoyer €
    txt = txt.replace("€", "").replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return float(txt)
    except Exception:
        return 0.0


def set_status(item_id: int, status_column_id: str, label: str) -> None:
    q = """
    mutation($item_id: Int!, $column_id: String!, $label: String!) {
      change_simple_column_value(item_id: $item_id, column_id: $column_id, value: $label) { id }
    }
    """
    _gql(q, {"item_id": item_id, "column_id": status_column_id, "label": label})


def set_link_in_column(item_id: int, column_id: str, url: str, text: str = "Ouvrir") -> None:
    value = json.dumps({"url": url, "text": text})
    q = """
    mutation($item_id:Int!, $column_id:String!, $value:JSON!) {
      change_column_value(item_id:$item_id, column_id:$column_id, value:$value) { id }
    }
    """
    _gql(q, {"item_id": item_id, "column_id": column_id, "value": value})


def extract_address_fields(columns: Dict[str, Any]) -> dict:
    addr_txt = _cv_text(columns, settings.ADDRESS_COLUMN_ID) if settings.ADDRESS_COLUMN_ID else ""
    postcode = _cv_text(columns, settings.POSTCODE_COLUMN_ID) if settings.POSTCODE_COLUMN_ID else ""
    city = _cv_text(columns, settings.CITY_COLUMN_ID) if settings.CITY_COLUMN_ID else ""

    if (not postcode or not city) and addr_txt:
        m = re.search(r"\b(\d{5})\s+([A-Za-zÀ-ÿ\-\s']+)$", addr_txt.strip())
        if m:
            postcode = postcode or m.group(1).strip()
            city = city or m.group(2).strip()

    return {"address": addr_txt.strip(), "postcode": postcode.strip(), "city": city.strip()}


def upload_file_to_files_column(item_id: int, column_id: str, filename: str, content: bytes) -> None:
    if not column_id:
        raise RuntimeError("Aucune colonne Files (column_id) fournie.")
    mtype, _ = mimetypes.guess_type(filename)
    if not mtype:
        mtype = "application/pdf"

    operations = {
        "query": """
          mutation ($file: File!, $item: Int!, $column: String!) {
            add_file_to_column(file: $file, item_id: $item, column_id: $column) { id }
          }
        """,
        "variables": {"file": None, "item": item_id, "column": column_id},
    }
    files = {
        "operations": (None, json.dumps(operations), "application/json"),
        "map": (None, json.dumps({"0": ["variables.file"]}), "application/json"),
        "0": (filename, content, mtype),
    }
    url = f"{settings.MONDAY_API_URL}/file"  # /v2/file
    r = requests.post(url, headers={"Authorization": settings.MONDAY_API_KEY}, files=files, timeout=90)
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"Upload fichier Monday échoué ({r.status_code}): {detail}")
