# Changelog

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
