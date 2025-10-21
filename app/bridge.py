# src/app/bridge.py
import requests
from .config import settings

def _resolve_base_url() -> str:
    # Si BRIDGE_BASE_URL est présent dans l'ENV, on le respecte
    base = (getattr(settings, "BRIDGE_BASE_URL", "") or "").strip()
    if base:
        return base.rstrip("/")

    # Sinon on déduit automatiquement depuis le client_id
    cid = (getattr(settings, "BRIDGE_CLIENT_ID", "") or "").strip()
    if cid.startswith("sandbox_"):
        return "https://sandbox.bridgeapi.io"
    return "https://api.bridgeapi.io"


def _headers(access_token: str | None = None, content_type: str = "application/json") -> dict:
    h = {
        "Accept": "application/json",
        "Bridge-Version": getattr(settings, "BRIDGE_VERSION", "2025-01-15"),
    }
    if content_type:
        h["Content-Type"] = content_type
    if access_token:
        h["Authorization"] = f"Bearer {access_token}"
    return h


def _get_access_token() -> str:
    base_url = _resolve_base_url()
    token_url = f"{base_url}/v2/oauth/token"

    client_id = getattr(settings, "BRIDGE_CLIENT_ID", None)
    client_secret = getattr(settings, "BRIDGE_CLIENT_SECRET", None)

    if not client_id or not client_secret:
        raise Exception("Bridge credentials missing: set BRIDGE_CLIENT_ID and BRIDGE_CLIENT_SECRET in ENV")

    # Bridge attend du x-www-form-urlencoded
    form = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        # Optionnel: si nécessaire, ajouter 'scope': 'payment_links:write'
    }

    resp = requests.post(
        token_url,
        data=form,
        headers=_headers(content_type="application/x-www-form-urlencoded"),
        timeout=25,
    )
    if resp.status_code >= 400:
        raise Exception(f"Bridge token error: {resp.status_code} -> {resp.text}")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise Exception(f"Bridge token missing in response: {data}")

    return access_token


def create_bridge_payment_link(*, amount_cents: int, label: str, metadata: dict) -> str:
    base_url = _resolve_base_url()
    links_url = f"{base_url}/v2/payment-links"

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

    resp = requests.post(
        links_url,
        json=body,
        headers=_headers(access_token),
        timeout=25,
    )
    if resp.status_code >= 400:
        raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    data = resp.json()
    return data.get("hosted_payment_url") or data.get("url") or ""
