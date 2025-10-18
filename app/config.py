from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Monday
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # Evoliz
    EVOLIZ_BASE_URL: str = "https://www.evoliz.io"
    EVOLIZ_COMPANY_ID: str = ""
    EVOLIZ_PUBLIC_KEY: str = ""
    EVOLIZ_SECRET_KEY: str = ""

    # PayPlug
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PAYPLUG_MODE: str = "test"

    # Monday Column IDs (existants)
    EMAIL_COLUMN_ID: str = "email_mkwn72p4"
    ADDRESS_COLUMN_ID: str = "location_mkwnm6xb"
    DESCRIPTION_COLUMN_ID: str = "formula_mkwqeyt4"
    IBAN_FORMULA_COLUMN_ID: str = "formula_mkwnb561"
    QUOTE_AMOUNT_FORMULA_ID: str = "numeric_mkwq2s74"  # Total HT (déjà chez toi)
    STATUS_COLUMN_ID: str = "color_mkwnsdd6"
    BUSINESS_STATUS_COLUMN_ID: str = "color_mkwnxf1h"

    # Acomptes
    FORMULA_COLUMN_IDS_JSON: str = '{"1":"formula_mkwnberr","2":"formula_mkwnntn2"}'
    LINK_COLUMN_IDS_JSON: str = '{"1":"link_mkwnz493","2":"link_mkwn3ph9"}'
    STATUS_AFTER_PAY_JSON: str = '{"1":"Payé acompte 1","2":"Payé acompte 2"}'

    # Devis (NOUVEAU) — valeurs par défaut = tes IDs
    CREATE_QUOTE_STATUS_COLUMN_ID: str = "color_mkwphad9"  # "Créer devis"
    QUOTE_LINK_COLUMN_ID: str = "link_mkwqahhx"           # "Devis"
    VAT_RATE_COLUMN_ID: str = "numeric_mkwqdrn3"          # "TVA"
    VAT_NUMBER_COLUMN_ID: str = "text_mkwqjydy"           # (optionnel)
    TOTAL_HT_COLUMN_ID: str = "numeric_mkwq2s74"          # "Montant total HT"
    TOTAL_TTC_COLUMN_ID: str = "numeric_mkwns793"         # "Montant total TTC"

    # Divers
    PUBLIC_BASE_URL: str = "https://energyz-payplug-api-1.onrender.com"
    IBAN_BY_STATUS_JSON: Optional[str] = '{"Enerlux":"FR76 1695 8000 0130 5670 5696 366","Energyz MAR":"FR76 1695 8000 0130 5670 5696 366","Energyz Divers":"FR76 1695 8000 0100 0571 1982 492"}'

    class Config:
        env_file = ".env"

settings = Settings()
