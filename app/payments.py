import os
import re
import requests

# IBAN “connus” côté Energyz
ENERGYZ_MAR_IBAN    = "FR76 1695 8000 0130 5670 5696 366"
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
        import json
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
    # 1) clé forcée (si tu veux bypasser toutes les règles)
    forced_key = os.getenv("FORCED_PAYPLUG_KEY")
    if forced_key:
        return forced_key.strip()

    mode = _mode()
    iban_c = _compact_iban(iban)

    # 2) cas “connus” Energyz (plus simples)
    if iban_c == _compact_iban(ENERGYZ_MAR_IBAN):
        if mode == "live":
            return os.getenv("PAYPLUG_LIVE_KEY_EZMAR")
        return os.getenv("PAYPLUG_TEST_KEY_EZMAR")
    if iban_c == _compact_iban(ENERGYZ_DIVERS_IBAN):
        if mode == "live":
            return os.getenv("PAYPLUG_LIVE_KEY_EZDIVERS")
        return os.getenv("PAYPLUG_TEST_KEY_EZDIVERS")

    # 3) mapping JSON libre (clé = IBAN compact)
    if mode == "live":
        mapping = _load_json_env("PAYPLUG_KEYS_LIVE_JSON")
    else:
        mapping = _load_json_env("PAYPLUG_KEYS_TEST_JSON")

    if mapping:
        # accepte aussi des clés avec espaces
        key = mapping.get(iban) or mapping.get(iban_c)
        if key:
            return key

    return None

def _valid_email(email: str) -> bool:
    if not email:
        return False
    # check très simple, suffisant ici
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None


def create_payment(api_key: str,
                   amount_cents: int,
                   email: str | None,
                   address: str | None,
                   client_name: str | None,
                   metadata: dict | None) -> str:
    """
    Crée un paiement PayPlug (lien hébergé).
    - NE PAS ENVOYER `billing` (l’API renvoie "This field is unknown." dans ton cas)
    - N’ENVOYER `customer` QUE SI l’email est valide
    """
    if not api_key:
        raise RuntimeError("create_payment: api_key manquante")

    url = "https://api.payplug.com/v1/payments"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "payment_method": "link",
        "metadata": metadata or {},
    }

    # Email uniquement s'il est valide
    if _valid_email(email):
        payload["customer"] = {
            "email": email.strip(),
        }
        # on peut mettre un first_name si tu veux, mais pas obligatoire
        if client_name:
            payload["customer"]["first_name"] = str(client_name)[:100]

    # IMPORTANT : ne pas envoyer "billing" (ton log montre que cet endpoint ne le supporte pas)
    # if address:
    #     payload["billing"] = {"address1": address, "country": "FR"}

    import json
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=20)
    if resp.status_code >= 300:
        raise RuntimeError(f"PayPlug error {resp.status_code}: {resp.text}")

    data = resp.json()
    # l’URL se trouve en général dans hosted_payment.payment_url
    hp = (data or {}).get("hosted_payment", {})
    pay_url = hp.get("payment_url")
    if not pay_url:
        # fallback éventuels
        pay_url = data.get("payment_url") or data.get("hosted_payment_url")
    if not pay_url:
        raise RuntimeError(f"PayPlug: URL de paiement introuvable dans la réponse: {data}")

    return pay_url
