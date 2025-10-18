import datetime as dt
from typing import Optional, Tuple, Dict, Any

import requests

from .config import settings

# ----------------------------
# Auth Evoliz (token bearer)
# ----------------------------

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


def _post_ignore_errors(path: str, payload: dict | None = None) -> Optional[dict]:
    try:
        return _post(path, payload or {})
    except Exception:
        return None


# ----------------------------
# Lookups client / prospect
# ----------------------------

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
    city_obj = addr.get("city") or {}
    country = addr.get("country") or {}

    street = (street_obj.get("long_name") or addr.get("address") or "").strip() or "Adresse non précisée"
    town = (city_obj.get("long_name") or "").strip() or "N/A"
    iso2 = (country.get("short_name") or country.get("shortName") or "").strip() or "FR"
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


# ----------------------------
# Quotes
# ----------------------------

def create_quote(
    label: str,
    description: str,
    unit_price_ht: float,
    vat_rate: float,
    recipient_name: str,
    recipient_email: str,
    recipient_address_json: Dict[str, Any] | None,
) -> dict:
    """Crée un devis. La désignation est **la description** (pas le nom)."""
    designation = (description or "").strip() or (label or "Prestation")

    clientid, prospectid = ensure_recipient(recipient_name, recipient_email, recipient_address_json)
    payload = {
        "label": label or designation or "Devis",
        "documentdate": dt.date.today().isoformat(),
        "status": "draft",
        "term": {"paytermid": 1},
        "items": [
            {
                "designation": designation,
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


def get_quote(qid: str) -> dict:
    return _request("GET", f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{qid}")


def _extract_link_from_dict(d: dict | None) -> Optional[str]:
    if not isinstance(d, dict):
        return None
    for key in ["public_link", "public_url", "share_link", "portal_url", "url", "download_url", "pdf_url"]:
        if d.get(key):
            return str(d[key])
    nested = d.get("data") if isinstance(d, dict) else {}
    if isinstance(nested, dict):
        for key in ["public_link", "public_url", "share_link", "portal_url", "url", "download_url"]:
            if nested.get(key):
                return str(nested[key])
    return None


def get_or_create_public_link(quote_id: str, recipient_email: str | None = None) -> Optional[str]:
    """
    1) Cherche un lien public déjà présent.
    2) Tente de le générer via /share et /send (plusieurs variantes).
    3) Relit le devis pour tenter de récupérer le lien.
    """
    if not quote_id:
        return None

    try:
        current = get_quote(quote_id)
        link = _extract_link_from_dict(current)
        if link:
            return link
    except Exception:
        pass

    endpoints: list[tuple[str, dict | None]] = [
        (f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{quote_id}/share", {}),
        (f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{quote_id}/public-link", {}),
        (f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{quote_id}/send", {"method": "link"}),
        (f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{quote_id}/send", {"by": "link"}),
    ]
    if recipient_email:
        endpoints.append(
            (
                f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes/{quote_id}/send",
                {"method": "link", "recipients": [{"email": recipient_email}]},
            )
        )

    for path, payload in endpoints:
        resp = _post_ignore_errors(path, payload)
        link = _extract_link_from_dict(resp)
        if link:
            return link
        try:
            again = get_quote(quote_id)
            link2 = _extract_link_from_dict(again)
            if link2:
                return link2
        except Exception:
            pass

    return None


def extract_identifiers(quote_response: dict) -> Tuple[Optional[str], Optional[str]]:
    data = quote_response.get("data") or quote_response
    qid = str(data.get("id") or data.get("quoteid") or "")
    number = str(data.get("number") or data.get("quotenumber") or "")
    return (qid or None, number or None)


def build_app_quote_url(qid: str | None) -> Optional[str]:
    """Construit un deep-link (tenants) comme https://evoliz.com/<slug>/quote/display.php?QUOTEID=<id>"""
    if not qid:
        return None
    if settings.EVOLIZ_TENANT_SLUG:
        return f"https://evoliz.com/{settings.EVOLIZ_TENANT_SLUG}/quote/display.php?QUOTEID={qid}"
    if settings.EVOLIZ_APP_BASE_URL:
        return f"{settings.EVOLIZ_APP_BASE_URL.rstrip('/')}/quotes/{qid}"
    return None
