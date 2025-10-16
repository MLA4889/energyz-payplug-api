import json
import mimetypes
import requests
from typing import Any, Dict, Optional

from .config import settings


def _headers() -> dict:
    return {
        "Authorization": settings.MONDAY_API_KEY,
        "Content-Type": "application/json",
    }


def gql(query: str, variables: dict | None = None) -> dict:
    r = requests.post(
        settings.MONDAY_API_URL,
        headers=_headers(),
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"Monday GQL error: {data['errors']}")
    return data["data"]


def get_item_columns(item_id: int) -> Dict[str, Dict[str, Any]]:
    """
    Retourne un dict: {column_id: {"text": ..., "value": parsed_or_raw, "label": status_label_if_any}}
    On interroge text ET value (JSON), et reconstruit une valeur 'display' robuste.
    """
    q = """
    query ($item_id: [ID!]!) {
      items (ids: $item_id) {
        id
        name
        column_values {
          id
          text
          value
          type
          additional_info
        }
      }
    }
    """
    d = gql(q, {"item_id": [str(item_id)]})
    items = d.get("items", [])
    if not items:
        raise RuntimeError(f"Item {item_id} introuvable")

    cv = items[0]["column_values"]
    out: Dict[str, Dict[str, Any]] = {}
    for c in cv:
        raw_value = c.get("value")
        parsed = None
        if raw_value:
            try:
                parsed = json.loads(raw_value)
            except Exception:
                parsed = raw_value

        addi = c.get("additional_info")
        addi_parsed = None
        if addi:
            try:
                addi_parsed = json.loads(addi)
            except Exception:
                addi_parsed = addi

        # Pour les status: label dans parsed.get('label') si type == 'status'
        label = None
        if c.get("type") == "status" and isinstance(parsed, dict):
            label = parsed.get("label")

        out[c["id"]] = {
            "text": c.get("text") or "",
            "value": parsed,
            "type": c.get("type"),
            "additional_info": addi_parsed,
            "label": label,
        }

    # Toujours ajouter le name (utile en fallback description)
    out["name"] = {"text": items[0]["name"], "value": items[0]["name"], "type": "name", "label": None}
    return out


def get_status_label(columns: Dict[str, Dict[str, Any]], col_id: str) -> str | None:
    c = columns.get(col_id)
    if not c:
        return None
    # label de status si dispo
    if c.get("label"):
        return c["label"]
    # parfois label est dans "text"
    if c.get("text"):
        return c["text"]
    # fallback: value JSON -> label
    v = c.get("value")
    if isinstance(v, dict):
        return v.get("label")
    return None


def extract_display_number(cell: Dict[str, Any]) -> Optional[float]:
    """
    Essaie d'obtenir un nombre depuis:
    - cell["text"] (ex: "1 234,56")
    - cell["value"] => {"amount": "1234.56"} ou {"text": "..."}
    - additional_info
    """
    # 1) text
    t = (cell or {}).get("text", "").strip()
    def _to_float(txt: str) -> Optional[float]:
        if not txt:
            return None
        # tolérant: vire espaces, remplace virgule par point
        normalized = txt.replace(" ", "").replace("\u202f", "").replace(",", ".")
        try:
            return float(normalized)
        except Exception:
            return None

    n = _to_float(t)
    if n is not None:
        return n

    # 2) value JSON
    v = (cell or {}).get("value")
    if isinstance(v, dict):
        # cas numbers monday: {"changed_at":"...","value":"1234.56"}
        if "value" in v:
            n = _to_float(str(v.get("value", "")))
            if n is not None:
                return n
        if "amount" in v:
            n = _to_float(str(v.get("amount", "")))
            if n is not None:
                return n
        if "text" in v:
            n = _to_float(str(v.get("text", "")))
            if n is not None:
                return n

    # 3) additional_info (rare)
    ai = (cell or {}).get("additional_info")
    if isinstance(ai, dict):
        if "value" in ai:
            n = _to_float(str(ai.get("value", "")))
            if n is not None:
                return n
        if "text" in ai:
            n = _to_float(str(ai.get("text", "")))
            if n is not None:
                return n
    return None


def extract_display_text(cell: Dict[str, Any]) -> Optional[str]:
    """
    Pour FORMULA (IBAN / description), on tente text -> value.text -> additional_info.text
    """
    if not cell:
        return None
    t = (cell.get("text") or "").strip()
    if t:
        return t
    v = cell.get("value")
    if isinstance(v, dict):
        for k in ("text", "value", "label"):
            val = v.get(k)
            if isinstance(val, str) and val.strip():
                return val.strip()
    ai = cell.get("additional_info")
    if isinstance(ai, dict):
        for k in ("text", "value", "label"):
            val = ai.get(k)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def set_link_in_column(item_id: int, column_id: str, url: str, title: str = "Ouvrir") -> None:
    """
    Met un link column sous forme valeur JSON: {"url":"...","text":"..."}
    """
    if not column_id:
        return
    mutation = """
    mutation ($item_id: ID!, $column_id: String!, $val: JSON!) {
      change_simple_column_value (item_id: $item_id, column_id: $column_id, value: $val) { id }
    }
    """
    value = {"url": url, "text": title}
    gql(mutation, {"item_id": str(item_id), "column_id": column_id, "val": json.dumps(value)})


def set_status(item_id: int, column_id: str, label: str) -> None:
    if not column_id or not label:
        return
    mutation = """
    mutation ($item_id: ID!, $column_id: String!, $label: String!) {
      change_column_value(item_id: $item_id, column_id: $column_id, value: {label: $label}) { id }
    }
    """
    gql(mutation, {"item_id": str(item_id), "column_id": column_id, "label": label})


def upload_file_to_column(item_id: int, column_id: str, filename: str, content: bytes) -> None:
    """
    Upload d'un fichier sur une colonne Files via /v2/file
    """
    if not column_id or not content:
        return
    url = settings.MONDAY_API_URL + "/file"
    query = """
    mutation add_file($file: File!, $item_id: ID!, $column_id: String!) {
      add_file_to_column(file: $file, item_id: $item_id, column_id: $column_id) { id }
    }
    """
    files = [
        ('query', (None, query)),
        ('variables', (None, json.dumps({"item_id": str(item_id), "column_id": column_id}))),
        ('map', (None, json.dumps({"file": ["variables.file"]}))),
    ]
    mime = mimetypes.guess_type(filename)[0] or "application/pdf"
    files.append(('file', (filename, content, mime)))
    r = requests.post(url, headers={"Authorization": settings.MONDAY_API_KEY}, files=files, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        # Tolérant : on ne bloque pas le process si l'upload échoue.
        pass
