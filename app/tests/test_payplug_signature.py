"""Verification HMAC-SHA256 du webhook Payplug."""
import hmac
import hashlib

import pytest

from app import payments
from app.config import settings


RAW = b'{"type":"payment.succeeded","data":{"object":{"id":"pay_123"}}}'


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_no_secret_configured_is_permissive(monkeypatch):
    monkeypatch.setattr(settings, "PAYPLUG_WEBHOOK_SECRET", "")
    assert payments.verify_webhook_signature(RAW, "anything") is True


def test_valid_signature_hex(monkeypatch):
    monkeypatch.setattr(settings, "PAYPLUG_WEBHOOK_SECRET", "supersecret")
    sig = _sign(RAW, "supersecret")
    assert payments.verify_webhook_signature(RAW, sig) is True


def test_valid_signature_prefixed(monkeypatch):
    monkeypatch.setattr(settings, "PAYPLUG_WEBHOOK_SECRET", "supersecret")
    sig = "sha256=" + _sign(RAW, "supersecret")
    assert payments.verify_webhook_signature(RAW, sig) is True


def test_invalid_signature(monkeypatch):
    monkeypatch.setattr(settings, "PAYPLUG_WEBHOOK_SECRET", "supersecret")
    bad = _sign(RAW, "wrong-secret")
    assert payments.verify_webhook_signature(RAW, bad) is False


def test_missing_signature(monkeypatch):
    monkeypatch.setattr(settings, "PAYPLUG_WEBHOOK_SECRET", "supersecret")
    assert payments.verify_webhook_signature(RAW, None) is False


def test_altered_body_fails_signature(monkeypatch):
    monkeypatch.setattr(settings, "PAYPLUG_WEBHOOK_SECRET", "supersecret")
    sig = _sign(RAW, "supersecret")
    altered = RAW + b" "  # espace ajoute
    assert payments.verify_webhook_signature(altered, sig) is False
