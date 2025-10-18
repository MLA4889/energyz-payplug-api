from fastapi import FastAPI, Request, HTTPException
from .payments import _choose_api_key, cents_from_str, create_payment
from .monday import get_item_columns, set_link_in_column, set_status
from .config import settings
import json

app = FastAPI(title="Energyz PayPlug API", version="1.0")


@app.get("/")
def root():
    return {"status": "ok", "message": "Energyz PayPlug API is live 🚀"}


# --- Webhook déclenché par Monday (colonne “Générer acompte X”) ---
@app.post("/quote/from_monday")
async def quote_from_monday(request: Request):
    try:
        payload = await request.json()
        print("📩 Webhook Monday reçu :", json.dumps(payload))

        event = payload.get("event", {})
        item_id = event.get("pulseId") or event.get("itemId")
        board_id = event.get("boardId") or settings.MONDAY_BOARD_ID

        if not item_id:
            raise HTTPException(status_code=400, detail="itemId manquant dans l’événement")

        # Déterminer si c’est acompte 1 ou 2 selon la colonne déclenchée
        column_id = event.get("columnId", "")
        link_columns = json.loads(settings.LINK_COLUMN_IDS_JSON)
        formula_columns = json.loads(settings.FORMULA_COLUMN_IDS_JSON)
        status_after_pay = json.loads(settings.STATUS_AFTER_PAY_JSON)

        acompte_num = next((k for k, v in formula_columns.items() if v == column_id), None)
        if not acompte_num:
            raise HTTPException(status_code=400, detail="Colonne déclenchante inconnue")

        # Récupérer les infos client dans Monday
        cols = get_item_columns(
            item_id,
            [
                settings.EMAIL_COLUMN_ID,
                settings.ADDRESS_COLUMN_ID,
                settings.DESCRIPTION_COLUMN_ID,
                settings.IBAN_FORMULA_COLUMN_ID,
                settings.QUOTE_AMOUNT_FORMULA_ID
            ]
        )

        email = cols.get(settings.EMAIL_COLUMN_ID, "")
        address = cols.get(settings.ADDRESS_COLUMN_ID, "")
        description = cols.get(settings.DESCRIPTION_COLUMN_ID, "")
        iban = cols.get(settings.IBAN_FORMULA_COLUMN_ID, "")
        amount = cols.get(settings.QUOTE_AMOUNT_FORMULA_ID, "0")

        if not iban:
            raise HTTPException(status_code=400, detail="IBAN introuvable (formule vide)")

        api_key = _choose_api_key(iban)
        if not api_key:
            raise HTTPException(status_code=400, detail=f"Clé PayPlug manquante pour IBAN {iban}")

        amount_cents = cents_from_str(amount)
        if acompte_num == "2":
            amount_cents //= 2

        metadata = {"item_id": item_id, "acompte": acompte_num, "description": description}
        payment_url = create_payment(api_key, amount_cents, email, address, description, metadata)

        # Enregistrer le lien dans Monday
        set_link_in_column(item_id, link_columns[acompte_num], payment_url, f"Payer acompte {acompte_num}")

        # Mettre à jour le statut
        set_status(item_id, settings.STATUS_COLUMN_ID, status_after_pay[acompte_num])

        print(f"✅ Acompte {acompte_num} créé et lien ajouté : {payment_url}")
        return {"status": "ok", "acompte": acompte_num, "payment_url": payment_url}

    except Exception as e:
        print(f"❌ Erreur webhook Monday : {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Route manuelle de test (comme avant) ---
@app.post("/pay/acompte/{n}")
async def create_acompte_link(n: int):
    try:
        client_name = "Jean Dupont"
        email = "jean.dupont@mail.com"
        address = "12 rue de Paris"
        amount = "1250.00"
        iban = "FR76 1695 8000 0130 5670 5696 366"

        api_key = _choose_api_key(iban)
        amount_cents = cents_from_str(amount) // (2 if n == 2 else 1)

        metadata = {"client": client_name, "acompte": str(n)}
        payment_url = create_payment(api_key, amount_cents, email, address, client_name, metadata)
        return {"status": "ok", "acompte": n, "payment_url": payment_url}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
