import requests
import datetime as dt
from typing import Optional, Tuple
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
        raise Exception(f"Evoliz login: token not found in response: {data}")
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

# ---------- Client/Prospect helpers ----------

def _find_client_by_email(email: str) -> Optional[str]:
    """Essaie de retrouver un client existant via email (si l’API le permet)."""
    try:
        data = _get(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients", params={"search": email})
        # on tente plusieurs formes de réponse
        items = data if isinstance(data, list) else data.get("data") or []
        for it in items:
            if str(it.get("email", "")).lower() == email.lower():
                return str(it.get("id") or it.get("clientid"))
    except Exception:
        pass
    return None

def _create_prospect(name: str, email: str, address1: str = "") -> Optional[str]:
    """Crée un prospect minimal (nom+email) et retourne son id."""
    payload = {
        "name": name or (email.split("@")[0] if email else "Prospect"),
        "email": email or "",
        "address1": address1 or ""
    }
    data = _post(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/prospects", payload)
    return str(data.get("id") or data.get("prospectid") or data.get("data", {}).get("id"))

def ensure_recipient(name: str, email: str, address1: str = "") -> Tuple[Optional[str], Optional[str]]:
    """
    Retourne (clientid, prospectid) — un seul des deux sera renseigné.
    Priorité :
      1) EVOLIZ_DEFAULT_CLIENT_ID si défini
      2) client existant par email
      3) création d’un prospect minimal
    """
    # 1) client par défaut (si fourni)
    if settings.EVOLIZ_DEFAULT_CLIENT_ID:
        return (str(settings.EVOLIZ_DEFAULT_CLIENT_ID), None)

    # 2) recherche d’un client existant
    if email:
        cid = _find_client_by_email(email)
        if cid:
            return (cid, None)

    # 3) création prospect
    pid = _create_prospect(name, email, address1)
    return (None, pid)

# ---------- Quote ----------

def create_quote(
    label: str,
    description: str,
    unit_price_ht: float,
    vat_rate: float,
    recipient_name: str,
    recipient_email: str,
    recipient_address: str = ""
) -> dict:
    """
    Crée un devis conforme aux exigences Evoliz:
      - documentdate (YYYY-MM-DD)
      - clientid OU prospectid
      - term.paymentid (1 = comptant / à adapter si besoin)
      - items: [{ designation, quantity, unit_price, vat_rate }]
    """
    clientid, prospectid = ensure_recipient(recipient_name, recipient_email, recipient_address)

    payload = {
        "label": label or description or "Devis",
        "documentdate": dt.date.today().isoformat(),
        "status": "draft",
        "term": {"paymentid": 1},  # 1 = comptant ; adapte si tu as une nomenclature différente
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

    data = _post(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes", payload)
    return data

def extract_public_link(quote_response: dict) -> Optional[str]:
    # essai de plusieurs clés possibles
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
