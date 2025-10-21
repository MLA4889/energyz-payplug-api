# src/app/bridge.py
import time
import requests
import logging
from typing import Optional

from .config import settings

logger = logging.getLogger("energyz.bridge")

# Configurable via ENV
BASE = getattr(settings, "BRIDGE_BASE_URL", "https://api.bridgeapi.io").rstrip("/")
TOKEN_PATH = "/v2/auth/token"
PAYMENT_LINKS_PATH = "/v2/payment-links"
BRIDGE_VERSION = getattr(settings, "BRIDGE_VERSION", "2021-06-30")

# Simple cache en mémoire du token (process-local)
_token_cache = {"access_token": None, "expires_at": 0}


def _get_access_token() -> str:
    """
    Récupère / cache le token Bridge.
    """
    now = int(time.time())
    token = _token_cache.get("access_token")
    if token and _token_cache.get("expires_at", 0) - 30 > now:
        return token

    url = f"{BASE}{TOKEN_PATH}"
    headers = {
        "Client-Id": getattr(settings, "BRIDGE_CLIENT_ID"),
        "Client-Secret": getattr(settings, "BRIDGE_CLIENT_SECRET"),
        "Bridge-Version": BRIDGE_VERSION,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials"}

    logger.info(f"[BRIDGE] POST {url} (get token)")
    resp = requests.post(url, headers=headers, data=data, timeout=15)

    if resp.status_code != 200:
        logger.error(f"[BRIDGE] token error: {resp.status_code} -> {resp.text}")
        raise Exception(f"Bridge token error: {resp.status_code} -> {resp.text}")

    j = resp.json()
    access_token = j.get("access_token")
    expires_in = int(j.get("expires_in", 300))
    if not access_token:
        raise Exception(f"Bridge token response missing access_token: {j}")

    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = int(time.time()) + expires_in

    logger.info("[BRIDGE] got access_token, expires_in=%s", expires_in)
    return access_token


def create_bridge_payment_link(
    amount_cents: int,
    label: str,
    metadata: dict,
    currency: str = "EUR",
    return_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> str:
    """
    Crée un lien de paiement Bridge et retourne l'URL publique.
    Lance Exception si échec.
    """
    access_token = _get_access_token()
    url = f"{BASE}{PAYMENT_LINKS_PATH}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Bridge-Version": BRIDGE_VERSION,
        "Content-Type": "application/json",
    }

    payload = {
        "amount": int(amount_cents),
        "currency": currency,
        "label": label or "Paiement Energyz",
        "metadata": metadata or {},
        # bridge specific fields (adaptables)
        "return_url": return_url or getattr(settings, "BRIDGE_SUCCESS_URL", ""),
        "cancel_url": cancel_url or getattr(settings, "BRIDGE_CANCEL_URL", ""),
        # beneficiary (optionnel) - si ton compte Bridge nécessite ces champs :
        "beneficiary": {
            "name": getattr(settings, "BRIDGE_BENEFICIARY_NAME", None),
            "iban": getattr(settings, "BRIDGE_BENEFICIARY_IBAN", None),
        },
    }

    # Nettoyage: retire les clés None
    payload["beneficiary"] = {k: v for k, v in payload["beneficiary"].items() if v}

    logger.info(f"[BRIDGE] POST {url} json={payload}")
    resp = requests.post(url, headers=headers, json=payload, timeout=20)

    if resp.status_code not in (200, 201):
        logger.error(f"[BRIDGE] create link failed: {resp.status_code} -> {resp.text}")
        # expose l'erreur lisible (pour logs)
        raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    data = resp.json()
    # selon réponse Bridge, la clé peut s'appeler 'url' ou 'link' ou 'payment_link'
    link = data.get("url") or data.get("link") or data.get("payment_link") or data.get("paymentUrl")
    if not link:
        # dump to help debugging
        raise Exception(f"Bridge create link response missing link field: {data}")

    logger.info(f"[BRIDGE] created link={link}")
    return link
