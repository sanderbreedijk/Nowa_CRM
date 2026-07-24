# NOWA CRM op meerdere werkplekken

Gebruik één vaste Windows-computer als centrale server. Plaats `nowa.sqlite3` nooit
zelf in een gedeelde map en open het bestand nooit vanaf meerdere computers.

## Servercomputer

1. Werk NOWA CRM bij naar minimaal versie 3.37.0.

## Synology PostgreSQL (aanbevolen)

Gebruik PostgreSQL 17 met de containerpoort `5432`. Een afwijkende NAS-poort, zoals
`55432`, vult u in NOWA CRM in. Ga naar **Systeem > Multi-user**, vul het NAS-adres,
poort, database, gebruiker en wachtwoord in en kies achtereenvolgens:

1. **Opslaan & testen**
2. **Gegevens veilig overzetten**
3. **PostgreSQL activeren**

NOWA CRM maakt vooraf een lokale SQLite-herstelkopie, zet alle tabellen over en
vergelijkt de aantallen. Bij een verschil blijft de lokale database actief.
Het PostgreSQL-wachtwoord wordt alleen lokaal versleuteld opgeslagen en komt nooit
in GitHub terecht. Stel poort 55432 uitsluitend beschikbaar op het lokale netwerk
of via VPN.
2. Open **Systeem > Multi-user**.
3. Vul de computernaam of het vaste IP-adres en poort `5088` in.
4. Kies een lange, unieke toegangssleutel.
5. Vink **Deze computer is de centrale server** aan.
6. Sla op en kies **Server starten**.
7. Sta poort 5088 uitsluitend toe binnen het vertrouwde bedrijfsnetwerk.

Laat NOWA CRM op deze computer actief. Bij volgende starts wordt de centrale
databaseservice automatisch gestart.

## Extra werkplek

1. Installeer dezelfde NOWA CRM-versie.
2. Vul bij **Systeem > Multi-user** dezelfde servernaam, poort en toegangssleutel in.
3. Test de verbinding.
4. Kies **Deze werkplek centraal zetten** en start NOWA CRM opnieuw.
5. Meld aan met het persoonlijke account dat op de server is aangemaakt.

## Bestaande gegevens overzetten

Gebruik **Lokale gegevens naar server** alleen vanaf de computer waarop de actuele
klantgegevens staan. Sluit eerst alle andere werkplekken. NOWA CRM maakt vooraf
automatisch een lokale herstelkopie.

Databaseverkeer, wachtwoordvelden en de centrale kluissleutel worden vóór transport
versleuteld. Klantdata, databases en sleutels worden nooit via GitHub verspreid.
