import os
import re
import requests
import json

# IBAN “connus” côté Energyz
ENERGYZ_MAR_IBAN = "FR76 1695 8000 0130 5670 5696 366"
ENERGYZ_DIVERS_IBAN = "FR76 1695 8000 0100 0571 1982 492"


def _compact_iban(iban: str) -> str:
    return (iban or "").replace(" ", "").upper()


def _mode() -> str:
    return (os.getenv("PAYPLUG_MODE") or "test").lower().strip()


def _load_json_env(name: str) -> dict:
    raw = os.getenv(name)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def cents_from_str(s: str) -> int:
    s = (s or "").replace(" ", "").replace("€", "").replace(",", ".")
    try:
        v = float(s)
    except Exception:
        v = 0.0
    return int(round(v * 100))


def _choose_api_key(iban: str) -> str | None:
    """
    Choix de la clé PayPlug en fonction de l’IBAN + ENV + FORCED_PAYPLUG_KEY éventuel.
    """
    forced_key = os.getenv("FORCED_PAYPLUG_KEY")
    if forced_key:
        return forced_key.strip()

    mode = _mode()
    iban_c = _compact_iban(iban)

    if iban_c == _compact_iban(ENERGYZ_MAR_IBAN):
        return os.getenv("PAYPLUG_LIVE_KEY_EZMAR") if mode == "live" else os.getenv("PAYPLUG_TEST_KEY_EZMAR")
    if iban_c == _compact_iban(ENERGYZ_DIVERS_IBAN):
        return os.getenv("PAYPLUG_LIVE_KEY_EZDIVERS") if mode == "live" else os.getenv("PAYPLUG_TEST_KEY_EZDIVERS")

    mapping = _load_json_env("PAYPLUG_KEYS_LIVE_JSON" if mode == "live" else "PAYPLUG_KEYS_TEST_JSON")
    if mapping:
        return mapping.get(iban) or mapping.get(iban_c)

    return None


def _valid_email(email: str) -> bool:
    if not email:
        return False
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None


def create_payment(
    api_key: str,
    amount_cents: int,
    email: str | None,
    address: str | None,      # non utilisé volontairement
    client_name: str | None,
    metadata: dict | None,
) -> str:
    """
    Crée un paiement PayPlug 'hébergé' (lien).
      - on utilise 'hosted_payment' (pas de 'payment_method')
      - pas de 'billing'
      - 'customer' uniquement si email valide
    """
    if not api_key:
        raise RuntimeError("create_payment: api_key manquante")

    url = "https://api.payplug.com/v1/payments"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # URLs de retour/annulation (facultatives, mais c’est propre d’en fournir)
    return_url = os.getenv("PAYPLUG_RETURN_URL", "https://www.energyz.fr/success")
    cancel_url = os.getenv("PAYPLUG_CANCEL_URL", "https://www.energyz.fr/cancel")

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        # pas de payment_method -> PayPlug génère une page de paiement hébergée
        "hosted_payment": {
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
        "metadata": metadata or {},
    }

    if _valid_email(email):
        payload["customer"] = {"email": email.strip()}
        if client_name:
            # Pas obligatoire, mais utile pour le ticket
            payload["customer"]["first_name"] = str(client_name)[:100]

    # NE PAS ENVOYER 'billing'
    # if address:
    #     payload["billing"] = {"address1": address, "country": "FR"}

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=20)
    if resp.status_code >= 300:
        raise RuntimeError(f"PayPlug error {resp.status_code}: {resp.text}")

    data = resp.json()
    hp = (data or {}).get("hosted_payment", {})
    pay_url = hp.get("payment_url") or data.get("payment_url") or data.get("hosted_payment_url")
    if not pay_url:
        raise RuntimeError(f"PayPlug: URL de paiement introuvable dans la réponse: {data}")

    return pay_url
 
