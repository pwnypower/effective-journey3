"""
Leest de Home Assistant add-on opties uit /data/options.json (ingevuld via de
add-on Configuration tab in de HA UI), zet ze als environment variables, en
start daarna de Flask-app. Zo hoeft de app zelf niets van HA-specifieke paden
te weten - dezelfde app.py werkt ook gewoon lokaal met een .env bestand.
"""
import json
import os

OPTIONS_PATH = "/data/options.json"

MAPPING = {
    "bedrijfsnaam": "BEDRIJFSNAAM",
    "kvk_nummer": "KVK_NUMMER",
    "btw_nummer": "BTW_NUMMER",
    "iban": "IBAN",
    "app_base_url": "APP_BASE_URL",
    "mollie_api_key": "MOLLIE_API_KEY",
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_user": "SMTP_USER",
    "smtp_password": "SMTP_PASSWORD",
    "smtp_from": "SMTP_FROM",
    "smtp_use_tls": "SMTP_USE_TLS",
}

if os.path.exists(OPTIONS_PATH):
    with open(OPTIONS_PATH) as f:
        options = json.load(f)
    for option_key, env_key in MAPPING.items():
        if option_key in options and options[option_key] not in (None, ""):
            os.environ[env_key] = str(options[option_key])

# secret_key willekeurig genereren en persistent opslaan in /data, zodat
# ingelogde sessies niet steeds verlopen bij een herstart van de add-on
SECRET_KEY_PATH = "/data/secret_key"
if os.path.exists(SECRET_KEY_PATH):
    with open(SECRET_KEY_PATH) as f:
        os.environ["SECRET_KEY"] = f.read().strip()
else:
    os.environ["SECRET_KEY"] = os.urandom(24).hex()
    with open(SECRET_KEY_PATH, "w") as f:
        f.write(os.environ["SECRET_KEY"])

import app  # noqa: E402  (import moet na het zetten van env vars gebeuren)

app.init_db()
app.app.run(host="0.0.0.0", port=app.PORT, debug=False)
