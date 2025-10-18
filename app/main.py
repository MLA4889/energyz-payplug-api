from fastapi import FastAPI, HTTPException
from .payments import _choose_api_key, cents_from_str, create_payment
from .config import settings

app = FastAPI(title="Energyz PayPlug API", version="1.0")


@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz PayPlug API is live 🚀"}


@app.post("/pay/acompte/{n}")
async def create_acompte_link(n: int):
    """Crée un lien de paiement PayPlug pour un acompte donné."""
    try:
        client_name = "Jean Dupont"
        email = "jean.dupont@mail.com"
        address = "12 rue de Paris"
        amount = "1250.00"
        iban = "FR76 1695 8000 0130 5670 5696 366"

        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(status_code=400, detail="Clé API PayPlug introuvable pour cet IBAN")

        amount_cents = cents_from_str(amount) // (2 if n == 2 else 1)
        if amount_cents <= 0:
            raise HTTPException(status_code=400, detail="Montant invalide")

        metadata = {"client": client_name, "acompte": str(n)}
        payment_url = create_payment(api_key, amount_cents, email, address, client_name, metadata)

        return {"status": "ok", "acompte": n, "payment_url": payment_url}

    except Exception as e:
        print(f"❌ Erreur : {e}")
        raise HTTPException(status_code=400, detail=str(e))
