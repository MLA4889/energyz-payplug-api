import logging
import requests
import uuid
from .config import settings

logger = logging.getLogger("energyz")

def _base_headers():
    # En-têtes communs pour TOUT appel Bridge PIS
    return {
        "Bridge-Version": settings.BRIDGE_VERSION.strip(),   # ex: 2025-01-15
        "Accept": "application/json",
        "Content-Type": "application/json",
        # Auth côté Payment Links = Client-Id (pas d'Authorization Bearer)
        "Client-Id": settings.BRIDGE_CLIENT_ID,
    }

def _clean_iban(iban: str | None) -> str | None:
    if not iban:
        return None
    return "".join(iban.split())

def _pick_user_from_metadata(md: dict) -> dict:
    """
    Payment Links requiert un 'user' :
      - soit {first_name + last_name} OU
      - soit {company_name}
    On essaie au mieux à partir des métadonnées Monday.
    """
    md = md or {}
    email = md.get("email") or md.get("client_email")
    first = md.get("first_name")
    last = md.get("last_name")
    company = md.get("company") or md.get("client_company") or md.get("name")

    user = {}
    if email:
        user["email"] = str(email)[:320]
    if first and last:
        user["first_name"] = str(first)[:80]
        user["last_name"] = str(last)[:80]
    else:
        # fallback côté pro: on passe par company_name
        user["company_name"] = (company or "Client Energyz")[:140]
    # Optionnel : rattacher ta référence externe (id Monday)
    if md.get("item_id"):
        user["external_reference"] = str(md["item_id"])[:140]
    return user

def _make_e2e_id(md: dict, amount_cents: int) -> str:
    """
    end_to_end_id (obligatoire côté Bridge pour la transaction)
    """
    md = md or {}
    base = f"EZY-{md.get('item_id') or 'UNK'}-{md.get('acompte') or md.get('step') or '1'}-{amount_cents}"
    # Garantir <= 35 chars (limites bancaires habituelles) en tronquant et ajoutant un suffixe court
    suf = uuid.uuid4().hex[:6].upper()
    e2e = (base.replace(" ", "-"))[:28] + "-" + suf
    return e2e

def create_bridge_payment_link(*, amount_cents: int, label: str, metadata: dict) -> str:
    """
    Crée un lien de paiement par virement (Payment Link) chez Bridge.
    Auth: Client-Id + Bridge-Version (PAS de token AIS).
    Doc/Collection officielles: POST /v3/payment/payment-links. 
    """
    url = settings.BRIDGE_BASE_URL.rstrip("/") + "/v3/payment/payment-links"

    amount_cents = int(amount_cents or 0)
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0 for Bridge payment link")

    # Prépare 'user'
    user = _pick_user_from_metadata(metadata)

    # IBAN bénéficiaire (fixe Energyz, nettoyage espaces)
    beneficiary_iban = _clean_iban(settings.BRIDGE_BENEFICIARY_IBAN)
    if not beneficiary_iban:
        raise ValueError("Missing BRIDGE_BENEFICIARY_IBAN")

    # Références
    client_ref = (metadata or {}).get("client_reference") or (metadata or {}).get("item_id") or "Energyz"
    end_to_end_id = (metadata or {}).get("end_to_end_id") or _make_e2e_id(metadata, amount_cents)

    # Corps conforme à la réf 2025 (user + transactions[])
    body = {
        "client_reference": str(client_ref)[:140],
        "user": user,
        "transactions": [
            {
                "amount": amount_cents,
                "currency": "EUR",
                "label": (label or "Acompte Energyz")[:140],
                "end_to_end_id": end_to_end_id,
                # Bénéficiaire dynamique (optionnel selon config, mais pratique si tu veux forcer ton IBAN ici)
                "beneficiary": {
                    # Tu peux utiliser l’un des champs: name / company_name / first_name+last_name
                    "company_name": settings.BRIDGE_BENEFICIARY_NAME[:140],
                    "iban": beneficiary_iban,
                },
            }
        ],
        # Callback côté front si tu veux un retour (pas un statut de paiement)
        "callback_url": (settings.BRIDGE_SUCCESS_URL or "").strip() or None,
        # Tu peux aussi gérer l'expiration ici si besoin: "expired_at": "2025-12-31T23:59:00Z"
        "metadata": metadata or {},
    }

    # Nettoyage des clés None
    if not body["callback_url"]:
        body.pop("callback_url", None)

    headers = _base_headers()

    # Log soft: on ne log pas toutes les données perso
    log_preview = {
        "client_reference": body["client_reference"],
        "amount": body["transactions"][0]["amount"],
        "label": body["transactions"][0]["label"],
        "end_to_end_id": body["transactions"][0]["end_to_end_id"],
    }
    logger.info(f"[BRIDGE] POST {url} headers={{Bridge-Version:{headers['Bridge-Version']}, Client-Id:***}} json={log_preview}")

    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        logger.error(f"[BRIDGE] create link failed: {resp.status_code} -> {resp.text}")
        # Message clair si quelqu’un remet un flux AIS par erreur
        if resp.status_code == 403 and "permission" in resp.text.lower():
            raise Exception(
                "Bridge create link forbidden (403). "
                "Vérifie que tu utilises bien l’auth Payment Links (header Client-Id) "
                "et NON le token AIS /aggregation/authorization/token."
            )
        raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    data = resp.json()
    link_url = data.get("url") or data.get("link")
    if not link_url:
        logger.error(f"[BRIDGE] missing url in response: {data}")
        raise Exception("Bridge create link failed: missing url")

    logger.info(f"[BRIDGE] link={link_url}")
    return link_url
