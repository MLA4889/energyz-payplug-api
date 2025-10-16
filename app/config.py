import os, json
from pydantic import BaseModel

def _loads(key: str, default: dict | None = None) -> dict:
    raw = os.getenv(key, "")
    if not raw:
        return default or {}
    return json.loads(raw)

class Settings(BaseModel):
    # ===== Monday =====
    MONDAY_API_KEY: str = os.getenv("MONDAY_API_KEY", "")
    MONDAY_BOARD_ID: int = int(os.getenv("MONDAY_BOARD_ID", "0"))
    MONDAY_API_URL: str = os.getenv("MONDAY_API_URL", "https://api.monday.com/v2").rstrip("/")

    # Colonnes (adapte avec tes ids)
    EMAIL_COLUMN_ID: str = os.getenv("EMAIL_COLUMN_ID", "")
    ADDRESS_COLUMN_ID: str = os.getenv("ADDRESS_COLUMN_ID", "")
    STATUS_COLUMN_ID: str = os.getenv("STATUS_COLUMN_ID", "")
    IBAN_FORMULA_COLUMN_ID: str = os.getenv("IBAN_FORMULA_COLUMN_ID", "")
    BUSINESS_STATUS_COLUMN_ID: str = os.getenv("BUSINESS_STATUS_COLUMN_ID", "")  # statut "Business Line / Société"

    # Pour les liens d’acompte
    LINK_COLUMN_IDS: dict = _loads("LINK_COLUMN_IDS_JSON", {})             # {"1":"link_xxx","2":"link_yyy"}
    FORMULA_COLUMN_IDS: dict = _loads("FORMULA_COLUMN_IDS_JSON", {})       # {"1":"formula_ac1","2":"formula_ac2"}

    STATUS_AFTER_PAY: dict = _loads("STATUS_AFTER_PAY_JSON", {})           # {"1":"Payé acompte 1","2":"Payé acompte 2"}

    # ===== Devis depuis Monday =====
    CLIENT_TYPE_COLUMN_ID: str = os.getenv("CLIENT_TYPE_COLUMN_ID", "")
    VAT_NUMBER_COLUMN_ID: str = os.getenv("VAT_NUMBER_COLUMN_ID", "")
    QUOTE_AMOUNT_FORMULA_ID: str = os.getenv("QUOTE_AMOUNT_FORMULA_ID", "")
    QUOTE_LINK_COLUMN_ID: str = os.getenv("QUOTE_LINK_COLUMN_ID", "")
    QUOTE_FILES_COLUMN_ID: str = os.getenv("QUOTE_FILES_COLUMN_ID", "")    # optionnel
    QUOTE_TRIGGER_LABEL: str = os.getenv("QUOTE_TRIGGER_LABEL", "Générer devis")
    QUOTE_STATUS_COLUMN_ID: str = os.getenv("QUOTE_STATUS_COLUMN_ID", "")
    QUOTE_STATUS_AFTER_CREATE: str = os.getenv("QUOTE_STATUS_AFTER_CREATE", "")

    POSTCODE_COLUMN_ID: str = os.getenv("POSTCODE_COLUMN_ID", "")
    CITY_COLUMN_ID: str = os.getenv("CITY_COLUMN_ID", "")
    DESCRIPTION_COLUMN_ID: str = os.getenv("DESCRIPTION_COLUMN_ID", "")

    # TVA
    VAT_RATE_COLUMN_ID: str = os.getenv("VAT_RATE_COLUMN_ID", "")
    DEFAULT_VAT_RATE: float = float(os.getenv("DEFAULT_VAT_RATE", "20.0"))

    # ===== PayPlug =====
    PAYPLUG_MODE: str = os.getenv("PAYPLUG_MODE", "test")  # "test" | "live"
    PAYPLUG_KEYS_LIVE: dict = _loads("PAYPLUG_KEYS_LIVE_JSON", {})
    PAYPLUG_KEYS_TEST: dict = _loads("PAYPLUG_KEYS_TEST_JSON", {})
    # Fallback IBAN par statut (si formula vide)
    PAYPLUG_IBAN_BY_STATUS: dict = _loads("PAYPLUG_IBAN_BY_STATUS_JSON", {})

    # ===== Divers =====
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    BRAND_NAME: str = os.getenv("BRAND_NAME", "ENERGYZ")

    # ===== Evoliz =====
    EVOLIZ_PUBLIC_KEY: str = os.getenv("EVOLIZ_PUBLIC_KEY", "")
    EVOLIZ_SECRET_KEY: str = os.getenv("EVOLIZ_SECRET_KEY", "")
    EVOLIZ_COMPANY_ID: str = os.getenv("EVOLIZ_COMPANY_ID", "")
    EVOLIZ_BASE_URL: str = os.getenv("EVOLIZ_BASE_URL", "https://api.evoliz.com").rstrip("/")

settings = Settings()
