import json
import re
import requests
from .config import settings

# IBAN Energyz connus
ENERGYZ_MAR_IBAN    = "FR76 1695 8000 0130 5670 5696 366"
ENERGYZ_DIVERS_IBAN = "FR76 1695 8000 0100 0571 1982 492"

def _compact_iban(s: str) -> str:
    return re.sub(r"\s+", "", (s or ""))

def _mode() -> str:
    return (getattr(settings, "PAYPLUG_MODE", "live") or "live").lower()

def _get_env(name: str) -> str:
    return getattr(settings, name, "") or ""

def _safe_parse_mapping(raw: str):
    """
    Tente de parser un mapping IBAN->KEY dans tous les formats usuels:
    - JSON strict
    - dict python (ast.literal_eval)
    - 'IBAN=KEY,IBAN2=KEY2' ou avec ';'
    Retourne un dict {iban: key}
    """
    if not raw:
        return {}
    # a) JSON strict
    try:
        return json.loads(raw)
    except Exception:
        pass
    # b) dict python
    try:
        import ast
        v = ast.literal_eval(raw)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    # c) 'IBAN=KEY,IBAN2=KEY2'
    try:
        out = {}
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        return out
    except Exception:
        return {}

def _choose_api_key(iban: str) -> str:
    """
    Choix **robuste** de la clé PayPlug à partir de l'IBAN:
      1) Si IBAN === Energyz MAR → PAYPLUG_*_KEY_EZMAR
      2) Si IBAN === Energyz Divers → PAYPLUG_*_KEY_EZDIVERS
      3) Sinon, dernier recours: mapping libre PAYPLUG_KEYS_*_JSON (tolérant)
    """
    mode = _mode()
    iban_c = _compact_iban(iban)
    mar_c  = _compact_iban(ENERGYZ_MAR_IBAN)
    div_c  = _compact_iban(ENERGYZ_DIVERS_IBAN)

    if iban_c == mar_c:
        return _get_env("PAYPLUG_LIVE_KEY_EZMAR") if mode == "live" else _get_env("PAYPLUG_TEST_KEY_EZMAR")
    if iban_c == div_c:
        return _get_env("PAYPLUG_LIVE_KEY_EZDIVERS") if mode == "live" else _get_env("PAYPLUG_TEST_KEY_EZDIVERS")

    # Mapping libre (facultatif)
    raw = _get_env("PAYPLUG_KEYS_LIVE_JSON") if mode == "live" else _get_env("PAYPLUG_KEYS_TEST_JSON")
    mapping = _safe_parse_mapping(raw)
    for k, v in (mapping or {}).items():
        if _compact_iban(k) == iban_c and v:
            return v

    return ""  # rien trouvé

def cents_from_str(s: str) -> int:
    """
    Convertit '1 234,56'/'1234.56' en centimes (int).
    """
    if not s:
        return 0
    s = s.replace("\u202f", "").replace(" ", "").replace("€", "").strip()
    s = s.replace(",", ".")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return 0
    val = float(m.group(0))
    return int(round(val * 100))

def create_payment(*, api_key: str, amount_cents: int, email: str = "", address: str = "", client_name: str = "", metadata: dict | None = None) -> str:
    """
    Crée un paiement PayPlug et retourne l'URL d'encaissement hébergée.
    Utilise l'API HTTP PayPlug (Authorization: Bearer <key>).
    """
    if not api_key:
        raise ValueError("PayPlug API key manquante")

    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "billing": {},
        "customer": {},
        "metadata": metadata or {},
        "hosted_payment": {
            # Tu peux personnaliser ces URLs si besoin
            "return_url": "https://payplug.com",
            "cancel_url": "https://payplug.com"
        }
    }

    if email:
        payload["customer"]["email"] = email
    if client_name:
        payload["customer"]["first_name"] = client_name[:40]  # facultatif
    if address:
        payload["billing"]["address1"] = address[:100]
        payload["billing"]["country"] = "FR"  # ajuste si besoin

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Endpoint de création PayPlug
    # Doc: https://docs.payplug.com/api/payment
    r = requests.post("https://api.payplug.com/v1/payments", headers=headers, json=payload, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"PayPlug error {r.status_code}: {r.text}")

    data = r.json()
    # L'URL se trouve généralement dans hosted_payment.payment_url
    link = (data.get("hosted_payment") or {}).get("payment_url", "")
    if not link:
        # fallback pour compat
        link = data.get("payment_url", "") or data.get("url", "")
    if not link:
        raise RuntimeError(f"PayPlug response sans payment_url: {data}")
    return link
