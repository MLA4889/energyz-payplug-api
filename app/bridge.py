# src/app/bridge.py
import os
import json
import requests
from .config import settings

BRIDGE_BASE_URL = getattr(settings, "BRIDGE_BASE_URL", "") or "https://api.bridgeapi.io"
TOKEN_URL  = f"{BRIDGE_BASE_URL}/v2/oauth/token"
LINKS_URL  = f"{BRIDGE_BASE_URL}/v2/payment-links"

def _headers(access_token: str | None = None) -> dict:
    h = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        # Version Bridge: utilisez celle que vous avez mise en ENV
        "Bridge-Version": getattr(settings, "BRIDGE_VERSION", "2025-01-15"),
    }
    if access_token:
        h["Authorization"] = f"Bearer {access_token}"
    return h

def _get_access_token() -> str:
    payload = {
        "grant_type": "client_credentials",
        "client_id": settings.BRIDGE_CLIENT_ID,       # sandbox_id_xxx... en sandbox
        "client_secret": settings.BRIDGE_CLIENT_SECRET,
    }
    resp = requests.post(TOKEN_URL, json=payload, headers=_headers(), timeout=25)
    if resp.status_code >= 400:
        raise Exception(f"Bridge token error: {resp.status_code} -> {resp.text}")
    data = resp.json()
    return data.get("access_token")

def create_bridge_payment_link(*, amount_cents: int, label: str, metadata: dict) -> str:
    """
    Crée un lien de paiement Bridge (virement instantané).
    amount_cents : montant en centimes
    label        : libellé visible pour le payeur
    metadata     : dict arbitraire (on y met item_id, acompte, etc.)
    """
    access_token = _get_access_token()

    # Corps attendu par Bridge
    body = {
        "amount": amount_cents,
        "currency": "EUR",
        "label": label,
        "creditor": {
            "name": getattr(settings, "BRIDGE_BENEFICIARY_NAME", "ENERGYZ"),
            "iban": getattr(settings, "BRIDGE_BENEFICIARY_IBAN", "").replace(" ", ""),
        },
        # URLs de redirection
        "success_url": getattr(settings, "BRIDGE_SUCCESS_URL", "https://www.energyz.fr"),
        "cancel_url": getattr(settings, "BRIDGE_CANCEL_URL",  "https://www.energyz.fr"),
        # Vous pouvez aussi prévoir un webhook global via le dashboard Bridge,
        # sinon ajoutez "webhook_url": f"{settings.PUBLIC_BASE_URL}/bridge/webhook"
        "metadata": metadata or {},
    }

    resp = requests.post(LINKS_URL, json=body, headers=_headers(access_token), timeout=25)
    if resp.status_code >= 400:
        raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    data = resp.json()
    # Selon la spec Bridge, l’URL direct du parcours de paiement est généralement dans "hosted_payment_url" ou "url"
    return data.get("hosted_payment_url") or data.get("url") or ""
