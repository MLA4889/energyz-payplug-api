"""
Script idempotent qui :
1) Liste les colonnes actuelles du board Destratificateurs
2) Crée les colonnes manquantes pour la facturation partenaire
3) Génère scripts/monday_config.json avec la map complète des IDs à utiliser
   dans les variables d'environnement Render.

Usage:
    MONDAY_API_KEY=xxxx python scripts/create_monday_columns.py

Le token doit avoir les droits write.
"""
import json
import os
import sys
from pathlib import Path
import urllib.request
import urllib.error

BOARD_ID = 2047255654
MONDAY_URL = "https://api.monday.com/v2"

# Colonnes à créer si absentes. Le matching se fait sur title (case-insensitive).
COLUMNS_TO_CREATE = [
    {"title": "Facture PDF Partenaire", "column_type": "file"},
    {"title": "SIRET facturation",      "column_type": "text"},
    {"title": "Email facturation",      "column_type": "text"},
    {"title": "Raison sociale facturation", "column_type": "text"},
]


def gql(query: str, variables: dict | None = None, token: str = "") -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        MONDAY_URL,
        data=body,
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
            "API-Version": "2024-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {e.reason}: {e.read().decode()}")
    if "errors" in data and data["errors"]:
        sys.exit(f"GraphQL errors: {json.dumps(data['errors'], indent=2, ensure_ascii=False)}")
    return data


def list_columns(token: str) -> list[dict]:
    query = """
    query ($b: [ID!]) {
      boards (ids: $b) {
        id name
        columns { id title type }
      }
    }
    """
    data = gql(query, {"b": [str(BOARD_ID)]}, token)
    return data["data"]["boards"][0]["columns"]


def create_column(title: str, column_type: str, token: str) -> dict:
    mutation = """
    mutation ($b: ID!, $t: String!, $ct: ColumnType!) {
      create_column (board_id: $b, title: $t, column_type: $ct) {
        id title type
      }
    }
    """
    data = gql(mutation, {"b": str(BOARD_ID), "t": title, "ct": column_type}, token)
    return data["data"]["create_column"]


def main() -> None:
    token = os.environ.get("MONDAY_API_KEY", "").strip()
    if not token:
        sys.exit("Erreur: MONDAY_API_KEY manquant dans l'environnement.")

    print(f"[1/3] Inspection du board {BOARD_ID}...")
    existing = list_columns(token)
    existing_titles_lower = {c["title"].strip().lower(): c for c in existing}
    print(f"      {len(existing)} colonnes existantes trouvees.")

    print("[2/3] Creation des colonnes manquantes...")
    created: list[dict] = []
    reused: list[dict] = []
    for spec in COLUMNS_TO_CREATE:
        key = spec["title"].strip().lower()
        if key in existing_titles_lower:
            col = existing_titles_lower[key]
            print(f"      [SKIP] Deja present: '{col['title']}' -> {col['id']}")
            reused.append({"title": col["title"], "id": col["id"], "type": col["type"]})
            continue
        new_col = create_column(spec["title"], spec["column_type"], token)
        print(f"      [NEW]  Cree: '{new_col['title']}' -> {new_col['id']} ({new_col['type']})")
        created.append(new_col)

    print("[3/3] Generation de scripts/monday_config.json...")
    # Re-liste apres creation pour avoir une source de verite unique
    all_cols = list_columns(token)
    by_title = {c["title"].strip().lower(): c for c in all_cols}

    def col_id(title: str) -> str | None:
        c = by_title.get(title.strip().lower())
        return c["id"] if c else None

    config = {
        "board_id": BOARD_ID,
        "board_name": gql('query ($b: [ID!]) { boards (ids: $b) { name } }',
                          {"b": [str(BOARD_ID)]}, token)["data"]["boards"][0]["name"],
        "columns": {
            # Colonnes existantes deja utilisees par le code actuel
            "SIRET":                   col_id("SIRET"),
            "ADDRESS_SITE":            col_id("Adresse du site"),
            "COMMENTS":                col_id("Commentaires ↘️"),
            "AMOUNT_FORMULA_TOTAL":    "numeric_mkxahyjf",  # Prix total EUR HT
            "AMOUNT_FORMULA_ACOMPTE1": col_id("Montant acompte 1"),
            "AMOUNT_FORMULA_ACOMPTE2": col_id("Montant acompte 2"),
            "IBAN_FORMULA":            col_id("IBAN"),
            "LINK_ACOMPTE1":           col_id("Lien Acompte 1 ↗️"),
            "LINK_ACOMPTE2":           col_id("Lien Acompte 2"),
            "TRIGGER_GENERATION":      col_id("Génération liens paiement"),
            "STATUS_PAYMENT":          col_id("Statut paiement ↗️"),
            "BUSINESS_LINE":           col_id("Business Line"),
            "CLIENT_TYPE":             col_id("Type client"),
            "INVOICE_NUMBER":          col_id("N° Facture"),
            "INVOICE_DATE":            col_id("Date facturation"),

            # Nouvelles colonnes pour la facturation partenaire
            "INVOICE_PDF":             col_id("Facture PDF Partenaire"),
            "BILLING_SIRET":           col_id("SIRET facturation"),
            "BILLING_EMAIL":           col_id("Email facturation"),
            "BILLING_LEGAL_NAME":      col_id("Raison sociale facturation"),
        },
        "created_now": created,
        "reused": reused,
    }

    out_path = Path(__file__).parent / "monday_config.json"
    out_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"      OK -> {out_path}")

    missing = [k for k, v in config["columns"].items() if v is None]
    if missing:
        print(f"\n[WARN] Colonnes introuvables dans Monday : {missing}")
        print("       Verifier les titres dans le board ou adapter le script.")
        sys.exit(1)

    print("\nTous les IDs necessaires sont disponibles.")


if __name__ == "__main__":
    main()
