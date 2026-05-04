"""
Configuration de l'application.

Fusion des champs :
  - v2.4 destrat (Bridge PIS + colonnes Monday existantes)
  - v3 (facturation partenaire automatique : billing, Evoliz invoices, PDF upload)

Les champs Bridge sont Optional pour permettre un deploiement sans Bridge.
"""
from pydantic_settings import BaseSettings
from pydantic import ValidationError
import logging
import os

logger = logging.getLogger("energyz")


class Settings(BaseSettings):
    # =========================================================
    # Monday
    # =========================================================
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # =========================================================
    # Evoliz
    # =========================================================
    EVOLIZ_BASE_URL: str = "https://www.evoliz.io"
    EVOLIZ_COMPANY_ID: str
    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str
    EVOLIZ_APP_BASE_URL: str | None = None
    EVOLIZ_TENANT_SLUG: str | None = None

    # =========================================================
    # PayPlug
    # =========================================================
    PAYPLUG_KEYS_TEST_JSON: str = "{}"
    PAYPLUG_KEYS_LIVE_JSON: str = "{}"
    PAYPLUG_MODE: str = "live"
    PAYPLUG_WEBHOOK_SECRET: str | None = None
    PUBLIC_BASE_URL: str
    NOTIFICATION_URL: str | None = None

    # =========================================================
    # Colonnes Monday existantes (heritees v2.4)
    # =========================================================
    EMAIL_COLUMN_ID: str = ""
    ADDRESS_COLUMN_ID: str = ""
    DESCRIPTION_COLUMN_ID: str = ""
    IBAN_FORMULA_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    STATUS_COLUMN_ID: str
    BUSINESS_STATUS_COLUMN_ID: str = ""
    CLIENT_TYPE_COLUMN_ID: str = ""
    SIRET_SITE_COLUMN_ID: str = ""

    # =========================================================
    # Acomptes / mapping (retrocompat)
    # =========================================================
    FORMULA_COLUMN_IDS_JSON: str = "{}"
    LINK_COLUMN_IDS_JSON: str = "{}"
    STATUS_AFTER_PAY_JSON: str = "{}"
    TRIGGER_STATUS_COLUMN_ID: str = "status"
    TRIGGER_LABELS_JSON: str = '{"1":"Generer acompte 1"}'
    FORMULA_FALLBACK_VALUE: str | None = None

    # =========================================================
    # IBAN / fallback
    # =========================================================
    IBAN_BY_STATUS_JSON: str | None = None
    FORCE_IBAN: str | None = None
    FORCE_CHECKOUT_COLLECT_CONTACT: str | None = None

    # =========================================================
    # Bridge PIS (v2.4) — Optional pour pouvoir desactiver
    # =========================================================
    BRIDGE_BASE_URL: str | None = None
    BRIDGE_VERSION: str | None = None
    BRIDGE_CLIENT_ID: str | None = None
    BRIDGE_CLIENT_SECRET: str | None = None
    BRIDGE_SUCCESS_URL: str | None = None
    BRIDGE_CANCEL_URL: str | None = None
    BRIDGE_WEBHOOK_SECRET: str | None = None
    BRIDGE_BENEFICIARY_NAME: str | None = None
    BRIDGE_BENEFICIARY_IBAN: str | None = None

    # =========================================================
    # v3 : facturation partenaire automatique
    # =========================================================

    # Labels sur STATUS_COLUMN_ID (avec accents - doivent matcher EXACTEMENT
    # les labels Monday existants : "Payé", "Facturé", "Bloqué")
    STATUS_LABEL_PAID: str = "Payé"
    STATUS_LABEL_INVOICED: str = "Facturé"
    STATUS_LABEL_ERROR: str = "Bloqué"

    # Colonnes Monday creees pour la facturation partenaire
    INVOICE_PDF_COLUMN_ID: str
    INVOICE_NUMBER_COLUMN_ID: str
    INVOICE_DATE_COLUMN_ID: str
    BILLING_SIRET_COLUMN_ID: str
    BILLING_EMAIL_COLUMN_ID: str
    BILLING_LEGAL_NAME_COLUMN_ID: str

    # Colonne ou on ecrit le lien /p/{token}
    PAYMENT_LINK_COLUMN_ID: str

    # TVA + libelle par defaut
    DEFAULT_VAT_RATE: float = 20.0
    DEFAULT_PRESTATION_LABEL: str = (
        "Note de dimensionnement - Destratificateur d'air"
    )

    # Token store
    TOKEN_TTL_DAYS: int = 30
    TOKEN_STORE_PATH: str = "/var/data/token_store.json"

    # Admin / debug
    ADMIN_API_KEY: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"


try:
    settings = Settings()
    logger.info(
        "[BOOT] Settings OK. BRIDGE_BASE_URL=%s PAYPLUG_MODE=%s TOKEN_STORE_PATH=%s",
        os.getenv("BRIDGE_BASE_URL"),
        os.getenv("PAYPLUG_MODE"),
        os.getenv("TOKEN_STORE_PATH"),
    )
except ValidationError as e:
    missing = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err.get("loc", []))
        msg = err.get("msg", "")
        missing.append(f"{loc}: {msg}")
    logger.error("ENV manquantes ou invalides:\n- " + "\n- ".join(missing))
    raise
