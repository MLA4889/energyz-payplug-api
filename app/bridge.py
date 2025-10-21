import logging
import requests
from .config import settings

logger = logging.getLogger("energyz")

def _base_headers():
    # En-têtes communs à TOUS les appels Bridge (obligatoire: Bridge-Version)
    return {
        "Bridge-Version": settings.BRIDGE_VERSION.strip(),  # ex: "2025-01-15"
        "Accept": "application/json",
    }

def _headers_auth():
    # Auth "client" pour récupérer un access_token
    h = _base_headers()
    h.update({
        "Client-Id": settings.BRIDGE_CLIENT_ID,
        "Client-Secret": settings.BRIDGE_CLIENT_SECRET,
        "Content-Type": "application/json",
    })
    return h

def _headers_api(access_token: str):
    # Auth "Bearer" pour les endpoints applicatifs
    h = _base_headers()
    h.update({
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    })
    return h

def _get_access_token() -> str:
    url = settings.BRIDGE_BASE_URL.rstrip("/") + "/v3/aggregation/authorization/token"
    logger.info(f"[BRIDGE] POST {url} (get token) with Bridge-Version={settings.BRIDGE_VERSION!r}")
    resp = requests.post(url, headers=_headers_auth(), json={})
    # Log de debug utile si ton Render masque/altère des en-têtes
    if resp.status_code != 200:
        logger.error(f"[BRIDGE] token error: {resp.status_code} -> {resp.text}")
        # Erreur typique si Bridge-Version absent/mauvais
        raise Exception(f"Bridge token error: {resp.status_code} -> {resp.text}")

    data = resp.json()
    token = data.get("access_token")
    if not token:
        logger.error(f"[BRIDGE] token payload sans access_token: {data}")
        raise Exception("Bridge token error: no access_token in response")
    return token

def _clean_iban(iban: str | None) -> str | None:
    if not iban:
        return None
    # Bridge accepte l'IBAN sans espaces (évite les 400 bêtes)
    return "".join(iban.split())

def create_bridge_payment_link(*, amount_cents: int, label: str, metadata: dict,
                               success_url: str | None = None,
                               cancel_url: str | None = None) -> str:
    """
    Crée un lien de paiement virement (Open Banking) chez Bridge.
    Compatible doc 2025 : usage de `callback_url`. On garde aussi un fallback
    si tu veux encore passer des URLs séparées.
    """
    access_token = _get_access_token()

    url = settings.BRIDGE_BASE_URL.rstrip("/") + "/v3/payment/payment-links"

    # Sécurise les champs
    amount_cents = int(amount_cents or 0)
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0 for Bridge payment link")

    beneficiary_iban = _clean_iban(settings.BRIDGE_BENEFICIARY_IBAN)
    if not beneficiary_iban:
        raise ValueError("Missing BRIDGE_BENEFICIARY_IBAN")

    # Doc "Create your first payment link": on privilégie `callback_url`
    # https://docs.bridgeapi.io/docs/first-payment-link-from-the-api
    callback_url = (success_url or settings.BRIDGE_SUCCESS_URL or "").strip()

    body = {
        "label": (label or "Acompte Energyz")[:140],
        "amount": amount_cents,
        "currency": "EUR",
        # Côté encaissement Energyz : on fixe le bénéficiaire
        "beneficiary": {
            "name": settings.BRIDGE_BENEFICIARY_NAME,
            "iban": beneficiary_iban,
        },
        # Référence croisée utile pour retrouver côté Monday
        "client_reference": (metadata or {}).get("client_reference") or (metadata or {}).get("item_id"),
        # Métadonnées (limites: 5 clés / 50c key / 100c value)
        "metadata": metadata or {},
    }

    # Callback moderne (docs 2025)
    if callback_url:
        body["callback_url"] = callback_url

    # Compat descendante si tu préfères séparer succès / échec
    # (certains extraits plus anciens montrent encore redirect_urls)
    if (cancel_url or settings.BRIDGE_CANCEL_URL):
        body["redirect_urls"] = {
            "success": callback_url or settings.BRIDGE_SUCCESS_URL,
            "fail": (cancel_url or settings.BRIDGE_CANCEL_URL),
        }

    logger.info(f"[BRIDGE] POST {url} json={{{'label': body['label'], 'amount': body['amount'], 'currency': body['currency'], 'client_reference': body.get('client_reference')}}}")
    resp = requests.post(url, headers=_headers_api(access_token), json=body)

    if resp.status_code not in (200, 201):
        # Trace lisible sur Render
        logger.error(f"[BRIDGE] create link failed: {resp.status_code} -> {resp.text}")
        # Message clair si jamais l'en-tête version a été ignoré côté infra
        if "missing_version_header" in resp.text or "invalid" in resp.text.lower():
            raise Exception(
                "Bridge create link failed (version header issue). "
                "Vérifie que l'en-tête 'Bridge-Version: 2025-01-15' est bien transmis jusqu'à Bridge "
                "et que BRIDGE_VERSION=2025-01-15 est présent dans l'env Render."
            )
        raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    data = resp.json()
    link_url = data.get("url")
    if not link_url:
        logger.error(f"[BRIDGE] no url in response: {data}")
        raise Exception("Bridge create link failed: missing url")

    logger.info(f"[BRIDGE] link={link_url}")
    return link_url
