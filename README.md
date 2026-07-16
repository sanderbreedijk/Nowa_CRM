# NOWA CRM

Nieuwe modulaire basis voor klantenbeheer, offertes, beveiligde klantcredentials en toekomstige mail- en Coligo-integraties.

## Ontwikkelstart

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\nowa-crm
```

Klantdata staat buiten de programmamap onder `%LOCALAPPDATA%\NOWA\CRM`. Zet `NOWA_DATA_DIR` om voor test- of netwerkprofielen.

## Grenzen

- `modules/customers`: gedeelde klantidentiteit en contacten.
- `modules/vault`: versleutelde gegevens met verplichte reden en auditregistratie.
- `integrations`: contracten voor mail en telefonie; Coligo-adapter is voorbereid.
- `ui`: presentatie zonder databasequeries of externe API-logica.

De oude NOWA-database wordt niet rechtstreeks geopend. Een aparte migratietool volgt, zodat brondata intact blijft en iedere conversie controleerbaar is.

## Veilige updates

De database heeft genummerde migraties. Zodra een nieuwe applicatieversie een databasewijziging nodig heeft, maakt NOWA CRM eerst automatisch een consistente back-up in `backups/`. De releasebouw controleert bovendien dat geen database of `vault.key` in het programmapakket terechtkomt.
