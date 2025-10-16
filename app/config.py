import os
import json

class Settings:
    BRAND_NAME = "ENERGYZ"
    MONDAY_API_KEY = os.getenv("MONDAY_API_KEY")
    MONDAY_BOARD_ID = int(os.getenv("MONDAY_BOARD_ID", "0"))

    EMAIL_COLUMN_ID = os.getenv("EMAIL_COLUMN_ID")
    ADDRESS_COLUMN_ID = os.getenv("ADDRESS_COLUMN_ID")
    IBAN_FORMULA_COLUMN_ID = os.getenv("IBAN_FORMULA_COLUMN_ID")

    FORMULA_COLUMN_IDS = json.loads(os.getenv("FORMULA_COLUMN_IDS", "{}"))
    LINK_COLUMN_IDS = json.loads(os.getenv("LINK_COLUMN_IDS", "{}"))
    STATUS_COLUMN_ID = os.getenv("STATUS_COLUMN_ID")

    PAYPLUG_TEST_KEY = os.getenv("PAYPLUG_TEST_KEY")
    PAYPLUG_LIVE_KEY = os.getenv("PAYPLUG_LIVE_KEY")

    EVOLIZ_BASE_URL = os.getenv("EVOLIZ_BASE_URL", "https://api.evoliz.com")
    EVOLIZ_COMPANY_ID = os.getenv("EVOLIZ_COMPANY_ID")
    EVOLIZ_PUBLIC_KEY = os.getenv("EVOLIZ_PUBLIC_KEY")
    EVOLIZ_SECRET_KEY = os.getenv("EVOLIZ_SECRET_KEY")

    STATUS_AFTER_PAY = {
        "1": "Acompte 1 payé",
        "2": "Acompte 2 payé",
        "3": "Acompte 3 payé",
        "4": "Acompte 4 payé",
    }

settings = Settings()
