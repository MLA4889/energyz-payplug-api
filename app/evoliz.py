import requests
import datetime as dt
from typing import Optional, Tuple, Dict, Any
from .config import settings

SESSION = {"token": None}

def _login() -> str:
    url = f"{settings.EVOLIZ_BASE_URL}/api/login"
    r = requests.post(url, json={
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY
    }, headers={"Content-Type": "application/json"})
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
        "Content-Type": "application/json"
    }

def _get(path: str, params: dict | None = None):
    url = f"{settings.EVOLIZ_BASE_URL}{path}"
    r = requests.get(url, headers=_headers(), params=params or {})
    if r.status_code == 401:
        _login()
        r = requests.get(url, headers=_headers(), params=params or {})
    r.raise_for_status()
    return r.json()

def _post(path: str, payload: dict):
    url = f"{settings.EVOLIZ_BASE_URL}{path}"
    r = requests.post(url, headers=_headers(), json=payload)
    if r.status_code == 401:
        _login()
        r = requests.post(url, headers=_headers(), json=payload)
    if not r.ok:
        raise Exception(f"Evoliz API error {r.status_code}: {r.text}")
    return r.json()

# ---------- Helpers client/prospect ----------

def _find_client_by_email(email: str) -> Optional[str]:
    try:
        data = _get(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients", params={"search": email})
        items = data if isinstance(data, list) else data.get("data") or []
        for it in items:
            if str(it.get("email", "")).lower() == (email or "").lower():
                return str(it.get("id") or it.get("clientid"))
    except Exception:
        pass
    return None

def _normalize_address(addr: Dict[str, Any] | None) -> Dict[str, str]:
    """
    Transforme le JSON 'location' de Monday en adresse Evoliz:
    - street: street.long_name (ou address)
    - town: city.long_name
    - postcode: '00000' si absent
    - iso2: country.short_name (FR, MA, EG, …)
    """
    addr = addr or {}
    street_obj = addr.get("street") or {}
    city_obj   = addr.get("city") or {}
    country    = addr.get("country") or {}

    street  = (street_obj.get("long_name") or addr.get("address") or "").strip()
    town    = (city_obj.get("long_name") or "").strip()
    iso2    = (country.get("short_name") or country.get("shortName") or "").strip()  # 2 lettres
    postcode = (addr.get("postalCode") or addr.get("postcode") or "").strip()

    if not postcode:
        postcode = "00000"           # fallback propre pour passer la validation Evoliz
    if not town:
        town = "N/A"                 # fallback
    if not street:
        street = "Adresse non précisée"
    if not iso2:
        iso2 = "FR"                  # fallback raisonnable (à adapter si besoin)

    return {"street": street, "town": town, "postcode": postcode, "iso2": iso2}

def _create_prospect(name: str, email: str, address_json: Dict[str, Any] | None) -> Optional[str]:
    address = _normalize_address(address_json)
    payload = {
        "name": name or (email.split("@")[0] if email else "Prospect"),
        "email": email or "",
        "address": address
    }
    data = _post(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/prospects", payload)
    return str(data.get("id") or data.get("prospectid") or data.get("data", {}).get("id"))

def ensure_recipient(name: str, email: str, address_json: Dict[str, Any] | None) -> Tuple[Optional[str], Optional[str]]:
    # 1) client forcé
    if settings.EVOLIZ_DEFAULT_CLIENT_ID:
        return (str(settings.EVOLIZ_DEFAULT_CLIENT_ID), None)
    # 2) recherche client
    if email:
        cid = _find_client_by_email(email)
        if cid:
            return (cid, None)
    # 3) création prospect (avec adresse complète)
    pid = _create_prospect(name, email, address_json)
    return (None, pid)

# ---------- Quote ----------

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
    Crée un devis conforme aux exigences Evoliz.
    - documentdate
    - clientid OU prospectid (créé si nécessaire, avec adresse complète)
    - term.paymentid
    - items[]
    """
    clientid, prospectid = ensure_recipient(recipient_name, recipient_email, recipient_address_json)

    payload = {
        "label": label or description or "Devis",
        "documentdate": dt.date.today().isoformat(),
        "status": "draft",
        "term": {"paymentid": 1},  # 1 = comptant
        "items": [
            {
                "designation": description or label or "Prestation",
                "quantity": 1,
                "unit_price": round(float(unit_price_ht), 2),
                "vat_rate": round(float(vat_rate), 2)
            }
        ]
    }
    if clientid:
        payload["clientid"] = clientid
    elif prospectid:
        payload["prospectid"] = prospectid

    return _post(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes", payload)

def extract_public_link(quote_response: dict) -> Optional[str]:
    for key in ["public_link", "public_url", "portal_url", "share_link", "url", "download_url", "pdf_url"]:
        v = quote_response.get(key)
        if v:
            return v
    nested = (quote_response.get("data") or quote_response.get("quote") or {})
    for key in ["public_link", "public_url", "portal_url", "share_link", "url"]:
        v = nested.get(key)
        if v:
            return v
    return None
