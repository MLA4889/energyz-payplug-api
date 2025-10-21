from pydantic_settings import BaseSettings
from pydantic import ValidationError
import os
import sys
import logging

logger = logging.getLogger("energyz")

class Settings(BaseSettings):
    # Monday
    MONDAY_API_KEY: str
    MONDAY_BOARD_ID: int

    # Evoliz (compat)
    EVOLIZ_BASE_URL: str
    EVOLIZ_COMPANY_ID: str
    EVOLIZ_PUBLIC_KEY: str
    EVOLIZ_SECRET_KEY: str

    # PayPlug
    PAYPLUG_KEYS_TEST_JSON: str
    PAYPLUG_KEYS_LIVE_JSON: str
    PAYPLUG_MODE: str
    PUBLIC_BASE_URL: str
    NOTIFICATION_URL: str | None = None

    # Colonnes Monday
    EMAIL_COLUMN_ID: str
    ADDRESS_COLUMN_ID: str
    DESCRIPTION_COLUMN_ID: str
    IBAN_FORMULA_COLUMN_ID: str
    QUOTE_AMOUNT_FORMULA_ID: str
    STATUS_COLUMN_ID: str
    BUSINESS_STATUS_COLUMN_ID: str
    CLIENT_TYPE_COLUMN_ID: str

    # Acomptes / mapping
    FORMULA_COLUMN_IDS_JSON: str
    LINK_COLUMN_IDS_JSON: str
    STATUS_AFTER_PAY_JSON: str
    TRIGGER_STATUS_COLUMN_ID: str
    TRIGGER_LABELS_JSON: str

    # IBAN mapping fallback
    IBAN_BY_STATUS_JSON: str | None = None
    FORCE_CHECKOUT_COLLECT_CONTACT: str | None = None

    # Bridge (PIS)
    BRIDGE_BASE_URL: str
    BRIDGE_VERSION: str
    BRIDGE_CLIENT_ID: str
    BRIDGE_CLIENT_SECRET: str
    BRIDGE_SUCCESS_URL: str
    BRIDGE_CANCEL_URL: str
    BRIDGE_WEBHOOK_SECRET: str
    BRIDGE_BENEFICIARY_NAME: str
    BRIDGE_BENEFICIARY_IBAN: str

try:
    # charge directement depuis l'environnement Render
    settings = Settings()
    # petit log de contrôle pour le déploiement
    logger.info(
        "[BOOT] Settings chargés. BRIDGE_BASE_URL=%s, BRIDGE_VERSION=%s, PAYPLUG_MODE=%s",
        os.getenv("BRIDGE_BASE_URL"),
        os.getenv("BRIDGE_VERSION"),
        os.getenv("PAYPLUG_MODE"),
    )
except ValidationError as e:
    # Rend l’erreur explicite dans les logs Render (sinon “cause unknown”)
    missing = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err.get("loc", []))
        msg = err.get("msg", "")
        missing.append(f"{loc}: {msg}")
    logger.error("❌ ENV manquantes ou invalides:\n- " + "\n- ".join(missing))
    # on re-raise pour que Render marque le deploy en échec (mais avec un message clair)
    raise
