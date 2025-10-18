import requests
from typing import Optional
from .config import settings

SESSION = {"token": None}

def _login() -> str:
    url = f"{settings.EVOLIZ_BASE_URL}/api/login"
    r = requests.post(url, json={
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY
    }, headers={"Content-Type": "application/json"})
    if not r.ok:
        raise Exception(f"Evoliz login error: {r.status_code} {r.text}")
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise Exception(f"Evoliz login: token missing in response: {data}")
    SESSION["token"] = token
    return token

def _auth_header() -> dict:
    if not SESSION["token"]:
        _login()
    return {"Authorization": f"Bearer {SESSION['token']}", "Content-Type": "application/json"}

def create_quote(label: str, description: str, unit_price_ht: float, vat_rate: float, quantity: float = 1.0) -> dict:
    """
    Crée un devis (draft) avec 1 ligne simple.
    Endpoint: POST /api/v1/companies/{companyid}/quotes
    Champs: label, lines[ {designation, quantity, unit_price, vat_rate} ]
    """
    url = f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes"
    payload = {
        "label": label or description or "Devis",
        "status": "draft",
        "lines": [
            {
                "designation": description or label or "Prestation",
                "quantity": quantity,
                "unit_price": round(float(unit_price_ht), 2),
                "vat_rate": round(float(vat_rate), 2)
            }
        ]
    }
    # tentative 1
    r = requests.post(url, headers=_auth_header(), json=payload)
    if r.status_code == 401:  # token expiré => relogin
        _login()
        r = requests.post(url, headers=_auth_header(), json=payload)
    if not r.ok:
        raise Exception(f"Evoliz quote error: {r.status_code} {r.text}")
    data = r.json()
    return data

def extract_public_link(quote_response: dict) -> Optional[str]:
    """
    Selon les versions, l’URL publique peut se trouver sous différents champs.
    On essaie plusieurs clés connues. Si aucune, on renvoie None.
    """
    for key in ["public_link", "public_url", "portal_url", "share_link", "url", "download_url", "pdf_url"]:
        v = quote_response.get(key)
        if v:
            return v
    # parfois l’URL est dans data, quote, links, etc.
    nested = (quote_response.get("data") or quote_response.get("quote") or {})
    for key in ["public_link", "public_url", "portal_url", "share_link", "url"]:
        v = nested.get(key)
        if v:
            return v
    return None
