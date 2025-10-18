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

# ---------- Helpers de recherche ----------

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
        # certains endpoints ne filtrent pas strictement → on re-vérifie
        for it in items:
            if str(it.get("name", "")).strip().lower() == name.strip().lower():
                return str(it.get("id") or it.get("prospectid"))
    except Exception:
        pass
    return None

# ---------- Normalisation adresse ----------

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

# ---------- Création de prospect (avec reprise sur “name taken”) ----------

def _create_prospect(name: str, email: str, address_json: Dict[str, Any] | None) -> Optional[str]:
    address = _normalize_address(address_json)
    payload = {
        "name": name or (email.split("@")[0] if email else "Prospect"),
        "email": email or "",
        "address": address
    }
    try:
        data = _post(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/prospects", payload)
        return str(data.get("id") or data.get("prospectid") or data.get("data", {}).get("id"))
    except Exception as e:
        # Si le nom est déjà pris → on récupère l’ID du prospect existant par nom
        msg = str(e)
        if "name has already been taken" in msg or "name has already been taken".replace(" ", "") in msg.replace(" ", ""):
            pid = _find_prospect_by_name(payload["name"])
            if pid:
                return pid
        raise

# ---------- Sélection du destinataire (client/prospect) ----------

def ensure_recipient(name: str, email: str, address_json: Dict[str, Any] | None) -> Tuple[Optional[str], Optional[str]]:
    # 1) client forcé via variable d'env
    if settings.EVOLIZ_DEFAULT_CLIENT_ID:
        return (str(settings.EVOLIZ_DEFAULT_CLIENT_ID), None)

    # 2) client existant par email
    cid = _find_client_by_email(email)
    if cid:
        return (cid, None)

    # 3) prospect existant par email
    pid = _find_prospect_by_email(email)
    if pid:
        return (None, pid)

    # 4) prospect existant par nom
    pid = _find_prospect_by_name(name)
    if pid:
        return (None, pid)

    # 5) sinon: création de prospect
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
    Crée un devis Evoliz :
      - documentdate (YYYY-MM-DD)
      - clientid OU prospectid (recherché/ créé de façon résiliente)
      - term.paymentid (1 = comptant)
      - items[{designation, quantity, unit_price, vat_rate}]
    """
    clientid, prospectid = ensure_recipient(recipient_name, recipient_email, recipient_address_json)

    payload = {
        "label": label or description or "Devis",
        "documentdate": dt.date.today().isoformat(),
        "status": "draft",
        "term": {"paymentid": 1},
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
