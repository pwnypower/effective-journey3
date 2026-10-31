# Changelog

## 2.3.0
- Inkoopfacturen/bonnen uploaden bij uitgaven (PDF, JPG, PNG, TIFF, WEBP), bewaard in `/data/bijlagen`
- Optioneel uitlezen met OCR (tesseract, NL+EN) of PDF-tekstlaag: datum, leverancier, factuurnummer, totaal, btw% en bedrag excl. btw worden voorgevuld
- Nieuwe velden bij uitgaven: factuurnummer en totaal incl. btw (rekent bedrag excl. btw automatisch uit)
- Bijlage bekijken/downloaden/vervangen/verwijderen; 📎-icoon in het uitgavenoverzicht

## 2.2.7
- Fix Word-factuur: factuurregels en btw-regels worden direct via python-docx in de tabel gezet (omzeilt de `{%tr %}`-verwerking van docxtpl)

## 2.2.6
- Fix: `NoneType`-fout bij laden van het Word-template; gesplitste Jinja2-tags worden eerst via python-docx samengevoegd
- Kortere add-on-omschrijving

## 2.2.5
- Fix Word-bijlage: kwetsbare XML-injectie vervangen door het samenvoegen van door Word gesplitste runs vóór het renderen

## 2.2.4
- Alleen versienummer verhoogd

## 2.2.3
- Fix bijlage bij factuurmail: logging, controle of het template bestaat, en in de melding staat of er een PDF- of Word-bijlage is meegestuurd

## 2.2.2
- Factuur als PDF-bijlage: Word-factuur wordt via LibreOffice omgezet naar PDF (valt terug op .docx als dat niet lukt)
- Dockerfile installeert `libreoffice-writer` en `fonts-dejavu-core`
- Regeleinden genormaliseerd

## 2.2.1
- Word-template: tabelrijen voor factuurregels en btw-regels worden vóór het renderen ingevoegd, zodat Word-opmaak de tags niet breekt

## 2.2.0
- Factuur wordt als Word-bijlage meegestuurd met de e-mail
- Optionele persoonlijke tekst bij het versturen van een factuur
- Eigen HTML-mailtemplates voor factuur en herinnering (tabblad MAILTEMPLATES in instellingen)
- Datums in e-mails in Nederlands formaat (dd-mm-jjjj)

## 2.1.22
- Fix: `datetime.date.today()` vervangen door `date.today()`

## 2.1.21
- Lege instellingen worden aangevuld met de HA add-on-configuratie (SMTP, bedrijfsnaam, basis-URL)
- SMTP-wachtwoord, afzender en TLS instelbaar op de instellingenpagina

## 2.1.20
- Versturen en herinnering weer via gewone formulierknoppen
- Fouten bij het opbouwen van de mail worden nu ook als melding getoond

## 2.1.19
- Eigen bevestigingsvenster voor versturen, herinnering, betaallink resetten en verwijderen

## 2.1.17
- Duidelijkere foutmelding bij mislukte e-mail (inclusief fouttype)

## 2.1.16
- Betalingsherinnering per e-mail versturen, met eigen mailtemplate en overzicht van verstuurde herinneringen
- SMTP ondersteunt directe SSL (poort 465) naast STARTTLS

## 2.1.14
- SMTP-instellingen blijven bewaard als velden leeg worden gelaten

## 2.1.13
- Factuur- en betaalbevestigingsmail via aparte HTML-templates
- Mollie OAuth-access-tokens (`access_…`) ondersteund naast API-keys
- mollie-relay.php: IP-whitelist voor Mollie weer actief, schrijven met file-lock

## 2.1.11
- Beveiliging mollie-relay.php: IP-whitelist hersteld met Mollie's volledige IP-reeksen (incl. 34.76.x.x)
- .htaccess toegevoegd: blokkeert directe browser-toegang tot mollie-updates.json en mollie-debug.log
- Debug-logging verwijderd uit relay na succesvolle test

## 2.1.10
- Fix: str_starts_with vervangen door strpos voor PHP 7.x compatibiliteit in mollie-relay.php
- (Teruggedraaid na upgrade naar PHP 8.0 op it-bosch.nl)

## 2.1.9
- RESET LINK knop toegevoegd op factuurpagina: wist bestaande betaallink zodat nieuwe aangemaakt kan worden met correcte webhook-URL
- Fix: betaallinks aangemaakt zonder webhook-URL konden niet worden bijgewerkt

## 2.1.8
- User-Agent header verbeterd voor polls naar it-bosch.nl (minder kans op blokkering)

## 2.1.7
- Toast-meldingen altijd zichtbaar: fallback naar amber als categorie ontbreekt
- Toast-categorieën uitgebreid: info, warning, error toegevoegd

## 2.1.6
- CHECK BETALING toont nu exacte foutmelding: verbindingsfout, HTTP-code, of succesbericht met aantal bijgewerkte facturen
- Polling-functie geeft statusbericht terug in plaats van stil te falen

## 2.1.5
- Fix: CHECK BETALING toont rode melding als Poll URL of token niet ingesteld is

## 2.1.0
- Mollie instellingen volledig uitgebreid: relay URL, bevestigings-URL, poll URL en token
- Redirect na betaling stuurt klant naar it-bosch.nl/betaald/ met nr, klant en bedrag in URL
- Webhook gaat naar mollie-relay.php op it-bosch.nl (geen publieke HA-tunnel nodig)
- Fallback naar interne routes als it-bosch.nl niet is ingesteld
- Mollie API-sleutels (test/live) instelbaar via instellingenpagina

## 2.0.9
- Automatische betaalbevestigingsmail naar klant na ontvangen betaling via Mollie
- Gestylede HTML-mail met regeloverzicht, totalen en bedrijfshuisstijl (amber/zwart)
- Mail wordt verstuurd via eigen SMTP zodra polling een betaalde status detecteert

## 2.0.8
- Mollie statuspolling via PHP-relay op it-bosch.nl (geen publieke HA-tunnel nodig)
- Polling elke 5 minuten via APScheduler, update factuurstatus automatisch naar 'betaald'
- Nieuwe instellingen: Mollie Poll URL en Poll Token
- PHP-bestanden: mollie-relay.php en mollie-status.php (zie zzpboekhouding/php/)

## 2.0.7
- BTW-aangifte wizard per kwartaal (uitklapbaar, met rubriekindeling, checklist en link naar belastingdienst.nl)
- Fix: knoppen op factuurpagina staan nu correct op één rij (display:contents op forms)
- Status-select hoogte gelijk aan knoppen
- Verstuurknop altijd zichtbaar, grijs als SMTP niet geconfigureerd

## 2.0.6
- Fix: dashboard 500-error door verkeerde url_for parameter (`factuur_id` → `fid`)
- Factuuracties (status, versturen, Mollie) visueel consistent gestyled
- Verstuurknop altijd zichtbaar, grijs uitgeschakeld als SMTP niet ingesteld is
- Vaste periodes per regel instelbaar op periodieke schema's

## 2.0.5
- Fix: dashboard url_for fid parameter
- Vaste periodes per regel op periodieke factuurschema's (bijv. domeinnamen 01-03 t/m 28-02)
- Periodefields opgeslagen en doorgegeven bij het aanmaken van periodieke facturen

## 2.0.0
- Volledig nieuw industrieel design (Space Mono + Barlow, amber kleurenschema)
- Donker/licht thema wissel
- Periodieke facturen met APScheduler (dagelijkse cron om 08:00)
- Word-template export via docxtpl met automatisch ingevulde placeholders
- Per-klant betalingstermijn (overschrijft de standaard instelling)
- Vervaldatum snelknoppen (+30d, +60d, +1 jaar, 31-12, einde maand)
- Per-factuurlijn periodes (periode_van / periode_tot)
- Automatische periodeberekening bij periodieke facturen op basis van interval
- Word-template upload/download/reset via instellingen
- Persistent data in /data/ — overleeft add-on updates

## 1.0.0
- Eerste versie: klanten, facturen, uitgaven, BTW-overzicht, jaaroverzicht
