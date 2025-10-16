import json
import os
from pydantic import BaseModel


def _loads_env_json(key: str, default: dict | None = None) -> dict:
    raw = os.getenv(key, "")
    if not raw:
        return default or {}
    return json.loads(raw)


class Settings(BaseModel):
    # ===== Monday =====
    MONDAY_API_KEY: str = os.getenv("MONDAY_API_KEY", "")
    MONDAY_BOARD_ID: int = int(os.getenv("MONDAY_BOARD_ID", "0"))
    MONDAY_API_URL: str = os.getenv("MONDAY_API_URL", "https://api.monday.com/v2").rstrip("/")

    LINK_COLUMN_IDS: dict = _loads_env_json("LINK_COLUMN_IDS_JSON", {})
    FORMULA_COLUMN_IDS: dict = _loads_env_json("FORMULA_COLUMN_IDS_JSON", {})
    EMAIL_COLUMN_ID: str = os.getenv("EMAIL_COLUMN_ID", "")
    ADDRESS_COLUMN_ID: str = os.getenv("ADDRESS_COLUMN_ID", "")
    STATUS_AFTER_PAY: dict = _loads_env_json("STATUS_AFTER_PAY_JSON", {})
    STATUS_COLUMN_ID: str = os.getenv("STATUS_COLUMN_ID", "")
    IBAN_FORMULA_COLUMN_ID: str = os.getenv("IBAN_FORMULA_COLUMN_ID", "")

    # ===== Devis depuis Monday =====
    CLIENT_TYPE_COLUMN_ID: str = os.getenv("CLIENT_TYPE_COLUMN_ID", "")
    VAT_NUMBER_COLUMN_ID: str = os.getenv("VAT_NUMBER_COLUMN_ID", "")
    QUOTE_AMOUNT_FORMULA_ID: str = os.getenv("QUOTE_AMOUNT_FORMULA_ID", "")
    QUOTE_LINK_COLUMN_ID: str = os.getenv("QUOTE_LINK_COLUMN_ID", "")

    # Colonne Files unique (optionnelle)
    DOC_FILES_COLUMN_ID: str = os.getenv("DOC_FILES_COLUMN_ID", "")
    # Backward compat si tu veux séparer
    QUOTE_FILES_COLUMN_ID: str = os.getenv("QUOTE_FILES_COLUMN_ID", "")
    INVOICE_FILES_COLUMN_ID: str = os.getenv("INVOICE_FILES_COLUMN_ID", "")

    QUOTE_TRIGGER_LABEL: str = os.getenv("QUOTE_TRIGGER_LABEL", "Générer devis")
    QUOTE_STATUS_COLUMN_ID: str = os.getenv("QUOTE_STATUS_COLUMN_ID", "")
    QUOTE_STATUS_AFTER_CREATE: str = os.getenv("QUOTE_STATUS_AFTER_CREATE", "")

    # Colonnes optionnelles CP/Ville/Description
    POSTCODE_COLUMN_ID: str = os.getenv("POSTCODE_COLUMN_ID", "")
    CITY_COLUMN_ID: str = os.getenv("CITY_COLUMN_ID", "")
    DESCRIPTION_COLUMN_ID: str = os.getenv("DESCRIPTION_COLUMN_ID", "")

    # --- Taux de TVA ---
    VAT_RATE_COLUMN_ID: str = os.getenv("VAT_RATE_COLUMN_ID", "")
    DEFAULT_VAT_RATE: float = float(os.getenv("DEFAULT_VAT_RATE", "20.0"))

    # ===== Factures =====
    INVOICE_LABEL_ACOMPTE1: str = os.getenv("INVOICE_LABEL_ACOMPTE1", "Facturer acompte 1")
    INVOICE_LABEL_ACOMPTE2: str = os.getenv("INVOICE_LABEL_ACOMPTE2", "Facturer acompte 2")
    INVOICE_LABEL_SOLDE: str = os.getenv("INVOICE_LABEL_SOLDE", "Facturer solde")

    INVOICE_LINK_AC1_COLUMN_ID: str = os.getenv("INVOICE_LINK_AC1_COLUMN_ID", "")
    INVOICE_LINK_AC2_COLUMN_ID: str = os.getenv("INVOICE_LINK_AC2_COLUMN_ID", "")
    INVOICE_LINK_FINAL_COLUMN_ID: str = os.getenv("INVOICE_LINK_FINAL_COLUMN_ID", "")

    EVOLIZ_PAYTERM_ID: int = int(os.getenv("EVOLIZ_PAYTERM_ID", "1"))

    # ===== PayPlug =====
    PAYPLUG_MODE: str = os.getenv("PAYPLUG_MODE", "live")
    PAYPLUG_KEYS_LIVE: dict = _loads_env_json("PAYPLUG_KEYS_LIVE_JSON", {})
    PAYPLUG_KEYS_TEST: dict = _loads_env_json("PAYPLUG_KEYS_TEST_JSON", {})

    # ===== Divers =====
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    BRAND_NAME: str = os.getenv("BRAND_NAME", "ENERGYZ")

    # ===== Evoliz =====
    EVOLIZ_PUBLIC_KEY: str = os.getenv("EVOLIZ_PUBLIC_KEY", "")
    EVOLIZ_SECRET_KEY: str = os.getenv("EVOLIZ_SECRET_KEY", "")
    EVOLIZ_COMPANY_ID: str = os.getenv("EVOLIZ_COMPANY_ID", "")
    EVOLIZ_BASE_URL: str = os.getenv("EVOLIZ_BASE_URL", "https://api.evoliz.com").rstrip("/")


settings = Settings()
