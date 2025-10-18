import requests
import datetime as dt
from typing import Optional, Tuple, Dict, Any
from .config import settings

# --------------------------------------------------------------------------------------
# Auth session
# --------------------------------------------------------------------------------------

SESSION = {"token": None}

def _login() -> str:
    url = f"{settings.EVOLIZ_BASE_URL}/api/login"
    r = requests.post(
        url,
        json={"public_key": settings.EVOLIZ_PUBLIC_KEY, "secret_key": settings.EVOLIZ_SECRET_KEY},
        headers={"Content-Type": "application/json"},
        timeout=25,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise Exception(f"Evoliz login: token missing in response: {data}")
    SESSION["token"] = token
    return token

def _headers() -> dict:
    if not SESSION["token"]:
        _login()
    return {
        "Authorization": f"Bearer {SESSION['token']}",
        "Content-Type": "application/json",
    }

def _get(path: str, params: dict | None = None):
    url = f"{settings.EVOLIZ_BASE_URL}{path}"
    r = requests.get(url, headers=_headers(), params=params or {}, timeout=25)
    if r.status_code == 401:
        _login()
        r = requests.get(url, headers=_headers(), params=params or {}, timeout=25)
    r.raise_for_status()
    return r.json()

def _post(path: str, payload: dict):
    url = f"{settings.EVOLIZ_BASE_URL}{path}"
    r = requests.post(url, headers=_headers(), json=payload, timeout=25)
    if r.status_code == 401:
        _login()
        r = requests.post(url, headers=_headers(), json=payload, timeout=25)
    if not r.ok:
        raise Exception(f"Evoliz API error {r.status_code}: {r.text}")
    return r.json()

# --------------------------------------------------------------------------------------
# Lookups (client/prospect)
# --------------------------------------------------------------------------------------

def _find_client_by_email(email: str) -> Optional[str]:
    if not email:
        return None
    try:
        data = _get(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients", params={"search": email})
        items = data if isinstance(data, list) else data.get("data") or []
        for it in items:
            if str(it.get("email", "")).lower() == email.lower():
                return str(it.get("id") or it.get("clientid"))
    except Exception:
        pass
    return None

def _find_prospect_by_email(email: str) -> Optional[str]:
    if not email:
        return None
    try:
        data = _get(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/prospects", params={"search": email})
        items = data if isinstance(data, list) else data.get("data") or []
        for it in items:
            if str(it.get("email", "")).lower() == email.lower():
                return str(it.get("id") or it.get("prospectid"))
    except Exception:
        pass
    return None

def _find_prospect_by_name(name: str) -> Optional[str]:
    if not name:
        return None
    try:
        data = _get(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/prospects", params={"search": name})
        items = data if isinstance(data, list) else data.get("data") or []
        for it in items:
            if str(it.get("name", "")).strip().lower() == name.strip().lower():
                return str(it.get("id") or it.get("prospectid"))
    except Exception:
        pass
    return None

# --------------------------------------------------------------------------------------
# Address normalization (Monday "location" → Evoliz)
# --------------------------------------------------------------------------------------

def _normalize_address(addr: Dict[str, Any] | None) -> Dict[str, str]:
    addr = addr or {}
    street_obj = addr.get("street") or {}
    city_obj   = addr.get("city") or {}
    country    = addr.get("country") or {}

    street   = (street_obj.get("long_name") or addr.get("address") or "").strip() or "Adresse non précisée"
    town     = (city_obj.get("long_name") or "").strip() or "N/A"
    iso2     = (country.get("short_name") or country.get("shortName") or "").strip() or "FR"
    postcode = (addr.get("postalCode") or addr.get("postcode") or "").strip() or "00000"

    return {"street": street, "town": town, "postcode": postcode, "iso2": iso2}

# --------------------------------------------------------------------------------------
# Prospect creation (robuste, gère "name has already been taken")
# --------------------------------------------------------------------------------------

def _create_prospect(name: str, email: str, address_json: Dict[str, Any] | None) -> Optional[str]:
    address = _normalize_address(address_json)
    payload = {
        "name": name or (email.split("@")[0] if email else "Prospect"),
        "email": email or "",
        "address": address,
    }
    try:
        data = _post(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/prospects", payload)
        return str(data.get("id") or data.get("prospectid") or data.get("data", {}).get("id"))
    except Exception as e:
        msg = str(e).lower()
        if "name has already been taken" in msg:
            pid = _find_prospect_by_name(payload["name"])
            if pid:
                return pid
        raise

def ensure_recipient(name: str, email: str, address_json: Dict[str, Any] | None) -> Tuple[Optional[str], Optional[str]]:
    if settings.EVOLIZ_DEFAULT_CLIENT_ID:
        return (str(settings.EVOLIZ_DEFAULT_CLIENT_ID), None)

    cid = _find_client_by_email(email)
    if cid:
        return (cid, None)

    pid = _find_prospect_by_email(email)
    if pid:
        return (None, pid)

    pid = _find_prospect_by_name(name)
    if pid:
        return (None, pid)

    pid = _create_prospect(name, email, address_json)
    return (None, pid)

# --------------------------------------------------------------------------------------
# Quotes
# --------------------------------------------------------------------------------------

def create_quote(
    label: str,
    description: str,
    unit_price_ht: float,
    vat_rate: float,
    recipient_name: str,
    recipient_email: str,
    recipient_address_json: Dict[str, Any] | None
) -> dict:
    """
    Crée un devis Evoliz :
      - documentdate (YYYY-MM-DD)
      - clientid OU prospectid
      - term.paytermid (1 = comptant)
      - items[{designation, quantity, unit_price, vat_rate}]
    """
    clientid, prospectid = ensure_recipient(recipient_name, recipient_email, recipient_address_json)

    payload = {
        "label": label or description or "Devis",
        "documentdate": dt.date.today().isoformat(),
        "status": "draft",
        "term": {"paytermid": 1},  # IMPORTANT: 'paytermid' (pas 'paymentid')
        "items": [
            {
                "designation": description or label or "Prestation",
                "quantity": 1,
                "unit_price": round(float(unit_price_ht), 2),
                "vat_rate": round(float(vat_rate), 2),
            }
        ],
    }
    if clientid:
        payload["clientid"] = clientid
    elif prospectid:
        payload["prospectid"] = prospectid

    return _post(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes", payload)

def get_quote(quote_id: str) -> dict:
    """Relit un devis par ID pour récupérer number/links éventuels."""
    return _get(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{quote_id}")

def extract_public_link(quote_response: dict) -> Optional[str]:
    """Tente d'extraire un lien partageable depuis la création ou la consultation."""
    # 1) test direct
    for key in ["public_link", "public_url", "portal_url", "share_link", "url", "download_url", "pdf_url"]:
        v = quote_response.get(key)
        if v:
            return v
    nested = (quote_response.get("data") or quote_response.get("quote") or {})
    for key in ["public_link", "public_url", "portal_url", "share_link", "url"]:
        v = nested.get(key)
        if v:
            return v

    # 2) si on a un id, on relit le devis et on réessaie
    qid = str(quote_response.get("id") or nested.get("id") or "")
    if qid:
        try:
            full = get_quote(qid)
            for key in ["public_link", "public_url", "portal_url", "share_link", "url", "download_url", "pdf_url"]:
                v = full.get(key) or (full.get("data") or {}).get(key)
                if v:
                    return v
        except Exception:
            pass

    return None

def extract_identifiers(quote_response: dict) -> Tuple[Optional[str], Optional[str]]:
    """Retourne (id, number) si dispo pour afficher un libellé utile dans Monday."""
    data = quote_response.get("data") or quote_response
    qid = str(data.get("id") or data.get("quoteid") or "")
    number = str(data.get("number") or data.get("quotenumber") or "")
    return (qid or None, number or None)
