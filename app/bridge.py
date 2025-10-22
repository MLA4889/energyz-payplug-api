import logging
import requests
from .config import settings

logger = logging.getLogger("energyz")

__all__ = ["create_bridge_payment_link"]

def _base_headers():
    # Auth PIS pour payment-links: via headers
    return {
        "Bridge-Version": settings.BRIDGE_VERSION.strip(),   # ex: 2025-01-15
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Client-Id": settings.BRIDGE_CLIENT_ID,
        "Client-Secret": settings.BRIDGE_CLIENT_SECRET,
    }

def _clean_iban(iban: str | None) -> str | None:
    if not iban:
        return None
    return "".join(iban.split())

def create_bridge_payment_link(*, amount_cents: int, label: str, metadata: dict) -> str:
    """
    Crée un lien de paiement par virement via /v3/payment/payment-links.
    Schéma attendu (payload SIMPLE) :
      - label (str)
      - amount (int, cents)
      - currency (EUR)
      - beneficiary: { name, iban }
      - callback_url OU redirect_urls { success, fail }
      - metadata (facultatif)
    """
    url = settings.BRIDGE_BASE_URL.rstrip("/") + "/v3/payment/payment-links"

    amount_cents = int(amount_cents or 0)
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0 for Bridge payment link")

    beneficiary_iban = _clean_iban(settings.BRIDGE_BENEFICIARY_IBAN)
    if not beneficiary_iban:
        raise ValueError("Missing BRIDGE_BENEFICIARY_IBAN")

    # on privilégie redirect_urls (plus explicite pour l’utilisateur)
    body = {
        "label": (label or "Acompte Energyz")[:140],
        "amount": amount_cents,
        "currency": "EUR",
        "beneficiary": {
            # IMPORTANT: la clé attendue est 'name' (pas company_name)
            "name": settings.BRIDGE_BENEFICIARY_NAME[:140],
            "iban": beneficiary_iban,
        },
        "redirect_urls": {
            "success": (settings.BRIDGE_SUCCESS_URL or "").strip() or "https://www.energyz.fr",
            "fail": (settings.BRIDGE_CANCEL_URL or "").strip() or "https://www.energyz.fr",
        },
        "metadata": metadata or {},
    }

    headers = _base_headers()

    # log non-sensible pour vérifier ce qui part
    log_preview = {
        "label": body["label"],
        "amount": body["amount"],
        "beneficiary_name": body["beneficiary"]["name"],
        "has_redirect_urls": bool(body.get("redirect_urls")),
    }
    logger.info(f"[BRIDGE] POST {url} headers={{Bridge-Version:{headers['Bridge-Version']}, Client-Id:***, Client-Secret:***}} json={log_preview}")

    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        # renvoie le texte pour debug immédiat
        logger.error(f"[BRIDGE] create link failed: {resp.status_code} -> {resp.text}")
        raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    data = resp.json()
    link_url = data.get("url") or data.get("link")
    if not link_url:
        logger.error(f"[BRIDGE] missing url in response: {data}")
        raise Exception("Bridge create link failed: missing url")

    logger.info(f"[BRIDGE] link={link_url}")
    return link_url
