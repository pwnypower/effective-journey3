"""
Opstartscript voor zowel Home Assistant add-on als lokaal gebruik.

- Home Assistant: leest opties uit /data/options.json en bewaart de secret key
  in /data/secret_key zodat sessies overleven bij herstart.
- Lokaal / Docker Compose: leest .env via python-dotenv (gedaan door app.py zelf),
  genereert een secret key als die niet in de omgeving staat.
"""
import json
import os
import secrets

# ── Home Assistant opties ────────────────────────────────────────────────────
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

# ── Secret key ───────────────────────────────────────────────────────────────
SECRET_KEY_PATH = "/data/secret_key"

if not os.environ.get("SECRET_KEY"):
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH) as f:
            os.environ["SECRET_KEY"] = f.read().strip()
    else:
        key = secrets.token_hex(24)
        os.environ["SECRET_KEY"] = key
        data_dir = os.path.dirname(SECRET_KEY_PATH)
        if os.path.isdir(data_dir):
            with open(SECRET_KEY_PATH, "w") as f:
                f.write(key)

# ── Start app ────────────────────────────────────────────────────────────────
import app as application  # noqa: E402

application.init_db()
application.app.run(
    host="0.0.0.0",
    port=application.PORT,
    debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
)
