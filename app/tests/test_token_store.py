"""Tests : cycle de vie d'un token + idempotence."""
from pathlib import Path

import pytest

from app import token_store


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Chaque test a son propre fichier json."""
    fake = tmp_path / "store.json"
    monkeypatch.setattr(token_store, "_PATH", fake)
    yield fake


def _make():
    return token_store.create_pending(
        monday_item_id="42",
        monday_board_id="999",
        prestation_label="Audit test",
        prestation_description="description",
        montant_ht=100.00,
        tva_rate=20.0,
        montant_ttc=120.00,
        iban="FR76 0000",
        item_name="DOSSIER XYZ",
    )


def test_create_and_get():
    entry = _make()
    again = token_store.get(entry["token"])
    assert again is not None
    assert again["status"] == "pending"
    assert again["montant_ttc"] == 120.00


def test_mark_payment_created():
    entry = _make()
    token_store.mark_payment_created(
        entry["token"], payplug_payment_id="pay_123", billing={"siret": "12345678900014"}
    )
    refreshed = token_store.get(entry["token"])
    assert refreshed["status"] == "payment_created"
    assert refreshed["payplug_payment_id"] == "pay_123"
    assert refreshed["billing"]["siret"] == "12345678900014"


def test_mark_paid_then_invoiced():
    entry = _make()
    token_store.mark_paid(entry["token"], paid_at_iso="2026-04-23T10:00:00+00:00")
    assert token_store.get(entry["token"])["status"] == "paid"
    token_store.mark_invoiced(
        entry["token"],
        evoliz_client_id="cli_9",
        evoliz_invoice_id="inv_42",
        invoice_number="F2026-000001",
        invoice_date="2026-04-23",
    )
    refreshed = token_store.get(entry["token"])
    assert refreshed["status"] == "invoiced"
    assert refreshed["invoice_number"] == "F2026-000001"


def test_webhook_idempotence():
    entry = _make()
    assert token_store.was_webhook_processed("pay_777") is False
    token_store.mark_webhook_processed("pay_777", entry["token"])
    assert token_store.was_webhook_processed("pay_777") is True


def test_find_token_by_payplug_id():
    entry = _make()
    token_store.mark_payment_created(
        entry["token"], payplug_payment_id="pay_abc", billing={"siret": "12"}
    )
    assert token_store.find_token_by_payplug_id("pay_abc") == entry["token"]
    assert token_store.find_token_by_payplug_id("pay_unknown") is None
