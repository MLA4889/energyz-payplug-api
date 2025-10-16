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
    colmap = {cv["id"]: cv for cv in item["column_values"]}
    return {"item_id": int(item["id"]), "name": item["name"], "columns": colmap}


def _cv_text(columns: Dict[str, Any], col_id: str) -> str:
    cv = columns.get(col_id)
    return (cv.get("text") if cv else "") or ""


def get_formula_display_value(columns: Dict[str, Any], formula_col_id: str) -> Optional[str]:
    if not formula_col_id:
        return None
    txt = _cv_text(columns, formula_col_id)
    return txt or None


def get_status_text(columns: Dict[str, Any], status_col_id: str) -> str:
    if not status_col_id:
        return ""
    return _cv_text(columns, status_col_id).strip()


def get_iban_via_formula_or_status(columns: Dict[str, Any]) -> str:
    # 1) essayer la colonne formula IBAN
    if settings.IBAN_FORMULA_COLUMN_ID:
        iban = get_formula_display_value(columns, settings.IBAN_FORMULA_COLUMN_ID)
        if iban:
            return iban.strip()

    # 2) fallback : mapping par statut Business Line / Société
    status_txt = get_status_text(columns, settings.BUSINESS_STATUS_COLUMN_ID)
    if status_txt and status_txt in settings.PAYPLUG_IBAN_BY_STATUS:
        return settings.PAYPLUG_IBAN_BY_STATUS[status_txt]

    return ""


def get_amount_from_formula_or_mapping(columns: Dict[str, Any], formula_col_id: str, acompten: int) -> float:
    # 1) essai via colonne formula (si Monday renvoie quelque chose)
    if formula_col_id:
        txt = get_formula_display_value(columns, formula_col_id)
        if txt:
            try:
                return float(str(txt).replace(",", "."))
            except Exception:
                pass

    # 2) fallback : mapping par statut
    status_txt = get_status_text(columns, settings.BUSINESS_STATUS_COLUMN_ID)
    mapping = settings.ACOMPTE_AMOUNTS.get(str(acompten), {})
    val = mapping.get(status_txt)
    if val is not None:
        return float(val)

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
    url = f"{settings.MONDAY_API_URL}/file"
    r = requests.post(url, headers={"Authorization": settings.MONDAY_API_KEY}, files=files, timeout=90)
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"Upload fichier Monday échoué ({r.status_code}): {detail}")
