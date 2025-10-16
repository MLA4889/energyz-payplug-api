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
    # Note: ne pas demander "additional_info" – certaines versions de l’API ne l’exposent pas
    q = """
    query($item_id: [Int]) {
      items(ids: $item_id) {
        id
        name
        column_values { id text value type }
      }
    }
    """
    data = _gql(q, {"item_id": item_id})
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"Item {item_id} introuvable.")
    item = items[0]
    colmap = {cv["id"]: cv for cv in item["column_values"]}
    return {"item_id": int(item["id"]), "name": item["name"], "columns": colmap}


# --------------------- helpers extraction ---------------------

_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")

def _clean_text_number(s: str) -> str:
    """Retire €, espaces, etc. et renvoie la 1ère forme numérique trouvée dans s."""
    if not s:
        return ""
    # remplace virgule par point, retire euros et espaces
    s2 = s.replace("€", " ").replace("\u00a0", " ").strip()
    m = _NUM_RE.search(s2)
    return (m.group(0) if m else "").replace(",", ".")


def _extract_from_value_field(raw: Any) -> str:
    """`value` peut être None, un nombre simple, une string, ou un JSON sérialisé."""
    if raw is None:
        return ""
    # nombre direct
    if isinstance(raw, (int, float)):
        return str(raw)
    # string
    if isinstance(raw, str):
        # si JSON sérialisé -> tente json.loads
        t = raw.strip()
        if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
            try:
                parsed = json.loads(t)
            except Exception:
                # pas du JSON exploitable -> essaie d'extraire un nombre de la string brute
                return _clean_text_number(t)
            # cherche des champs classiques
            for key in ("text", "value", "display_value", "formatted"):
                v = parsed.get(key) if isinstance(parsed, dict) else None
                if v:
                    return _clean_text_number(str(v))
            # sinon, tente une extraction brute
            return _clean_text_number(t)
        # pas du JSON -> extraction brute
        return _clean_text_number(t)
    # fallback
    return _clean_text_number(str(raw))


def get_formula_display_value(columns: Dict[str, Any], formula_col_id: str) -> Optional[str]:
    """
    Renvoie une string numérique exploitable depuis une colonne Formula.
    Essaye d'abord 'text', puis parse 'value' (souvent JSON).
    """
    cv = columns.get(formula_col_id)
    if not cv:
        return None

    # 1) le plus simple : text
    txt = (cv.get("text") or "").strip()
    if txt:
        cleaned = _clean_text_number(txt)
        if cleaned:
            return cleaned

    # 2) sinon, value (souvent JSON)
    return _extract_from_value_field(cv.get("value")) or None


# --------------------- autres utilitaires Monday ---------------------

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


def upload_file_to_files_column(item_id: int, column_id: str, filename: str, content: bytes) -> None:
    """Upload via GraphQL multipart → /v2/file (obligatoire)."""
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
