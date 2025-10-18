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
    }, headers={"Content-Type": "application/json"}, timeout=25)
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
    return {"Authorization": f"Bearer {SESSION['token']}", "Content-Type": "application/json"}

def _request(method: str, path: str, payload: dict | None = None):
    url = f"{settings.EVOLIZ_BASE_URL}{path}"
    r = requests.request(method, url, headers=_headers(), json=payload or {}, timeout=25)
    if r.status_code == 401:
        _login()
        r = requests.request(method, url, headers=_headers(), json=payload or {}, timeout=25)
    if not r.ok:
        raise Exception(f"Evoliz API error {r.status_code}: {r.text}")
    return r.json()

def _get(path: str, params: dict | None = None):
    return _request("GET", path, params)

def _post(path: str, payload: dict | None = None):
    return _request("POST", path, payload)

# -------- Lookups (client/prospect) --------

def _find_by_email(endpoint: str, email: str) -> Optional[str]:
    if not email:
        return None
    try:
        data = _request("GET", f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/{endpoint}", {"search": email})
        items = data if isinstance(data, list) else data.get("data") or []
        for it in items:
            if str(it.get("email", "")).lower() == email.lower():
                return str(it.get("id") or it.get(f"{endpoint[:-1]}id"))
    except Exception:
        pass
    return None

def _find_prospect_by_name(name: str) -> Optional[str]:
    if not name:
        return None
    try:
        data = _request("GET", f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/prospects", {"search": name})
        items = data if isinstance(data, list) else data.get("data") or []
        for it in items:
            if str(it.get("name", "")).strip().lower() == name.strip().lower():
                return str(it.get("id") or it.get("prospectid"))
    except Exception:
        pass
    return None

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

def _create_prospect(name: str, email: str, address_json: Dict[str, Any] | None) -> Optional[str]:
    address = _normalize_address(address_json)
    payload = {"name": name or (email.split("@")[0] if email else "Prospect"), "email": email or "", "address": address}
    try:
        data = _post(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/prospects", payload)
        return str(data.get("id") or data.get("prospectid") or (data.get("data") or {}).get("id"))
    except Exception as e:
        if "name has already been taken" in str(e).lower():
            pid = _find_prospect_by_name(payload["name"])
            if pid:
                return pid
        raise

def ensure_recipient(name: str, email: str, address_json: Dict[str, Any] | None) -> Tuple[Optional[str], Optional[str]]:
    if settings.EVOLIZ_TENANT_SLUG:  # rien à voir mais on garde la priorité
        pass
    # client > prospect mail > prospect nom > create
    cid = _find_by_email("clients", email)
    if cid:
        return (cid, None)
    pid = _find_by_email("prospects", email)
    if pid:
        return (None, pid)
    pid = _find_prospect_by_name(name)
    if pid:
        return (None, pid)
    return (None, _create_prospect(name, email, address_json))

# -------- Quotes --------

def create_quote(
    label: str,
    description: str,
    unit_price_ht: float,
    vat_rate: float,
    recipient_name: str,
    recipient_email: str,
    recipient_address_json: Dict[str, Any] | None
) -> dict:
    # Désignation = description (pas le nom)
    designation = (description or "").strip() or (label or "Prestation")

    clientid, prospectid = ensure_recipient(recipient_name, recipient_email, recipient_address_json)
    payload = {
        "label": label or designation or "Devis",
        "documentdate": dt.date.today().isoformat(),
        "status": "draft",
        "term": {"paytermid": 1},
        "items": [{
            "designation": designation,
            "quantity": 1,
            "unit_price": round(float(unit_price_ht), 2),
            "vat_rate": round(float(vat_rate), 2)
        }]
    }
    if clientid: payload["clientid"] = clientid
    elif prospectid: payload["prospectid"] = prospectid
    return _post(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes", payload)

def get_quote(qid: str) -> dict:
    return _request("GET", f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{qid}")

def _try_create_share_link(qid: str) -> Optional[str]:
    # essaye quelques endpoints si dispos sur ton compte
    for path in [
        f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{qid}/share",
        f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{qid}/public-link",
    ]:
        try:
            data = _post(path, {})
            for k in ["public_link", "public_url", "share_link", "url"]:
                if isinstance(data, dict) and data.get(k): return str(data[k])
                nested = (data.get("data") if isinstance(data, dict) else None) or {}
                if nested.get(k): return str(nested[k])
        except Exception:
            continue
    return None

def extract_public_link(quote_response: dict) -> Optional[str]:
    for k in ["public_link", "public_url", "portal_url", "share_link", "url", "download_url", "pdf_url"]:
        v = quote_response.get(k)
        if v: return str(v)
    nested = (quote_response.get("data") or quote_response.get("quote") or {})
    for k in ["public_link", "public_url", "portal_url", "share_link", "url"]:
        v = nested.get(k)
        if v: return str(v)

    qid = str(quote_response.get("id") or nested.get("id") or "")
    if not qid: return None

    try:
        full = get_quote(qid)
        for k in ["public_link", "public_url", "portal_url", "share_link", "url", "download_url", "pdf_url"]:
            v = full.get(k) or (full.get("data") or {}).get(k)
            if v: return str(v)
    except Exception:
        pass

    return _try_create_share_link(qid)

def extract_identifiers(quote_response: dict) -> Tuple[Optional[str], Optional[str]]:
    data = quote_response.get("data") or quote_response
    qid = str(data.get("id") or data.get("quoteid") or "")
    number = str(data.get("number") or data.get("quotenumber") or "")
    return (qid or None, number or None)

def build_app_quote_url(qid: str | None) -> Optional[str]:
    if not qid: 
        return None
    # 1) URL tenant (préférée dans ton cas)
    if settings.EVOLIZ_TENANT_SLUG:
        return f"https://evoliz.com/{settings.EVOLIZ_TENANT_SLUG}/quote/display.php?QUOTEID={qid}"
    # 2) URL app générique si tu l’utilises
    if settings.EVOLIZ_APP_BASE_URL:
        return f"{settings.EVOLIZ_APP_BASE_URL.rstrip('/')}/quotes/{qid}"
    return None
