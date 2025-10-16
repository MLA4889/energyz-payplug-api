import json, mimetypes, re, requests
from typing import Any, Dict, Optional
from .config import settings

HEADERS = {"Authorization": settings.MONDAY_API_KEY}

def _gql(query: str, variables: dict | None = None) -> dict:
    r = requests.post(
        settings.MONDAY_API_URL,
        headers={**HEADERS, "Content-Type": "application/json"},
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

def cv_text(cols: Dict[str, Any], col_id: str) -> str:
    if not col_id: return ""
    cv = cols.get(col_id)
    return (cv.get("text") if cv else "") or ""

def get_formula_display_value(cols: Dict[str, Any], formula_col_id: str) -> Optional[str]:
    if not formula_col_id: return None
    cv = cols.get(formula_col_id)
    return (cv.get("text") if cv else None)

def set_status(item_id: int, status_column_id: str, label: str) -> None:
    q = """
    mutation($item_id: Int!, $column_id: String!, $label: String!) {
      change_simple_column_value(item_id: $item_id, column_id: $column_id, value: $label) { id }
    }
    """
    _gql(q, {"item_id": item_id, "column_id": status_column_id, "label": label})

def set_link_in_column(item_id: int, column_id: str, url: str, text: str) -> None:
    value = json.dumps({"url": url, "text": text})
    q = """
    mutation($item_id:Int!, $column_id:String!, $value:JSON!) {
      change_column_value(item_id:$item_id, column_id:$column_id, value:$value) { id }
    }
    """
    _gql(q, {"item_id": item_id, "column_id": column_id, "value": value})

def extract_address_fields(cols: Dict[str, Any]) -> dict:
    addr_txt = cv_text(cols, settings.ADDRESS_COLUMN_ID)
    postcode = cv_text(cols, settings.POSTCODE_COLUMN_ID)
    city = cv_text(cols, settings.CITY_COLUMN_ID)

    if (not postcode or not city) and addr_txt:
        m = re.search(r"\b(\d{5})\s+([A-Za-zÀ-ÿ\-\s']+)$", addr_txt.strip())
        if m:
            if not postcode: postcode = m.group(1).strip()
            if not city: city = m.group(2).strip()

    return {"address": addr_txt.strip(), "postcode": postcode.strip(), "city": city.strip()}
