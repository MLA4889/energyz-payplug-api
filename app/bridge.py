# src/app/bridge.py
import requests
from .config import settings

# Base URL Bridge
BRIDGE_BASE_URL = getattr(settings, "BRIDGE_BASE_URL", "") or "https://api.bridgeapi.io"
TOKEN_URL = f"{BRIDGE_BASE_URL}/v2/oauth/token"
LINKS_URL = f"{BRIDGE_BASE_URL}/v2/payment-links"


def _headers(access_token: str | None = None) -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Bridge-Version": getattr(settings, "BRIDGE_VERSION", "2025-01-15"),
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _get_access_token() -> str:
    client_id = getattr(settings, "BRIDGE_CLIENT_ID", None)
    client_secret = getattr(settings, "BRIDGE_CLIENT_SECRET", None)

    if not client_id or not client_secret:
        raise Exception("❌ Bridge credentials missing: set BRIDGE_CLIENT_ID and BRIDGE_CLIENT_SECRET in Render ENV")

    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }

    resp = requests.post(TOKEN_URL, json=payload, headers=_headers(), timeout=25)
    if resp.status_code >= 400:
        raise Exception(f"Bridge token error: {resp.status_code} -> {resp.text}")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise Exception(f"Bridge token missing in response: {data}")

    return access_token


def create_bridge_payment_link(*, amount_cents: int, label: str, metadata: dict) -> str:
    """
    Crée un lien de paiement Bridge (virement instantané).
    amount_cents : montant en centimes
    label        : libellé visible pour le payeur
    metadata     : dict arbitraire (on y met item_id, acompte, etc.)
    """
    access_token = _get_access_token()

    body = {
        "amount": amount_cents,
        "currency": "EUR",
        "label": label,
        "creditor": {
            "name": getattr(settings, "BRIDGE_BENEFICIARY_NAME", "ENERGYZ"),
            "iban": (getattr(settings, "BRIDGE_BENEFICIARY_IBAN", "") or "").replace(" ", ""),
        },
        "success_url": getattr(settings, "BRIDGE_SUCCESS_URL", "https://www.energyz.fr"),
        "cancel_url": getattr(settings, "BRIDGE_CANCEL_URL", "https://www.energyz.fr"),
        "metadata": metadata or {},
    }

    resp = requests.post(LINKS_URL, json=body, headers=_headers(access_token), timeout=25)
    if resp.status_code >= 400:
        raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    data = resp.json()
    # L'URL directe de paiement est souvent "hosted_payment_url" ou "url"
    return data.get("hosted_payment_url") or data.get("url") or ""
