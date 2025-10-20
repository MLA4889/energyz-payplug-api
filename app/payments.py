import requests
import json
import re
import logging
from .config import settings

logger = logging.getLogger("energyz")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", flags=re.IGNORECASE)


def _choose_api_key(iban: str) -> str:
    """Sélectionne la clé PayPlug selon l’IBAN et le mode (test/live)."""
    mode = (settings.PAYPLUG_MODE or "").lower()
    key_dict = json.loads(settings.PAYPLUG_KEYS_TEST_JSON if mode == "test" else settings.PAYPLUG_KEYS_LIVE_JSON)
    return key_dict.get((iban or "").strip())


def cents_from_str(amount_str: str) -> int:
    """Convertit un montant texte en centimes (ex: '1250.00' → 125000)."""
    try:
        if not amount_str:
            return 0
        cleaned = (
            str(amount_str)
            .replace("€", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .replace(",", ".")
        )
        return int(round(float(cleaned) * 100))
    except Exception:
        return 0


def _sanitize_email(raw: str | None) -> str:
    """Garde pour compat, même si on n'envoie plus 'customer'."""
    if not raw:
        return "client@energyz.fr"
    s = str(raw).strip()
    s = s.replace("mailto:", "").replace("<", " ").replace(">", " ")
    s = re.sub(r"[;,/|]", " ", s)
    m = _EMAIL_RE.search(s)
    if not m:
        return "client@energyz.fr"
    return m.group(0).lower()


def _sanitize_address_line(raw: str | None) -> str:
    if not raw:
        return "France"
    s = str(raw).strip()
    s = re.sub(r"[\r\n\t]+", " ", s)
    return s[:255] if len(s) > 255 else s


def _split_first_last(name: str | None) -> tuple[str, str]:
    if not name:
        return ("Client", "Energyz")
    parts = str(name).strip().split()
    if len(parts) == 1:
        return (parts[0][:50], "Energyz")
    return (parts[0][:50], " ".join(parts[1:])[:50])


def create_payment(api_key: str, amount_cents: int, email: str, address: str, client_name: str, metadata: dict) -> str:
    """
    Crée un lien de paiement PayPlug (HTTP) :
    - redirige vers https://www.energyz.fr après validation (et aussi en cas d’annulation)
    - notification_url envoyée à chaque paiement pour mettre à jour Monday via /payplug/webhook
    - n'envoie PAS 'customer' → PayPlug affichera la saisie prénom/nom/email.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # URL de notification : ENV prioritaire, sinon PUBLIC_BASE_URL + /payplug/webhook
    notif_url = getattr(settings, "NOTIFICATION_URL", None) or (
        settings.PUBLIC_BASE_URL.rstrip("/") + "/payplug/webhook"
    )

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "metadata": metadata or {},
        "hosted_payment": {
            "return_url": "https://www.energyz.fr",  # ← après paiement validé
            "cancel_url": "https://www.energyz.fr",  # ← si annulé
        },
        "notification_url": notif_url,               # ← PayPlug enverra ici l’event payé
        "description": (metadata or {}).get("description", "Paiement acompte Energyz"),
    }

    # ⚠️ On n’inclut PAS 'customer' pour forcer la saisie côté checkout.
    # Si un jour tu veux pré-remplir, dé-commente ce bloc :
    # email_clean = _sanitize_email(email)
    # address_clean = _sanitize_address_line(address)
    # first_name, last_name = _split_first_last(client_name)
    # payload["customer"] = {
    #     "email": email_clean,
    #     "first_name": first_name,
    #     "last_name": last_name,
    #     "address1": address_clean
    # }

    url = "https://api.payplug.com/v1/payments"
    logger.info(f"[PAYPLUG] POST {url} json={payload}")
    res = requests.post(url, headers=headers, json=payload)
    if res.status_code not in (200, 201):
        logger.error(f"[PAYPLUG] {res.status_code} → {res.text}")
        raise Exception(f"Erreur PayPlug : {res.status_code} → {res.text}")

    data = res.json()
    payment_url = data.get("hosted_payment", {}).get("payment_url")
    logger.info(f"[PAYPLUG] created payment_url={payment_url}")
    return payment_url
