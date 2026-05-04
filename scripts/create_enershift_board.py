"""
Cree la board Monday "EnerShift - Dossiers CEE (Backup)" :
  - 7 groupes ordonnes
  - 29 colonnes avec types + labels predefinis
  - Affiche board_id + JSON des column_ids a la fin

Usage :
    MONDAY_API_KEY=xxxxx python scripts/create_enershift_board.py [WORKSPACE_ID]
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

MONDAY_URL = "https://api.monday.com/v2"
TOKEN = os.environ.get("MONDAY_API_KEY", "").strip()
if not TOKEN:
    sys.exit("MONDAY_API_KEY manquant.")

WORKSPACE_ID = sys.argv[1] if len(sys.argv) > 1 else None
BOARD_NAME = "EnerShift - Dossiers CEE (Backup)"


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        MONDAY_URL,
        data=body,
        headers={
            "Authorization": TOKEN,
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
    return data["data"]


# =====================================================
# 1) Create board
# =====================================================

print(f"[1/4] Creation board '{BOARD_NAME}'...")
ws_arg = f", workspace_id: {WORKSPACE_ID}" if WORKSPACE_ID else ""
mutation = f"""
mutation {{
  create_board (board_name: "{BOARD_NAME}", board_kind: public{ws_arg}) {{
    id
    name
  }}
}}
"""
res = gql(mutation)
board_id = int(res["create_board"]["id"])
print(f"      board_id = {board_id}")


# =====================================================
# 2) Setup groupes (delete defaults, create 7 in order)
# =====================================================

print("[2/4] Configuration des 7 groupes...")
# List existing default groups
existing = gql(f"query {{ boards(ids:[{board_id}]) {{ groups {{ id title }} }} }}")
default_groups = existing["boards"][0]["groups"]
for g in default_groups:
    try:
        gql(f'mutation {{ delete_group(board_id: {board_id}, group_id: "{g["id"]}") {{ id }} }}')
    except SystemExit:
        # peut echouer pour le dernier groupe (Monday refuse parfois)
        pass

# Cree les 7 groupes dans l'ordre. Position : on insere chacun apres le precedent.
GROUPS = [
    "Brouillons",
    "Paiement attendu",
    "En instruction BE",
    "Controle qualite",
    "A corriger",
    "Valides",
    "Rejetes / Archives",
]
group_ids: dict[str, str] = {}
for i, name in enumerate(GROUPS):
    res = gql(
        'mutation ($b: ID!, $n: String!) { create_group (board_id: $b, group_name: $n) { id title } }',
        {"b": str(board_id), "n": name},
    )
    gid = res["create_group"]["id"]
    group_ids[name] = gid
    print(f"      [{i+1}/7] '{name}' -> {gid}")
    time.sleep(0.2)


# =====================================================
# 3) Create columns
# =====================================================

# Status / dropdown defaults (JSON-stringified)
def status_defaults(labels: list[str]) -> str:
    """Pour status (colors), Monday accepte 'labels': {idx: name}."""
    return json.dumps({"labels": {str(i): lbl for i, lbl in enumerate(labels)}})


def dropdown_defaults(values: list[str]) -> str:
    """Pour dropdown, Monday accepte 'settings': {'labels':[{'id': i, 'name': v}]}."""
    return json.dumps({
        "settings": {"labels": [{"id": i + 1, "name": v} for i, v in enumerate(values)]}
    })


COLUMNS = [
    # (key_interne, titre_FR, type, defaults_JSON_str_or_None)
    ("reference",          "Reference",                    "text",      None),
    ("status",             "Statut",                       "status",    status_defaults([
        "Brouillon", "Soumis", "Paiement en cours", "Paye",
        "En attente BE", "En instruction", "Controle qualite", "Pret a signer",
        "Correction demandee", "Info attendue", "Valide", "Paye delegataire",
        "Rejete", "Archive",
    ])),
    ("fiche_id",           "Type de fiche",                "dropdown",  dropdown_defaults([
        "BAR-TH-104 - PAC air/eau residentielle",
        "BAR-TH-159 - PAC hybride residentielle",
        "BAR-TH-174 - PAC air/eau tertiaire",
        "BAR-TH-175 - PAC geothermique tertiaire",
        "BAR-TH-179 - Regulation chauffage tertiaire",
        "BAT-TH-134 - Recuperateur chaleur fatale",
        "BAT-TH-139 - Calorifugeage tertiaire",
        "BAT-TH-142 - Calepinage isolation toiture",
        "BAT-TH-163 - Isolation murs tertiaires",
        "IND-BA-110 - Isolation batiment industriel",
        "IND-UT-103 - Recuperateur chaleur process",
    ])),
    ("title",              "Titre du dossier",             "text",      None),
    ("installer_email",    "Installateur - Email",         "email",     None),
    ("installer_company",  "Installateur - Societe",       "text",      None),
    ("installer_siret",    "Installateur - SIRET",         "text",      None),
    ("installer_phone",    "Installateur - Telephone",     "phone",     None),
    ("beneficiaire_name",  "Beneficiaire - Raison sociale","text",      None),
    ("beneficiaire_siret", "Beneficiaire - SIRET",         "text",      None),
    ("site_address",       "Beneficiaire - Adresse site",  "long_text", None),
    ("site_city",          "Beneficiaire - Ville",         "text",      None),
    ("site_postal_code",   "Beneficiaire - Code postal",   "text",      None),
    ("climate_zone",       "Zone climatique",              "dropdown",
        dropdown_defaults(["H1", "H2", "H3"])),
    ("prime_eur",          "Prime CEE (EUR)",              "numbers",   None),
    ("kwhc",               "kWhc cumac",                   "numbers",   None),
    ("puissance_kw",       "Puissance (kW)",               "numbers",   None),
    ("created_at",         "Date de creation",             "date",      None),
    ("submitted_at",       "Date de soumission",           "date",      None),
    ("validated_at",       "Date validation BE",           "date",      None),
    ("paid_at",            "Date paiement delegataire",    "date",      None),
    ("realisateur_email",  "Realisateur BE",               "email",     None),
    ("controleur_email",   "Controleur QC",                "email",     None),
    ("payment_status",     "Statut paiement",              "status",    status_defaults([
        "UNPAID", "INVOICED", "PAID", "MANUAL_VERIFIED",
    ])),
    ("credit_status",      "Statut credit",                "status",    status_defaults([
        "PREPAID", "CREDIT_OK", "CREDIT_LIMIT_REACHED", "BLOCKED",
    ])),
    ("enershift_url",      "Lien Enershift",               "link",      None),
    ("nd_pdf_url",         "URL NdD finale (PDF)",         "link",      None),
    ("notes",              "Notes BE / commentaires",      "long_text", None),
    ("snapshot_file",      "Snapshot technique (JSON)",    "file",      None),
]

print(f"[3/4] Creation des {len(COLUMNS)} colonnes...")
column_ids: dict[str, str] = {}
for idx, (key, title, ctype, defaults) in enumerate(COLUMNS, start=1):
    if defaults:
        mutation = """
        mutation ($b: ID!, $t: String!, $ct: ColumnType!, $d: JSON!) {
          create_column (board_id: $b, title: $t, column_type: $ct, defaults: $d) { id title }
        }
        """
        variables = {"b": str(board_id), "t": title, "ct": ctype, "d": defaults}
    else:
        mutation = """
        mutation ($b: ID!, $t: String!, $ct: ColumnType!) {
          create_column (board_id: $b, title: $t, column_type: $ct) { id title }
        }
        """
        variables = {"b": str(board_id), "t": title, "ct": ctype}
    res = gql(mutation, variables)
    cid = res["create_column"]["id"]
    column_ids[key] = cid
    print(f"      [{idx:2}/{len(COLUMNS)}] {key:20} ({ctype:10}) -> {cid}")
    time.sleep(0.15)  # eviter rate-limit


# =====================================================
# 4) Output
# =====================================================

print("\n" + "=" * 70)
print("RESULTAT")
print("=" * 70)
print(f"Board ID : {board_id}")
print(f"Board URL : https://energyz-company.monday.com/boards/{board_id}")
print()
print("Group IDs :")
print(json.dumps(group_ids, indent=2, ensure_ascii=False))
print()
print("Column Mapping (a coller dans MONDAY_COLUMN_MAPPING) :")
print(json.dumps(column_ids, indent=2))
print()
print("Une-ligne pour Supabase :")
print(json.dumps(column_ids))

# Sauvegarde locale aussi
out_path = os.path.join(os.path.dirname(__file__), "enershift_board.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({
        "board_id": board_id,
        "board_url": f"https://energyz-company.monday.com/boards/{board_id}",
        "groups": group_ids,
        "columns": column_ids,
    }, f, indent=2, ensure_ascii=False)
print(f"\nSauvegarde -> {out_path}")
