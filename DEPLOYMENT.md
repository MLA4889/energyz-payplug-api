# Deploiement - Energyz Payment Automation v3

## Prerequis

- [ ] Compte Render existant avec le service `energyz-payplug-api`
- [ ] **Payplug `sk_live_` revoquee et regeneree** (ancienne clef leakee)
- [ ] **Token Monday revoque et regenere** (idem)
- [ ] Acces Evoliz (public_key + secret_key pour le compte entreprise)

## Etapes

### 1. Mettre a jour le code sur GitHub

Depuis ta machine, dans le dossier `energyz-payplug-api-main/` :

```bash
git init
git add .
git commit -m "v3: page de facturation partenaire + Evoliz + upload PDF Monday"
git remote add origin https://github.com/MLA4889/energyz-payplug-api.git
git branch -M main
git push -u origin main --force   # ATTENTION : ecrase l'historique
```

Alternative plus douce : creer une branche `v3` et merger plus tard.

### 2. Ajouter un disque persistant sur Render

Le token store est un fichier JSON : il faut un disque qui survit aux redeploiements.

Render Dashboard -> service -> **Disks** :
- Name : `data`
- Mount path : `/var/data`
- Size : 1 GB (largement suffisant)

### 3. Variables d'environnement Render

Onglet **Environment**. **NE PAS** coller les secrets ici ailleurs que dans ce panneau.

| Variable | Valeur |
|---|---|
| `MONDAY_API_KEY` | *nouveau token* (Monday -> Avatar -> Developers) |
| `MONDAY_BOARD_ID` | `2047255654` |
| `TRIGGER_STATUS_COLUMN_ID` | `color_mkwwes91` |
| `TRIGGER_LABELS_JSON` | `{"1":"Generer acompte 1"}` |
| `IBAN_FORMULA_COLUMN_ID` | `formula_mkwwg0fh` |
| `QUOTE_AMOUNT_FORMULA_ID` | `numeric_mkxahyjf` |
| `FORMULA_COLUMN_IDS_JSON` | `{"1":"formula_mkwwcfeb","2":"formula_mkwwdes0"}` |
| `PAYMENT_LINK_COLUMN_ID` | `link_mkww3qd4` |
| `LINK_COLUMN_IDS_JSON` | `{"1":"link_mkww3qd4","2":"link_mkwwcj3m"}` |
| `ADDRESS_COLUMN_ID` | `lieu_mkmmfwfs` |
| `DESCRIPTION_COLUMN_ID` | `long_texte_mkmm908x` |
| `BUSINESS_STATUS_COLUMN_ID` | `color_mkwwrssx` |
| `CLIENT_TYPE_COLUMN_ID` | `color_mkwwys33` |
| `SIRET_SITE_COLUMN_ID` | `texte_mkmmc5s0` |
| `STATUS_COLUMN_ID` | `color_mkwwwmdg` |
| `STATUS_LABEL_PAID` | `Paye` |
| `STATUS_LABEL_INVOICED` | `Facture` |
| `STATUS_LABEL_ERROR` | `Bloque` |
| `INVOICE_PDF_COLUMN_ID` | `file_mm2pmbe3` |
| `INVOICE_NUMBER_COLUMN_ID` | `text_mkyrbp0y` |
| `INVOICE_DATE_COLUMN_ID` | `date_mm06amfy` |
| `BILLING_SIRET_COLUMN_ID` | `text_mm2pkwx3` |
| `BILLING_EMAIL_COLUMN_ID` | `text_mm2p5e9` |
| `BILLING_LEGAL_NAME_COLUMN_ID` | `text_mm2pkbyn` |
| `PAYPLUG_MODE` | `live` (ou `test` pour les essais) |
| `PAYPLUG_KEYS_LIVE_JSON` | `{"FR76 1695 8000 0100 0571 1982 492":"sk_live_NOUVELLE_CLE"}` |
| `PAYPLUG_KEYS_TEST_JSON` | `{"FR76 1695 8000 0100 0571 1982 492":"sk_test_..."}` |
| `PAYPLUG_WEBHOOK_SECRET` | *a generer dans le dashboard Payplug webhook* |
| `FORCE_IBAN` | `FR76 1695 8000 0100 0571 1982 492` |
| `EVOLIZ_BASE_URL` | `https://www.evoliz.io` |
| `EVOLIZ_COMPANY_ID` | *id de ta company Evoliz* |
| `EVOLIZ_PUBLIC_KEY` | *public key Evoliz* |
| `EVOLIZ_SECRET_KEY` | *secret key Evoliz* |
| `PUBLIC_BASE_URL` | `https://energyz-payplug-api.onrender.com` (ou ton domaine custom) |
| `DEFAULT_VAT_RATE` | `20.0` |
| `DEFAULT_PRESTATION_LABEL` | `Note de dimensionnement - Destratificateur d'air` |
| `TOKEN_TTL_DAYS` | `30` |
| `TOKEN_STORE_PATH` | `/var/data/token_store.json` |

### 4. Webhook Payplug

Dashboard Payplug -> **Webhooks** -> Ajouter :
- URL : `https://<ton-service>.onrender.com/payplug/webhook`
- Evenements : au moins `payment.succeeded`
- Secret : copier dans `PAYPLUG_WEBHOOK_SECRET`

### 5. Webhook Monday (inchange)

Deja en place. Il pointe sur `/quote/from_monday`. La seule difference :
l'endpoint ecrit desormais une URL `/p/{token}` au lieu d'une URL Payplug directe.

### 6. Test end-to-end (mode test)

1. Passer `PAYPLUG_MODE=test` et utiliser une cle `sk_test_...`
2. Sur le board Monday destrat, creer un item test avec :
   - Prix total EUR HT = 1.00 (la formule Montant acompte 1 renverra 1.20)
3. Passer le statut "Generation liens paiement" = **Generer acompte 1**
4. Verifier que la colonne "Lien Acompte 1" contient une URL `/p/<uuid>`
5. Cliquer, saisir un SIRET valide (ex : 73282932000074), email test
6. Carte de test Payplug : `4000 0000 0000 0077` / date future / CVV 123
7. Verifier dans Evoliz : client cree, facture emise, statut "Payee"
8. Verifier sur Monday : PDF dans "Facture PDF Partenaire", N° Facture rempli, statut "Facture"
9. Rejouer le webhook depuis le dashboard Payplug -> aucune 2e facture (idempotence OK)

### 7. Bascule en live

- `PAYPLUG_MODE=live`
- Redeployer (ou manually "Save, Rebuild & Deploy")

## Monitoring

- Logs Render : onglet Logs du service, filtrer par token ou payment_id
- Format des logs : JSON structure, champ `event` pour filtrer
- Tokens : examiner `/var/data/token_store.json` via le Shell Render si besoin

## Rollback

Si probleme detecte :
- Repasser `PAYPLUG_MODE=test` pour stopper les paiements live
- Sur Monday, temporairement desactiver le webhook /quote/from_monday
- Le code de la v2.1 reste disponible dans le commit precedent -> `git checkout <ancien-commit>` -> redeploy
