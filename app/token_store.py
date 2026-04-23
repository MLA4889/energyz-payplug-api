"""
Stockage persistant simple des tokens de paiement.

On choisit un fichier JSON sur disque (Render permet un persistent disk)
plutot que Redis ou une base, pour :
  - zero dependance externe,
  - restauration triviale (le fichier est la sauvegarde),
  - volumes tres faibles (quelques paiements/jour).

Le fichier est lu/ecrit sous un verrou thread-safe.
Structure : { token: { ... payload ... } }
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import uuid

from .config import settings


_LOCK = threading.RLock()
_PATH = Path(settings.TOKEN_STORE_PATH)


def _ensure_parent() -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict[str, Any]:
    _ensure_parent()
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Fichier corrompu : on ne detruit pas l'historique silencieusement,
        # on repart d'un dict vide mais on renomme la copie fautive.
        backup = _PATH.with_suffix(f".corrupt.{int(time.time())}.json")
        try:
            _PATH.rename(backup)
        except OSError:
            pass
        return {}


def _save(data: dict[str, Any]) -> None:
    _ensure_parent()
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_pending(
    monday_item_id: str,
    monday_board_id: str,
    prestation_label: str,
    prestation_description: str,
    montant_ht: float,
    tva_rate: float,
    montant_ttc: float,
    iban: str,
    item_name: str = "",
) -> dict[str, Any]:
    """
    Cree une entree 'pending' avec un token UUID.
    Retourne le dict complet (utile pour logs).
    """
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.TOKEN_TTL_DAYS)
    entry = {
        "token": token,
        "status": "pending",
        "monday_item_id": str(monday_item_id),
        "monday_board_id": str(monday_board_id),
        "item_name": item_name,
        "prestation_label": prestation_label,
        "prestation_description": prestation_description,
        "montant_ht": float(montant_ht),
        "tva_rate": float(tva_rate),
        "montant_ttc": float(montant_ttc),
        "iban": iban,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "billing": None,
        "payplug_payment_id": None,
        "evoliz_client_id": None,
        "evoliz_invoice_id": None,
        "invoice_number": None,
        "invoice_date": None,
        "paid_at": None,
        "last_error": None,
    }
    with _LOCK:
        data = _load()
        data[token] = entry
        _save(data)
    return entry


def get(token: str) -> dict[str, Any] | None:
    with _LOCK:
        data = _load()
        return data.get(token)


def is_expired(entry: dict[str, Any]) -> bool:
    try:
        return datetime.fromisoformat(entry["expires_at"]) < datetime.now(timezone.utc)
    except (KeyError, ValueError):
        return True


def update(token: str, **fields: Any) -> dict[str, Any] | None:
    """Merge de champs sur l'entree existante."""
    with _LOCK:
        data = _load()
        entry = data.get(token)
        if entry is None:
            return None
        entry.update(fields)
        data[token] = entry
        _save(data)
        return entry


def mark_payment_created(token: str, payplug_payment_id: str, billing: dict[str, Any]) -> dict[str, Any] | None:
    return update(
        token,
        status="payment_created",
        payplug_payment_id=payplug_payment_id,
        billing=billing,
    )


def mark_paid(token: str, paid_at_iso: str | None = None) -> dict[str, Any] | None:
    return update(token, status="paid", paid_at=paid_at_iso or _now_iso())


def mark_invoiced(
    token: str,
    evoliz_client_id: str,
    evoliz_invoice_id: str,
    invoice_number: str,
    invoice_date: str,
) -> dict[str, Any] | None:
    return update(
        token,
        status="invoiced",
        evoliz_client_id=evoliz_client_id,
        evoliz_invoice_id=evoliz_invoice_id,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
    )


def mark_error(token: str, step: str, message: str) -> dict[str, Any] | None:
    return update(
        token,
        last_error={"step": step, "message": message, "at": _now_iso()},
    )


# =====================================================
# Idempotence webhook Payplug
# =====================================================

def was_webhook_processed(payplug_payment_id: str) -> bool:
    """True si un webhook Payplug pour ce payment_id a deja ete traite avec succes."""
    with _LOCK:
        data = _load()
        key = f"__processed__:{payplug_payment_id}"
        return bool(data.get(key))


def mark_webhook_processed(payplug_payment_id: str, token: str) -> None:
    with _LOCK:
        data = _load()
        key = f"__processed__:{payplug_payment_id}"
        data[key] = {"token": token, "processed_at": _now_iso()}
        _save(data)


def find_token_by_payplug_id(payplug_payment_id: str) -> str | None:
    """Retrouve le token associe a un payment_id Payplug (ceinture + bretelles)."""
    with _LOCK:
        data = _load()
        for token, entry in data.items():
            if token.startswith("__"):
                continue
            if entry.get("payplug_payment_id") == payplug_payment_id:
                return token
    return None
