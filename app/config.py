import os, json

class Settings:
    BRAND_NAME = os.getenv("BRAND_NAME", "ENERGYZ")
    MONDAY_API_KEY = os.getenv("MONDAY_API_KEY")
    MONDAY_BOARD_ID = int(os.getenv("MONDAY_BOARD_ID", "0"))

    EMAIL_COLUMN_ID = os.getenv("EMAIL_COLUMN_ID")
    ADDRESS_COLUMN_ID = os.getenv("ADDRESS_COLUMN_ID")
    IBAN_FORMULA_COLUMN_ID = os.getenv("IBAN_FORMULA_COLUMN_ID")

    FORMULA_COLUMN_IDS = json.loads(os.getenv("FORMULA_COLUMN_JSON", "{}"))
    LINK_COLUMN_IDS = json.loads(os.getenv("LINK_COLUMN_JSON", "{}"))
    STATUS_AFTER_PAY = json.loads(os.getenv("STATUS_AFTER_PAY_JSON", "{}"))

    PAYPLUG_KEYS = json.loads(os.getenv("PAYPLUG_KEYS_JSON", "{}"))
    PAYPLUG_MODE = os.getenv("PAYPLUG_MODE", "test")

    EVOLIZ_BASE_URL = os.getenv("EVOLIZ_BASE_URL", "https://api.evoliz.com")
    EVOLIZ_COMPANY_ID = os.getenv("EVOLIZ_COMPANY_ID")
    EVOLIZ_PUBLIC_KEY = os.getenv("EVOLIZ_PUBLIC_KEY")
    EVOLIZ_SECRET_KEY = os.getenv("EVOLIZ_SECRET_KEY")

settings = Settings()
