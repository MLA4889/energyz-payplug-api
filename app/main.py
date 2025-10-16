from fastapi import FastAPI, HTTPException
from .payments import _choose_api_key, cents_from_str, create_payment
from .config import settings
import requests

app = FastAPI(title="Energyz PayPlug API - Final Stable")

@app.get("/")
def home():
    return {"status": "ok", "message": "API is live"}


@app.post("/pay/acompte/{n}")
async def create_acompte_link(n: int):
    try:
        # Simule lecture Monday (pour test)
        iban = "FR76 1695 8000 0130 5670 5696 366"
        client = "Jean Dupont"
        email = "jean.dupont@mail.com"
        address = "12 rue de Paris"
        total = "1250.00"

        print(f"➡️ Création acompte {n} pour {client}")

        # 1️⃣ Trouver la clé PayPlug correspondante
        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(status_code=400, detail="Clé API PayPlug introuvable.")

        # 2️⃣ Convertir le montant
        amount_cents = cents_from_str(total) // (2 if n == 2 else 1)
        if amount_cents <= 0:
            raise HTTPException(status_code=400, detail="Montant invalide.")

        # 3️⃣ Créer le lien PayPlug
        metadata = {"client": client, "acompte": str(n)}
        url = create_payment(api_key, amount_cents, email, address, client, metadata)

        return {"status": "ok", "acompte": n, "payment_url": url}

    except Exception as e:
        print(f"❌ Erreur globale: {e}")
        raise HTTPException(status_code=400, detail=str(e))
