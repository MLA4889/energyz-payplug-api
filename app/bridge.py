# app/bridge.py
import os
import requests

BRIDGE_BASE = "https://api.bridgeapi.io"
BRIDGE_VERSION = os.getenv("BRIDGE_VERSION", "2025-01-15")

BRIDGE_CLIENT_ID = os.getenv("BRIDGE_CLIENT_ID")
BRIDGE_CLIENT_SECRET = os.getenv("BRIDGE_CLIENT_SECRET")

BRIDGE_SUCCESS_URL = os.getenv("BRIDGE_SUCCESS_URL", "https://www.energyz.fr")
BRIDGE_CANCEL_URL = os.getenv("BRIDGE_CANCEL_URL", "https://www.energyz.fr")

BRIDGE_BENEFICIARY_NAME = os.getenv("BRIDGE_BENEFICIARY_NAME", "ENERGYZ")
BRIDGE_BENEFICIARY_IBAN = os.getenv("BRIDGE_BENEFICIARY_IBAN")

def _headers():
    return {
        "Bridge-Version": BRIDGE_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Client-Id": BRIDGE_CLIENT_ID or "",
        "Client-Secret": BRIDGE_CLIENT_SECRET or "",
    }

def _extract_url(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    # différentes versions/retours possibles selon Bridge
    for k in ("url", "link", "redirect_url", "payment_link", "payment_url"):
        if data.get(k):
            return data[k]
    # parfois imbriqué
    for k in ("data", "result"):
        if isinstance(data.get(k), dict):
            u = _extract_url(data[k])
            if u:
                return u
    return ""

def create_bridge_payment_link(amount_cents: int, label: str, metadata: dict) -> str:
    """
    Essaie automatiquement les schémas Bridge connus et renvoie l'URL du payment-link.
    - Ne plante pas PayPlug: l'exception est remontée au caller qui la catch et log.
    """
    if not BRIDGE_CLIENT_ID or not BRIDGE_CLIENT_SECRET:
        raise Exception("Bridge credentials missing (BRIDGE_CLIENT_ID/BRIDGE_CLIENT_SECRET)")
    if not BRIDGE_BENEFICIARY_IBAN:
        raise Exception("Bridge beneficiary IBAN missing (BRIDGE_BENEFICIARY_IBAN)")

    # 1) v2/payment-links : amount en EUROS (float) + beneficiary avec "type"
    body_v2 = {
        "label": label or "Acompte Energyz",
        "amount": round((amount_cents or 0) / 100.0, 2),  # euros
        "currency": "EUR",
        "beneficiary": {
            "type": "iban",
            "name": BRIDGE_BENEFICIARY_NAME or "ENERGYZ",
            "iban": BRIDGE_BENEFICIARY_IBAN
        },
        "success_url": BRIDGE_SUCCESS_URL,
        "cancel_url": BRIDGE_CANCEL_URL,
        "metadata": metadata or {},
    }
    url_v2 = f"{BRIDGE_BASE}/v2/payment-links"

    # 2) v3/payment/payment-links : amount objet (centimes)
    body_v3 = {
        "label": label or "Acompte Energyz",
        "amount": {"value": int(amount_cents), "currency": "EUR"},
        "beneficiary": {
            "name": BRIDGE_BENEFICIARY_NAME or "ENERGYZ",
            "iban": BRIDGE_BENEFICIARY_IBAN
        },
        "success_url": BRIDGE_SUCCESS_URL,
        "cancel_url": BRIDGE_CANCEL_URL,
        "metadata": metadata or {},
    }
    url_v3 = f"{BRIDGE_BASE}/v3/payment/payment-links"

    # Essais dans l'ordre v2 puis v3
    for endpoint, body in ((url_v2, body_v2), (url_v3, body_v3)):
        try:
            res = requests.post(endpoint, headers=_headers(), json=body, timeout=25)
        except Exception as e:
            # problème réseau ponctuel → essaie endpoint suivant
            last_err = f"request error {type(e).__name__}: {e}"
            continue

        if res.status_code in (200, 201):
            data = res.json() or {}
            link = _extract_url(data)
            if link:
                return link
            # si pas d'URL claire, on tente la clé "url" brute
            if isinstance(data, dict) and data.get("url"):
                return data["url"]

        # si 4xx, on tente l'autre schéma/endpoint
        last_err = f"{res.status_code} -> {res.text}"

    # si on est ici, tous les essais ont échoué
    raise Exception(f"Bridge create link failed on all attempts: {last_err}")
