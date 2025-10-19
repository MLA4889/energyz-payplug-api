import os
import re
import requests
import json

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
        # accepte avec ou sans espaces
        return mapping.get(iban) or mapping.get(iban_c)

    return None

# ---------- Préremplissage systématique ----------
def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s or "client"

def _split_name(fullname: str) -> tuple[str, str]:
    base = (fullname or "Client Energyz").strip()
    parts = base.split()
    first = (parts[0] if parts else "Client")[:64] or "Client"
    last  = ((parts[-1] if len(parts) > 1 else "Energyz")[:64]) or "Energyz"
    return first, last

def _valid_email(email: str) -> bool:
    if not email:
        return False
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None

def _safe_alias_email(client_name: str | None, item_id: str | int | None) -> str:
    # alias simple, RFC-valide, toujours accepté par PayPlug
    iid = str(item_id or "0")
    return f"paiement+{iid}@energyz.fr"

def create_payment(api_key: str,
                   amount_cents: int,
                   email: str | None,
                   address: str | None,      # non bloquant
                   client_name: str | None,
                   metadata: dict | None) -> str:
    """
    Crée un paiement PayPlug 'hébergé' (lien) en PRÉREMPLISSANT toujours Nom/Prénom/E-mail :
      - si email Monday absent/incorrect, alias stable: paiement+{item_id}@energyz.fr
      - le champ e-mail reste ÉDITABLE sur la page PayPlug (le payeur peut mettre son e-mail de reçu)
    Conserve la structure existante pour ne pas casser les intégrations.
    """
    if not api_key:
        raise RuntimeError("create_payment: api_key manquante")

    url = "https://api.payplug.com/v1/payments"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # URLs de retour/annulation
    base_url   = os.getenv("PUBLIC_BASE_URL", "https://www.energyz.fr")
    return_url = os.getenv("PAYPLUG_RETURN_URL", base_url)
    cancel_url = os.getenv("PAYPLUG_CANCEL_URL", base_url)

    # Nom/Prénom + e-mail alias si besoin
    first_name, last_name = _split_name(client_name or "")
    item_id = str((metadata or {}).get("item_id", "0"))

    # 1) email Monday si présent
    alias_email = (email or "").strip()
    # 2) si vide/invalide -> alias sûr
    if not _valid_email(alias_email):
        alias_email = _safe_alias_email(client_name, item_id)
    # 3) filet ultime
    if not _valid_email(alias_email):
        alias_email = "paiement@energyz.fr"

    # 🔔 Ajout d'une mention pour inciter à renseigner son e-mail de reçu
    base_desc = (metadata or {}).get("description") or f"Paiement acompte { (metadata or {}).get('acompte','?') } — {client_name or 'Client Energyz'}"
    hint = " • Merci de vérifier/indiquer votre e-mail pour recevoir le reçu."
    description = (base_desc + hint)[:255]

    payload = {
        "amount": int(amount_cents or 0),
        "currency": "EUR",
        "hosted_payment": {
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
        "metadata": metadata or {},
        "description": description,
        "customer": {
            "email": alias_email,       # pré-rempli mais EDITABLE côté PayPlug
            "first_name": first_name,
            "last_name": last_name,
        },
        # "billing": {"address1": (address or "")[:255], "country": "FR"}  # à activer si besoin
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    if resp.status_code >= 300:
        raise RuntimeError(f"PayPlug error {resp.status_code}: {resp.text}")

    data = resp.json()
    hp = (data or {}).get("hosted_payment", {})
    pay_url = hp.get("payment_url") or data.get("payment_url") or data.get("hosted_payment_url")
    if not pay_url:
        raise RuntimeError(f"PayPlug: URL de paiement introuvable dans la réponse: {data}")
    return pay_url
