# app/bridge.py
import os
import requests

BRIDGE_BASE = "https://api.bridgeapi.io"
BRIDGE_VERSION = os.getenv("BRIDGE_VERSION", "2025-01-15")

BRIDGE_CLIENT_ID = os.getenv("BRIDGE_CLIENT_ID")
BRIDGE_CLIENT_SECRET = os.getenv("BRIDGE_CLIENT_SECRET")

BRIDGE_SUCCESS_URL = os.getenv("BRIDGE_SUCCESS_URL", "https://www.energyz.fr")
BRIDGE_CANCEL_URL = os.getenv("BRIDGE_CANCEL_URL", "https://www.energyz.fr")

# Bénéficiaire (ton compte de réception)
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

def create_bridge_payment_link(amount_cents: int, label: str, metadata: dict) -> str:
    """
    Crée un 'payment link' Bridge et renvoie l'URL.
    - amount_cents : montant en centimes
    - label        : description affichée chez le payeur
    - metadata     : dict arbitraire renvoyé dans le webhook
    """
    if not BRIDGE_CLIENT_ID or not BRIDGE_CLIENT_SECRET:
        raise Exception("Bridge credentials missing (BRIDGE_CLIENT_ID/BRIDGE_CLIENT_SECRET)")

    if not BRIDGE_BENEFICIARY_IBAN:
        raise Exception("Bridge beneficiary IBAN missing (BRIDGE_BENEFICIARY_IBAN)")

    # Bridge attend un objet 'amount' (value en centimes) + 'beneficiary'
    body = {
        "label": label or "Acompte Energyz",
        "amount": {
            "value": int(amount_cents),   # en centimes
            "currency": "EUR"
        },
        "beneficiary": {
            "name": BRIDGE_BENEFICIARY_NAME or "ENERGYZ",
            "iban": BRIDGE_BENEFICIARY_IBAN
        },
        "success_url": BRIDGE_SUCCESS_URL,
        "cancel_url": BRIDGE_CANCEL_URL,
        "metadata": metadata or {},
    }

    url = f"{BRIDGE_BASE}/v3/payment/payment-links"
    res = requests.post(url, headers=_headers(), json=body, timeout=25)

    # Log clair si Bridge change le schéma
    if res.status_code not in (200, 201):
        raise Exception(f"Bridge create link failed: {res.status_code} -> {res.text}")

    data = res.json() or {}
    # certaines versions renvoient 'url', d'autres 'link'/'redirect_url'
    return data.get("url") or data.get("link") or data.get("redirect_url") or ""
