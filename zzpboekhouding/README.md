# ZZP Boekhouding - Home Assistant Add-on

Dit is dezelfde boekhoud-webapp, verpakt als een Home Assistant add-on zodat hij meedraait
op je HAOS-systeem: automatisch starten, persistente data in `/data`, en beheer via de
normale HA add-on-UI.

## Installeren op HAOS

HAOS heeft geen losse "docker run" optie, maar wel ondersteuning voor **lokale add-ons**.

### Stap 1 - Bestanden op de juiste plek zetten

1. Zorg dat je bij je HA-bestanden kan, bijvoorbeeld via de **Samba** add-on of de
   **SSH & Web Terminal** add-on (Settings → Add-ons → Add-on store, als je deze nog
   niet hebt).
2. Kopieer de map `zzpboekhouding/` (met daarin `config.yaml`, `Dockerfile`, `run.py`
   en de `app/` map) naar de map `/addons/` op je HA-systeem.
   - Via Samba: verbind met `\\<ha-ip>\addons` (Windows) of `smb://<ha-ip>/addons` (Mac),
     en plak de map daar.
   - Via SSH: `scp -r zzpboekhouding root@<ha-ip>:/addons/`

   Resultaat moet zijn: `/addons/zzpboekhouding/config.yaml` etc.

### Stap 2 - Add-on activeren

1. Ga in Home Assistant naar **Instellingen → Add-ons → Add-on store**.
2. Klik rechtsboven op de drie puntjes → **"Check for updates"** (of herlaad de pagina).
   Onderaan verschijnt een sectie **"Local add-ons"** met "ZZP Boekhouding" erin.
3. Klik erop → **Install**. De eerste build duurt een paar minuten (downloaden Python
   image + dependencies installeren).

### Stap 3 - Configureren

1. Ga naar het tabblad **Configuration** van de add-on.
2. Vul in:
   - `bedrijfsnaam`, `kvk_nummer`, `btw_nummer`, `iban`
   - `app_base_url` — zie hieronder, **belangrijk voor Mollie**
   - `mollie_api_key` — je Mollie test- of live-key
   - `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from` — voor het
     versturen van facturen per e-mail
3. Sla op en start de add-on (tabblad **Info** → Start).

## Toegang via Ingress (aanbevolen voor jezelf)

Deze add-on ondersteunt **Ingress**: na installatie verschijnt "ZZP Boekhouding" gewoon als
item in het **linker menu van Home Assistant** (of via Instellingen → Add-ons → de add-on
zelf → het ingress-icoontje naast "OPEN WEB UI"). Je opent de app dan via dezelfde
beveiligde verbinding als de rest van HA — dus ook via **Nabu Casa remote**, als je dat
gebruikt, zonder een los subdomein of poort open te zetten.

Dit is de makkelijkste manier om er **zelf** vanaf je telefoon/laptop bij te kunnen, ook
buiten je eigen netwerk, zonder extra configuratie.

**Belangrijk onderscheid:** Ingress is alleen voor jouw eigen toegang via de HA-login.
Mollie (voor betaallinks/webhooks) en je klanten (als ze een factuurlink in een e-mail
openen) hebben geen HA-account en kunnen dus niet via ingress. Daarvoor blijft de losse
poort + `app_base_url` (reverse proxy/subdomein, zie hieronder) nodig. Je gebruikt dus
beide naast elkaar:
- **Ingress** → voor jezelf, werkt direct na installatie, geen configuratie nodig
- **Poort 5000 + `app_base_url`** → alleen relevant zodra je Mollie-betaallinks of
  e-mails met factuurlinks naar klanten gebruikt

### Stap 4 - Publieke URL regelen (voor Mollie + facturen openen vanaf je telefoon)

Dit is de stap die op een lokale pc lastig was (ngrok nodig) maar nu **makkelijker** is,
omdat je waarschijnlijk al een manier hebt om je HA-instantie van buiten te bereiken
(je gebruikt al `patrijzenhof.biefstukbereiden.nl` voor Home Assistant zelf).

Twee opties:

**A) Via je bestaande reverse proxy (NGINX Proxy Manager, Caddy, Traefik, etc.)**
Als je al een reverse proxy voor je HA-domein hebt, voeg je daar een extra subdomein
of pad toe dat doorverwijst naar de add-on:
- Subdomein-variant: `boekhouding.biefstukbereiden.nl` → `http://<ha-ip>:5000`
- Pad-variant: `patrijzenhof.biefstukbereiden.nl/boekhouding` → `http://<ha-ip>:5000`
  (let op: dan moet de Flask-app weten dat hij achter een sub-pad draait —
  laat het weten als je deze route wilt, dan voeg ik daar ondersteuning voor toe)

Zet de gekozen URL dan in de add-on optie `app_base_url`, bv.
`https://boekhouding.biefstukbereiden.nl`.

**B) Via Nabu Casa Cloud (als je dat gebruikt voor HA)**
Nabu Casa's remote-toegang is gekoppeld aan de HA-frontend zelf en werkt niet direct
voor losse add-on-poorten zonder extra configuratie. Optie A is dan eenvoudiger.

Zonder een publieke `app_base_url` werkt de app verder gewoon **lokaal in je eigen
netwerk** op `http://<ha-ip>:5000` — alleen de Mollie-betaallink/webhook-knoppen blijven
dan uitgeschakeld.

## Data en backups

De SQLite-database staat in de add-on `/data` map, die HA automatisch persistent houdt
(blijft bestaan bij add-on updates/herstarts). Maak via de **Samba**- of **SSH**-add-on
toch af en toe een kopie van `/addons/zzpboekhouding` (configuratie) en de add-on
`/data`-map (database) naar een andere plek — HA-backups dekken add-on data wel mee als
je de standaard HA-backup-functie gebruikt (Instellingen → Systeem → Backups), dus dat
is ook een prima vangnet.

## Verschil met de "lokale pc" versie

Functioneel identiek — dezelfde `app.py`. Het enige verschil is hoe instellingen
binnenkomen: lokaal via een `.env` bestand, hier via de HA add-on Configuration-UI
(die ze automatisch omzet naar dezelfde environment variables).
