import requests
from .config import settings

def _base(url: str) -> str:
    # Évite les // et assure le bon host
    base = settings.EVOLIZ_BASE_URL.rstrip("/")
    return f"{base}{url}"

def _raise_for_evoliz(r: requests.Response):
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    if r.status_code >= 400:
        # Messages plus explicites en log
        msg = data.get("message") or data.get("error") or data
        raise RuntimeError(f"[Evoliz {r.status_code}] {msg}")

def get_access_token() -> str:
    payload = {
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY,
    }
    r = requests.post(_base("/api/login"), json=payload, timeout=getattr(settings, "EVOLIZ_TIMEOUT", 20))
    _raise_for_evoliz(r)
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Login Evoliz sans access_token (vérifie clés et droits API).")
    return token

def create_client_if_needed(token: str, client_data: dict) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    params = {"search": client_data["name"]}
    r = requests.get(
        _base(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients"),
        headers=headers, params=params, timeout=getattr(settings, "EVOLIZ_TIMEOUT", 20)
    )
    _raise_for_evoliz(r)
    existing = r.json().get("data", [])
    if existing:
        return existing[0]["clientid"]

    payload = {
        "name": client_data["name"],
        "type": "Professionnel",
        "address": {
            "addr": client_data.get("address", "") or "",
            "postcode": client_data.get("postcode", "") or "",
            "town": client_data.get("city", "") or "",
            "iso2": "FR"
        }
    }
    r = requests.post(
        _base(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients"),
        headers=headers, json=payload, timeout=getattr(settings, "EVOLIZ_TIMEOUT", 20)
    )
    _raise_for_evoliz(r)
    client_id = r.json().get("clientid")
    if not client_id:
        raise RuntimeError("Création client Evoliz OK mais pas de clientid dans la réponse.")
    return client_id

def create_quote(token: str, client_id: int, quote_data: dict) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "clientid": client_id,
        "lines": [
            {
                "designation": quote_data["description"],
                "unit_price": quote_data["amount_ht"],
                "quantity": 1
            }
        ],
        "currency": "EUR"
    }
    r = requests.post(
        _base(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes"),
        headers=headers, json=payload, timeout=getattr(settings, "EVOLIZ_TIMEOUT", 20)
    )
    _raise_for_evoliz(r)
    return r.json()
