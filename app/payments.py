"""
Wrapper PayPlug : creation de paiements + verification signature webhook.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import requests
from typing import Any

from .config import settings

PAYPLUG_API_URL = "https://api.payplug.com/v1/payments"


# =====================================================
# Selection de cle (multi-IBAN) + parsing montant (compat v1)
# =====================================================

def _choose_api_key(iban: str) -> str:
    """Selectionne la cle PayPlug selon l'IBAN et le mode (test/live)."""
    mode = (settings.PAYPLUG_MODE or "").lower()
    key_dict = json.loads(
        settings.PAYPLUG_KEYS_TEST_JSON if mode == "test" else settings.PAYPLUG_KEYS_LIVE_JSON
    )
    return key_dict.get((iban or "").strip(), "")


def cents_from_str(amount_str: str) -> int:
    """Convertit un montant texte en centimes (ex: '1250.00' -> 125000)."""
    try:
        if not amount_str:
            return 0
        cleaned = (
            str(amount_str)
            .replace("\u20ac", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .replace(",", ".")
        )
        return int(round(float(cleaned) * 100))
    except Exception:
        return 0


def cents_from_float(amount: float) -> int:
    return int(round(float(amount) * 100))


# =====================================================
# V1 : creation payment direct (retrocompat, inutilise en nouveau flux)
# =====================================================

def create_payment(
    api_key: str,
    amount_cents: int,
    email: str,
    address: str,
    client_name: str,
    metadata: dict,
) -> str:
    """Ancienne fonction : cree un paiement direct (utilisee avant refonte)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": email or "client@inconnu.fr",
            "first_name": (client_name or "Client").split(" ")[0],
            "last_name": (client_name or "Inconnu").split(" ")[-1],
            "address1": address or "Adresse non precisee",
        },
        "metadata": metadata,
        "hosted_payment": {"return_url": settings.PUBLIC_BASE_URL},
        "description": metadata.get("description", "Paiement acompte Energyz"),
    }
    res = requests.post(PAYPLUG_API_URL, headers=headers, json=payload, timeout=25)
    if res.status_code not in (200, 201):
        raise RuntimeError(f"Erreur PayPlug : {res.status_code} -> {res.text}")
    data = res.json()
    return data.get("hosted_payment", {}).get("payment_url", "")


# =====================================================
# V3.1 : creation payment direct sans billing
# (BILLING_ENABLED=False : le lien Monday pointe direct sur PayPlug,
#  la facturation est faite manuellement par la comptable)
# =====================================================

def create_payment_direct(
    api_key: str,
    amount_cents: int,
    token: str,
    dossier: dict[str, Any],
) -> dict[str, Any]:
    """
    Cree un payment PayPlug hosted sans infos de facturation :
    le payeur saisit sa carte directement sur la page PayPlug.
    Le token reste dans metadata pour que le webhook retrouve le dossier.
    Retourne le dict PayPlug complet (payment_url + id).
    """
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "hosted_payment": {
            "sent_by": "OTHER",
            "return_url": f"{base}/p/{token}/success",
            "cancel_url": f"{base}/p/{token}/cancelled",
        },
        "notification_url": f"{base}/payplug/webhook",
        "description": dossier.get("prestation_label", "Prestation Energyz")[:100],
        "metadata": {
            "source": "energyz_direct_payment",
            "token": token,
            "monday_item_id": dossier.get("monday_item_id", ""),
            "monday_board_id": dossier.get("monday_board_id", ""),
            "item_name": dossier.get("item_name", "")[:100],
            "montant_ttc": str(dossier.get("montant_ttc", "")),
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    res = requests.post(PAYPLUG_API_URL, headers=headers, json=payload, timeout=25)
    if res.status_code not in (200, 201):
        raise RuntimeError(f"Erreur PayPlug create: {res.status_code} -> {res.text}")
    return res.json()


# =====================================================
# V2 : creation payment avec billing complet
# =====================================================

def create_payment_with_billing(
    api_key: str,
    amount_cents: int,
    token: str,
    billing: dict[str, Any],
    dossier: dict[str, Any],
) -> dict[str, Any]:
    """
    Cree un payment Payplug hosted avec :
      - amount / currency / customer
      - return_url = /p/{token}/success
      - cancel_url = /p/{token}/cancelled
      - notification_url = /payplug/webhook
      - metadata : token + contexte dossier + billing (ceinture + bretelles)

    Retourne le dict Payplug complet (pour lire payment_url et id).
    """
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    payload = {
        "amount": amount_cents,
        "currency": "EUR",
        "customer": {
            "email": billing["email"],
            "first_name": "Facturation",
            "last_name": billing["raison_sociale"][:100],
            "address1": billing["adresse_ligne1"][:255],
            "postcode": billing["code_postal"],
            "city": billing["ville"],
            "country": "FR",
        },
        "hosted_payment": {
            "return_url": f"{base}/p/{token}/success",
            "cancel_url": f"{base}/p/{token}/cancelled",
        },
        "notification_url": f"{base}/payplug/webhook",
        "description": dossier.get("prestation_label", "Prestation Energyz")[:100],
        "metadata": {
            "source": "energyz_partner_payment",
            "token": token,
            "monday_item_id": dossier.get("monday_item_id", ""),
            "monday_board_id": dossier.get("monday_board_id", ""),
            "partner_siret": billing["siret"],
            "partner_legal_name": billing["raison_sociale"],
            "partner_email": billing["email"],
            "partner_address_line1": billing["adresse_ligne1"],
            "partner_address_line2": billing.get("adresse_ligne2", ""),
            "partner_postal_code": billing["code_postal"],
            "partner_city": billing["ville"],
            "partner_country": "FR",
            "prestation_label": dossier.get("prestation_label", ""),
            "prestation_description": dossier.get("prestation_description", ""),
            "montant_ht": str(dossier.get("montant_ht", "")),
            "tva_rate": str(dossier.get("tva_rate", "")),
            "montant_ttc": str(dossier.get("montant_ttc", "")),
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    res = requests.post(PAYPLUG_API_URL, headers=headers, json=payload, timeout=25)
    if res.status_code not in (200, 201):
        raise RuntimeError(f"Erreur PayPlug create: {res.status_code} -> {res.text}")
    return res.json()


# =====================================================
# Signature webhook
# =====================================================

def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """
    Verifie la signature HMAC-SHA256 d'un webhook Payplug.

    Payplug envoie le header 'Payplug-Signature' (ou 'X-Payplug-Signature') contenant
    le HMAC du body, hex.

    Si PAYPLUG_WEBHOOK_SECRET n'est pas configure, on retourne True (mode permissif)
    mais on log un warning au niveau applicatif.
    """
    secret = (settings.PAYPLUG_WEBHOOK_SECRET or "").strip()
    if not secret:
        return True
    if not signature_header:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    # Support "sha256=..." ou "..."
    actual = signature_header.strip()
    if "=" in actual:
        actual = actual.split("=", 1)[1]
    return hmac.compare_digest(expected, actual)
