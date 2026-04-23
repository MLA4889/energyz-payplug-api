"""
Cree un token de test dans le store local pour pouvoir tester /p/{token}
sans declencher de webhook Monday.

Usage :
  cd energyz-payplug-api-main
  python scripts/seed_test_token.py
"""
import os
import sys
from pathlib import Path

# .env load (evite d'avoir a l'exporter)
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

# Importer app.* APRES avoir charge l'env
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import token_store  # noqa: E402

entry = token_store.create_pending(
    monday_item_id="9999999999",
    monday_board_id="2047255654",
    prestation_label="Note de dimensionnement - Destratificateur d'air",
    prestation_description="Audit test LOCAL - ne pas facturer",
    montant_ht=400.00,
    tva_rate=20.0,
    montant_ttc=480.00,
    iban="FR76 1695 8000 0100 0571 1982 492",
    item_name="DOSSIER TEST LOCAL",
)
print(f"Token cree : {entry['token']}")
print(f"URL locale : http://localhost:8000/p/{entry['token']}")
