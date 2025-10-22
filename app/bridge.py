import logging
import requests
from .config import settings

logger = logging.getLogger("energyz")

__all__ = ["create_bridge_payment_link"]

def _headers():
    return {
        "Bridge-Version": settings.BRIDGE_VERSION.strip(),  # ex: 2025-01-15
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Client-Id": settings.BRIDGE_CLIENT_ID,
        "Client-Secret": settings.BRIDGE_CLIENT_SECRET,
    }

def _clean_iban(iban: str | None) -> str | None:
    if not iban:
        return None
    return "".join(iban.split())

def _beneficiaries_base_url():
    return settings.BRIDGE_BASE_URL.rstrip("/") + "/v3/payment/beneficiaries"

def _payment_links_url():
    return settings.BRIDGE_BASE_URL.rstrip("/") + "/v3/payment/payment-links"

def _get_beneficiary_id_by_iban(iban: str) -> str | None:
    """
    Essaie de retrouver un beneficiary existant par IBAN (si le tenant l'autorise).
    """
    url = _beneficiaries_base_url()
    headers = _headers()
    try:
        resp = requests.get(url, headers=headers, params={"iban": iban}, timeout=30)
        if resp.status_code != 200:
            logger.info(f"[BRIDGE] beneficiaries GET by IBAN -> {resp.status_code} {resp.text}")
            return None
        data = resp.json()
        # formats possibles: {"beneficiaries":[{id,...}]} ou liste directe
        lst = data.get("beneficiaries")
        if isinstance(lst, list) and lst:
            ben = lst[0]
            ben_id = ben.get("id") or ben.get("beneficiary_id")
            return str(ben_id) if ben_id else None
        return None
    except Exception as e:
        logger.info(f"[BRIDGE] beneficiaries GET failed ({e})")
        return None

def _create_beneficiary(name: str, iban: str) -> str | None:
    """
    Crée un beneficiary si nécessaire.
    """
    url = _beneficiaries_base_url()
    headers = _headers()
    body = {"name": name[:140], "iban": iban}
    logger.info(f"[BRIDGE] POST {url} (create beneficiary) json={{'name': body['name'], 'iban': '****{iban[-4:]}'}}")
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        logger.info(f"[BRIDGE] create beneficiary failed: {resp.status_code} -> {resp.text}")
        return None
    data = resp.json()
    ben_id = data.get("id") or data.get("beneficiary_id")
    return str(ben_id) if ben_id else None

def _ensure_beneficiary_id(name: str, iban: str) -> str | None:
    """
    Tente de récupérer un beneficiary_id existant, sinon de le créer.
    """
    ben_id = _get_beneficiary_id_by_iban(iban)
    if ben_id:
        logger.info(f"[BRIDGE] Found existing beneficiary_id={ben_id}")
        return ben_id
    ben_id = _create_beneficiary(name, iban)
    if ben_id:
        logger.info(f"[BRIDGE] Created beneficiary_id={ben_id}")
    return ben_id

def _try_payment_link_with_beneficiary_id(*, amount_cents: int, label: str, client_reference: str, metadata: dict, beneficiary_id: str):
    url = _payment_links_url()
    headers = _headers()
    body = {
        "label": label[:140],
        "amount": int(amount_cents),
        "currency": "EUR",
        "client_reference": str(client_reference)[:140],
        "beneficiary_id": str(beneficiary_id),
        "redirect_urls": {
            "success": (settings.BRIDGE_SUCCESS_URL or "https://www.energyz.fr").strip(),
            "fail": (settings.BRIDGE_CANCEL_URL or "https://www.energyz.fr").strip(),
        },
        "metadata": metadata or {},
    }
    log_preview = {k: body[k] for k in ("label", "amount", "client_reference")}
    log_preview["beneficiary_id"] = body["beneficiary_id"]
    logger.info(f"[BRIDGE] POST {url} (via beneficiary_id) headers={{Bridge-Version:{headers['Bridge-Version']}, Client-Id:***}} json={log_preview}")
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    return resp

def _try_payment_link_with_inline_beneficiary(*, amount_cents: int, label: str, client_reference: str, metadata: dict, beneficiary_name: str, beneficiary_iban: str):
    url = _payment_links_url()
    headers = _headers()
    body = {
        "label": label[:140],
        "amount": int(amount_cents),
        "currency": "EUR",
        "client_reference": str(client_reference)[:140],
        "beneficiary": {
            "name": beneficiary_name[:140],
            "iban": beneficiary_iban,
        },
        "redirect_urls": {
            "success": (settings.BRIDGE_SUCCESS_URL or "https://www.energyz.fr").strip(),
            "fail": (settings.BRIDGE_CANCEL_URL or "https://www.energyz.fr").strip(),
        },
        "metadata": metadata or {},
    }
    log_preview = {k: body[k] for k in ("label", "amount", "client_reference")}
    log_preview["beneficiary_name"] = body["beneficiary"]["name"]
    logger.info(f"[BRIDGE] POST {url} (via inline beneficiary) headers={{Bridge-Version:{headers['Bridge-Version']}, Client-Id:***}} json={log_preview}")
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    return resp

def create_bridge_payment_link(*, amount_cents: int, label: str, metadata: dict) -> str:
    """
    Crée un lien de paiement Bridge et renvoie l'URL.
    Stratégie:
      1) essayer avec 'beneficiary_id'
      2) si 400 "invalid body content", retenter avec 'beneficiary' inline
    """
    amount_cents = int(amount_cents or 0)
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0 for Bridge payment link")

    beneficiary_name = settings.BRIDGE_BENEFICIARY_NAME
    beneficiary_iban = _clean_iban(settings.BRIDGE_BENEFICIARY_IBAN)
    if not beneficiary_iban:
        raise ValueError("Missing BRIDGE_BENEFICIARY_IBAN")

    client_reference = (metadata or {}).get("client_reference") or (metadata or {}).get("item_id") or "Energyz"
    # 1) Tentative avec beneficiary_id (si le tenant le requiert, c’est la voie “propre”)
    ben_id = _ensure_beneficiary_id(beneficiary_name, beneficiary_iban)
    if ben_id:
        resp = _try_payment_link_with_beneficiary_id(
            amount_cents=amount_cents,
            label=label or "Acompte Energyz",
            client_reference=str(client_reference),
            metadata=metadata or {},
            beneficiary_id=ben_id,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            link_url = data.get("url") or data.get("link")
            if not link_url:
                logger.error(f"[BRIDGE] missing url in response: {data}")
                raise Exception("Bridge create link failed: missing url")
            logger.info(f"[BRIDGE] link={link_url} (via beneficiary_id)")
            return link_url

        # Si invalid body content → on retente en inline
        if resp.status_code == 400 and "invalid" in resp.text.lower():
            logger.info(f"[BRIDGE] beneficiary_id path returned 400; retrying with inline beneficiary. Body={resp.text}")
        else:
            # Autre erreur significative
            logger.error(f"[BRIDGE] create link (beneficiary_id) failed: {resp.status_code} -> {resp.text}")
            raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    # 2) Fallback: beneficiary inline
    resp = _try_payment_link_with_inline_beneficiary(
        amount_cents=amount_cents,
        label=label or "Acompte Energyz",
        client_reference=str(client_reference),
        metadata=metadata or {},
        beneficiary_name=beneficiary_name,
        beneficiary_iban=beneficiary_iban,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"[BRIDGE] create link (inline) failed: {resp.status_code} -> {resp.text}")
        raise Exception(f"Bridge create link failed: {resp.status_code} -> {resp.text}")

    data = resp.json()
    link_url = data.get("url") or data.get("link")
    if not link_url:
        logger.error(f"[BRIDGE] missing url in response: {data}")
        raise Exception("Bridge create link failed: missing url")

    logger.info(f"[BRIDGE] link={link_url} (via inline beneficiary)")
    return link_url
