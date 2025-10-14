import json
import os
from pydantic import BaseModel


def _loads_env_json(key: str, default: dict | None = None) -> dict:
    raw = os.getenv(key, "")
    if not raw:
        return default or {}
    return json.loads(raw)


class Settings(BaseModel):
    # --- Monday ---
    MONDAY_API_KEY: str = os.getenv("MONDAY_API_KEY", "")
    MONDAY_API_URL: str = os.getenv("MONDAY_API_URL", "https://api.monday.com/v2")
    MONDAY_BOARD_ID: int = int(os.getenv("MONDAY_BOARD_ID", "0"))

    # Paiements (acomptes)
    LINK_COLUMN_IDS: dict = _loads_env_json("LINK_COLUMN_IDS_JSON", {})          # {"1":"link_xxx","2":"link_yyy"}
    FORMULA_COLUMN_IDS: dict = _loads_env_json("FORMULA_COLUMN_IDS_JSON", {})    # {"1":"formula_xxx","2":"formula_yyy"}
    EMAIL_COLUMN_ID: str = os.getenv("EMAIL_COLUMN_ID", "")
    ADDRESS_COLUMN_ID: str = os.getenv("ADDRESS_COLUMN_ID", "")
    IBAN_FORMULA_COLUMN_ID: str = os.getenv("IBAN_FORMULA_COLUMN_ID", "")
    STATUS_AFTER_PAY: dict = _loads_env_json("STATUS_AFTER_PAY_JSON", {})        # {"1":"Acompte 1 payé","2":"Acompte 2 payé"}
    STATUS_COLUMN_ID: str = os.getenv("STATUS_COLUMN_ID", "")

    # Devis (Evoliz) depuis Monday
    CLIENT_TYPE_COLUMN_ID: str = os.getenv("CLIENT_TYPE_COLUMN_ID", "")          # status "Particulier / Professionnel"
    VAT_NUMBER_COLUMN_ID: str = os.getenv("VAT_NUMBER_COLUMN_ID", "")            # text "FR..."
    POSTCODE_COLUMN_ID: str = os.getenv("POSTCODE_COLUMN_ID", "")                # optionnel
    CITY_COLUMN_ID: str = os.getenv("CITY_COLUMN_ID", "")                        # optionnel
    DESCRIPTION_COLUMN_ID: str = os.getenv("DESCRIPTION_COLUMN_ID", "")          # optionnel (long_text / text)
    QUOTE_AMOUNT_FORMULA_ID: str = os.getenv("QUOTE_AMOUNT_FORMULA_ID", "")      # numbers / formula (HT)
    QUOTE_LINK_COLUMN_ID: str = os.getenv("QUOTE_LINK_COLUMN_ID", "")            # link (PDF Evoliz)
    QUOTE_FILES_COLUMN_ID: str = os.getenv("QUOTE_FILES_COLUMN_ID", "")          # files (PDF hébergé chez Monday)
    QUOTE_STATUS_COLUMN_ID: str = os.getenv("QUOTE_STATUS_COLUMN_ID", "")        # optionnel (colonne "Créer devis")
    QUOTE_STATUS_AFTER_CREATE: str = os.getenv("QUOTE_STATUS_AFTER_CREATE", "")  # optionnel (ex: "Devis généré")
    QUOTE_TRIGGER_LABEL: str = os.getenv("QUOTE_TRIGGER_LABEL", "Générer devis")

    # --- PayPlug ---
    PAYPLUG_MODE: str = os.getenv("PAYPLUG_MODE", "live")                        # "live" ou "test"
    PAYPLUG_KEYS_LIVE: dict = _loads_env_json("PAYPLUG_KEYS_LIVE_JSON", {})
    PAYPLUG_KEYS_TEST: dict = _loads_env_json("PAYPLUG_KEYS_TEST_JSON", {})

    # --- Divers ---
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    BRAND_NAME: str = os.getenv("BRAND_NAME", "ENERGYZ")

    # --- Evoliz ---
    EVOLIZ_PUBLIC_KEY: str = os.getenv("EVOLIZ_PUBLIC_KEY", "")
    EVOLIZ_SECRET_KEY: str = os.getenv("EVOLIZ_SECRET_KEY", "")
    EVOLIZ_COMPANY_ID: str = os.getenv("EVOLIZ_COMPANY_ID", "")
    EVOLIZ_BASE_URL: str = os.getenv("EVOLIZ_BASE_URL", "https://www.evoliz.io")
    EVOLIZ_PAYTERM_ID: int = int(os.getenv("EVOLIZ_PAYTERM_ID", "1"))            # 1 = comptant/à réception (ajuste si besoin)
    EVOLIZ_TIMEOUT: int = int(os.getenv("EVOLIZ_TIMEOUT", "20"))


settings = Settings()
