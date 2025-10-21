import logging
import requests
from .config import settings

logger = logging.getLogger("energyz")


def _headers_auth():
    """En-têtes requis pour obtenir un token Bridge (v3)."""
    return {
        "Client-Id": settings.BRIDGE_CLIENT_ID,
        "Client-Secret": settings.BRIDGE_CLIENT_SECRET,
        "Bridge-Version": settings.BRIDGE_VERSION,
        "Content-Type": "application/json",
    }


def _headers_api(access_token: str):
    """En-têtes pour appeler les endpoints de paiement (v3)."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Bridge-Version": settings.BRIDGE_VERSION,
        "Content-Type": "application/json",
    }


def _get_access_token() -> str:
    """
    POST /v3/aggregation/authorization/token → access_token
    """
    url = settings.BRIDGE_BASE_URL.rstrip("/") + "/v3/aggregation/authorization/token"
    logger.info(f"[BRIDGE] POST {url} (get token)")
    resp = requests.post(url, headers=_headers_auth(), json={})
    if resp.status_code != 200:
        logger.error(f"[BRIDGE] token error: {resp.status_code} -> {resp.text}")
        raise Exception(f"Bridge token error: {resp.status_code} -> {resp.text}")

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise Exception("Bridge token error: no access_token in response")
    return token


def create_bridge_payment_link(*, amount_cents: int, label: str, metadata: dict) -> str:
    """
    Crée un lien de virement Bridge (PIS) et retourne l'URL.
    N’impacte pas PayPlug.
    """
    access_token = _get_access_token()

    url = settings.BRIDGE_BASE_URL.rstrip("/") + "/v3/payment/payment-links"
    body = {
        "label": label or "Acompte Energyz",
        "amount": int(amount_cents),           # en centimes
        "currency": "EUR",
        "beneficiary": {
            "name": settings.BRIDGE_BENEFICIARY_NAME,
            "iban": settings.BRIDGE_BENEFICIARY_IBAN,
        },
        "redirect_urls": {
            "success": settings.BRIDGE_SUCCESS_URL,
            "fail": settings.BRIDGE_CANCEL_URL,
        },
        "metadata": metadata or {},
    }

    logger.info(f"[BRIDGE] POST {url} json={body}")
    resp = requests.post(url, headers=_headers_api(access_token), json=body)
    if resp.status_code not in (200, 201):
        logger.error(f"[BRIDGE] create link failed: {resp.status_code} -> {resp.text}")
        raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    data = resp.json()
    link_url = data.get("url")
    if not link_url:
        logger.error(f"[BRIDGE] no url in response: {data}")
        raise Exception("Bridge create link failed: missing url")

    logger.info(f"[BRIDGE] link={link_url}")
    return link_url
