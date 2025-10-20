import requests
import json
import re
import logging
from .config import settings

logger = logging.getLogger("energyz")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", flags=re.IGNORECASE)


def _normalize_iban(s: str) -> str:
    """FR76 1695 8000 0100 0571 1982 492 -> FR7616958000010005711982492"""
    return (s or "").replace(" ", "").upper()


def _choose_api_key(iban: str) -> str:
    """
    Sélectionne la clé PayPlug selon IBAN + mode, avec normalisation
    et vérification du préfixe (sk_test_ / sk_live_).
    """
    mode = str(getattr(settings, "PAYPLUG_MODE", "test")).strip().lower()
    keys_raw = getattr(
        settings,
        "PAYPLUG_KEYS_TEST_JSON" if mode == "test" else "PAYPLUG_KEYS_LIVE_JSON",
        "{}",
    )

    try:
        mapping = json.loads(keys_raw) if isinstance(keys_raw, str) else dict(keys_raw)
    except Exception:
        mapping = {}

    # normalise les clés (IBANs) du mapping pour matcher même si tu as mis des espaces
    norm_map = {_normalize_iban(k): v for k, v in mapping.items() if v}

    norm_iban = _normalize_iban(iban)
    api_key = norm_map.get(norm_iban)

    logger.info(
        f"[KEY-SELECT] mode={mode} iban_in='{iban}' norm='{norm_iban}' "
        f"has_key={bool(api_key)} available_ibans={list(norm_map.keys())}"
    )

    if not api_key:
        raise Exception(
            f"Aucune clé PayPlug trouvée pour IBAN '{iban}' (norm='{norm_iban}') "
            f"en mode={mode}. Vérifie PAYPLUG_KEYS_{'TEST' if mode=='test' else 'LIVE'}_JSON."
        )

    # Cohérence du mode et du préfixe de clé
    if mode == "test" and not api_key.startswith("sk_test_"):
        raise Exception(
            "Clé incohérente: mode=test mais la clé ne commence pas par 'sk_test_'."
        )
    if mode != "test" and not api_key.startswith("sk_live_"):
        raise Exception(
            "Clé incohérente: mode=live mais la clé ne commence pas par 'sk_live_'."
        )

    return api_key


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


# (compat si tu veux repasser un jour en pré-rempli)
def _sanitize_email(raw: str | None) -> str:
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
    - envoie notification_url à chaque paiement (webhook Monday)
    - n'envoie PAS 'customer' pour forcer la saisie prénom/nom/email sur la page PayPlug.
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
            "cancel_url": "https://www.energyz.fr",  # ← si paiement annulé
        },
        "notification_url": notif_url,               # ← PayPlug enverra ici l’event payé
        "description": (metadata or {}).get("description", "Paiement acompte Energyz"),
    }

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
