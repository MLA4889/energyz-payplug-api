import requests
from datetime import date
from .config import settings


def get_access_token():
    payload = {
        "public_key": settings.EVOLIZ_PUBLIC_KEY,
        "secret_key": settings.EVOLIZ_SECRET_KEY
    }
    r = requests.post(f"{settings.EVOLIZ_BASE_URL}/api/login", json=payload, timeout=30)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Evoliz: pas de access_token reçu.")
    return token


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_client_if_needed(token, client_data: dict):
    # Recherche client par nom
    r = requests.get(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients",
        headers=_auth_headers(token),
        params={"search": client_data["name"]},
        timeout=30,
    )
    r.raise_for_status()
    existing = r.json().get("data", [])
    if existing:
        return existing[0]["clientid"]

    payload = {
        "name": client_data["name"],
        "type": "Professionnel" if client_data.get("client_type") == "Professionnel" else "Particulier",
        "address": {
            "addr": client_data.get("address", ""),
            "postcode": client_data.get("postcode", ""),
            "town": client_data.get("city", ""),
            "iso2": "FR",
        }
    }
    if client_data.get("client_type") == "Professionnel" and client_data.get("vat_number"):
        payload["vat_number"] = client_data["vat_number"]

    r = requests.post(
        f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients",
        headers=_auth_headers(token),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["clientid"]


def _payload_lines(quote_data: dict) -> dict:
    vat_rate = float(quote_data.get("vat_rate", settings.DEFAULT_VAT_RATE))
    return {
        "lines": [
            {
                "designation": quote_data["description"],
                "unit_price": quote_data["amount_ht"],
                "quantity": 1,
                "vat_rate": vat_rate,          # <- taux de TVA
            }
        ],
        "currency": "EUR",
        "prices_include_vat": False
    }


def _payload_items_legacy(quote_data: dict) -> dict:
    """Repli si l'API réclame items/documentdate/term.paytermid."""
    vat_rate = float(quote_data.get("vat_rate", settings.DEFAULT_VAT_RATE))
    return {
        "documentdate": date.today().isoformat(),
        "term": {"paytermid": 1},              # 1 = à réception (classique)
        "items": [
            {
                "designation": quote_data["description"],
                "unit_price": quote_data["amount_ht"],
                "quantity": 1,
                "vat_rate": vat_rate,
            }
        ],
        "currency": "EUR",
        "prices_include_vat": False
    }


def create_quote(token, client_id, quote_data: dict):
    """
    Crée un devis Evoliz avec TVA. Préférence pour schéma 'lines'.
    En cas d'erreur attendue, retente en schéma 'items'.
    """
    url = f"{settings.EVOLIZ_BASE_URL}/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes"
    base = {"clientid": client_id}

    # 1) tentative 'lines'
    payload = {**base, **_payload_lines(quote_data)}
    r = requests.post(url, headers=_auth_headers(token), json=payload, timeout=30)
    if r.status_code < 400:
        return r.json()

    # 2) si message indique le schéma legacy -> on retente
    try:
        err = r.json()
    except Exception:
        err = {"raw": r.text}
    msg = str(err)
    needs_legacy = ("items" in msg) or ("documentdate" in msg) or ("term.paytermid" in msg)

    if needs_legacy:
        payload2 = {**base, **_payload_items_legacy(quote_data)}
        r2 = requests.post(url, headers=_auth_headers(token), json=payload2, timeout=30)
        if r2.status_code < 400:
            return r2.json()
        raise RuntimeError(f"Evoliz legacy error {r2.status_code}: {r2.text}")

    # sinon, on propage l'erreur
    raise RuntimeError(f"Evoliz error {r.status_code}: {r.text}")
