# app/bridge.py
import os
import requests

# ---------- Base URL ----------
# En sandbox : sandbox.bridgeapi.io
# En prod : api.bridgeapi.io
BRIDGE_MODE = os.getenv("BRIDGE_MODE", "sandbox").lower()
BRIDGE_BASE = "https://sandbox.bridgeapi.io" if BRIDGE_MODE == "sandbox" else "https://api.bridgeapi.io"

BRIDGE_VERSION = os.getenv("BRIDGE_VERSION", "2025-01-15")

BRIDGE_CLIENT_ID = os.getenv("BRIDGE_CLIENT_ID")
BRIDGE_CLIENT_SECRET = os.getenv("BRIDGE_CLIENT_SECRET")

BRIDGE_SUCCESS_URL = os.getenv("BRIDGE_SUCCESS_URL", "https://www.energyz.fr")
BRIDGE_CANCEL_URL = os.getenv("BRIDGE_CANCEL_URL", "https://www.energyz.fr")
BRIDGE_BENEFICIARY_NAME = os.getenv("BRIDGE_BENEFICIARY_NAME", "ENERGYZ")
BRIDGE_BENEFICIARY_IBAN = os.getenv("BRIDGE_BENEFICIARY_IBAN")

def _headers():
    return {
        "Bridge-Version": BRIDGE_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Client-Id": BRIDGE_CLIENT_ID or "",
        "Client-Secret": BRIDGE_CLIENT_SECRET or "",
    }

def _extract_url(data: dict) -> str:
    """Cherche l'URL du lien Bridge dans la réponse."""
    if not isinstance(data, dict):
        return ""
    for key in ("url", "redirect_url", "link", "payment_link", "payment_url"):
        if data.get(key):
            return data[key]
    if isinstance(data.get("data"), dict):
        return _extract_url(data["data"])
    return ""

def create_bridge_payment_link(amount_cents: int, label: str, metadata: dict) -> str:
    """
    Crée un lien de paiement bancaire Bridge (virement instantané)
    Compatible sandbox & production.
    """
    if not BRIDGE_CLIENT_ID or not BRIDGE_CLIENT_SECRET:
        raise Exception("Bridge credentials missing (CLIENT_ID/SECRET)")
    if not BRIDGE_BENEFICIARY_IBAN:
        raise Exception("Bridge beneficiary IBAN missing")

    # Montant en euros (Bridge Sandbox attend un float, pas centimes)
    amount_euros = round((amount_cents or 0) / 100.0, 2)

    body = {
        "label": label or "Acompte Energyz",
        "amount": amount_euros,
        "currency": "EUR",
        "beneficiary": {
            "type": "iban",
            "name": BRIDGE_BENEFICIARY_NAME or "ENERGYZ",
            "iban": BRIDGE_BENEFICIARY_IBAN
        },
        "success_url": BRIDGE_SUCCESS_URL,
        "cancel_url": BRIDGE_CANCEL_URL
    }

    url = f"{BRIDGE_BASE}/v2/payment-links"
    res = requests.post(url, headers=_headers(), json=body, timeout=25)

    if res.status_code not in (200, 201):
        raise Exception(f"Bridge create link failed: {res.status_code} -> {res.text}")

    data = res.json() or {}
    link = _extract_url(data)
    if not link:
        raise Exception(f"Bridge link not found in response: {data}")

    return link
