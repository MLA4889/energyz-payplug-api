# app/bridge.py
import os
import requests

BRIDGE_BASE = "https://api.bridgeapi.io"
BRIDGE_VERSION = os.getenv("BRIDGE_VERSION", "2025-01-15")
BRIDGE_CLIENT_ID = os.getenv("BRIDGE_CLIENT_ID")
BRIDGE_CLIENT_SECRET = os.getenv("BRIDGE_CLIENT_SECRET")
BRIDGE_SUCCESS_URL = os.getenv("BRIDGE_SUCCESS_URL", "https://www.energyz.fr")
BRIDGE_CANCEL_URL = os.getenv("BRIDGE_CANCEL_URL", "https://www.energyz.fr")

def _headers():
    return {
        "Bridge-Version": BRIDGE_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Client-Id": BRIDGE_CLIENT_ID or "",
        "Client-Secret": BRIDGE_CLIENT_SECRET or "",
    }

def create_bridge_payment_link(amount_cents: int, label: str, metadata: dict) -> str:
    body = {
        "amount": int(amount_cents),
        "currency": "EUR",
        "label": label or "Acompte Energyz",
        "success_url": BRIDGE_SUCCESS_URL,
        "cancel_url": BRIDGE_CANCEL_URL,
        "metadata": metadata or {},
    }
    url = f"{BRIDGE_BASE}/v3/payment/payment-links"
    res = requests.post(url, headers=_headers(), json=body, timeout=20)
    if res.status_code not in (200, 201):
        raise Exception(f"Bridge create link failed: {res.status_code} -> {res.text}")
    data = res.json() or {}
    return data.get("url") or ""
