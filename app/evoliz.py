def create_client_if_needed(token: str, client_data: dict) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    # 1) Recherche
    r = requests.get(
        _base(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients"),
        headers=headers,
        params={"search": client_data["name"]},
        timeout=getattr(settings, "EVOLIZ_TIMEOUT", 20)
    )
    _raise_for_evoliz(r)
    existing = r.json().get("data", [])
    if existing:
        return existing[0]["clientid"]

    client_type = client_data.get("client_type") or "Particulier"
    vat_number = client_data.get("vat_number")

    # Garde-fou côté serveur avant d'appeler Evoliz
    if client_type == "Professionnel" and not vat_number:
        raise RuntimeError("Client de type Professionnel : 'vat_number' requis.")

    payload = {
        "name": client_data["name"],
        "type": client_type,  # "Particulier" ou "Professionnel"
        "address": {
            "addr": client_data.get("address", "") or "",
            "postcode": client_data.get("postcode", "") or "",
            "town": client_data.get("city", "") or "",
            "iso2": "FR"
        }
    }
    if vat_number:
        payload["vat_number"] = vat_number

    r = requests.post(
        _base(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/clients"),
        headers=headers, json=payload, timeout=getattr(settings, "EVOLIZ_TIMEOUT", 20)
    )
    _raise_for_evoliz(r)
    client_id = r.json().get("clientid")
    if not client_id:
        raise RuntimeError("Création client Evoliz OK mais pas de clientid dans la réponse.")
    return client_id

def create_quote(token: str, client_id: int, quote_data: dict) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    # Par défaut, Evoliz calcule la TVA selon la config du compte.
    # Si tu veux FORCER 20% sur la ligne : ajoute "vat": 20.0 dans la ligne.
    payload = {
        "clientid": client_id,
        "lines": [
            {
                "designation": quote_data["description"],
                "unit_price": quote_data["amount_ht"],
                "quantity": 1,
                # décommente si tu veux forcer 20% :
                # "vat": 20.0
            }
        ],
        "currency": "EUR"
    }
    r = requests.post(
        _base(f"/api/v1/companies/{settings.EVOLIZ_COMPANY_ID}/quotes"),
        headers=headers, json=payload, timeout=getattr(settings, "EVOLIZ_TIMEOUT", 20)
    )
    _raise_for_evoliz(r)
    return r.json()
