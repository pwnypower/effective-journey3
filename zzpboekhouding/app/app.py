import os
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, g
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "boekhouding.db"))
PORT = int(os.environ.get("PORT", "5000"))
MOLLIE_API_KEY = os.environ.get("MOLLIE_API_KEY", "")
BEDRIJFSNAAM = os.environ.get("BEDRIJFSNAAM", "Mijn ZZP Bedrijf")
KVK_NUMMER = os.environ.get("KVK_NUMMER", "")
BTW_NUMMER = os.environ.get("BTW_NUMMER", "")
IBAN = os.environ.get("IBAN", "")

# Publieke basis-URL van de app, nodig voor Mollie webhook + redirect.
# Bij lokaal testen: vul hier je ngrok/Cloudflare Tunnel URL in (zonder trailing slash).
# Bij hosting: vul hier je echte domein in, bv. https://boekhouding.jouwdomein.nl
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

# SMTP instellingen voor het versturen van facturen per e-mail
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS klanten (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naam TEXT NOT NULL,
            contactpersoon TEXT,
            email TEXT,
            adres TEXT,
            postcode TEXT,
            plaats TEXT,
            land TEXT DEFAULT 'Nederland',
            kvk TEXT,
            btw_nummer TEXT
        );

        CREATE TABLE IF NOT EXISTS facturen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factuurnummer TEXT NOT NULL UNIQUE,
            klant_id INTEGER NOT NULL,
            factuurdatum TEXT NOT NULL,
            vervaldatum TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            betaallink TEXT,
            mollie_payment_id TEXT,
            notities TEXT,
            FOREIGN KEY (klant_id) REFERENCES klanten (id)
        );

        CREATE TABLE IF NOT EXISTS factuurregels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factuur_id INTEGER NOT NULL,
            omschrijving TEXT NOT NULL,
            aantal REAL NOT NULL DEFAULT 1,
            prijs_per_stuk REAL NOT NULL,
            btw_percentage REAL NOT NULL DEFAULT 21,
            FOREIGN KEY (factuur_id) REFERENCES facturen (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS uitgaven (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            omschrijving TEXT NOT NULL,
            categorie TEXT,
            bedrag_excl_btw REAL NOT NULL,
            btw_percentage REAL NOT NULL DEFAULT 21,
            zakelijk_percentage REAL NOT NULL DEFAULT 100,
            leverancier TEXT,
            notities TEXT
        );
        """
    )
    db.commit()
    db.close()


# ---------- Helpers ----------

def kwartaal_van_datum(d: date):
    return (d.month - 1) // 3 + 1


def huidig_boekjaar_kwartalen(jaar):
    return [f"{jaar}-Q{q}" for q in range(1, 5)]


def factuur_totalen(regels):
    subtotaal = 0.0
    btw_totaal = 0.0
    for r in regels:
        lijnbedrag = r["aantal"] * r["prijs_per_stuk"]
        subtotaal += lijnbedrag
        btw_totaal += lijnbedrag * (r["btw_percentage"] / 100)
    return round(subtotaal, 2), round(btw_totaal, 2), round(subtotaal + btw_totaal, 2)


def smtp_geconfigureerd():
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def verstuur_email(naar, onderwerp, html_body):
    if not smtp_geconfigureerd():
        raise RuntimeError("SMTP is niet geconfigureerd. Vul SMTP_HOST/SMTP_USER/SMTP_PASSWORD in via .env.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = onderwerp
    msg["From"] = SMTP_FROM
    msg["To"] = naar
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, [naar], msg.as_string())


def maak_mollie_payment(factuur_id, totaal, factuurnummer):
    """Maakt een Mollie payment aan en koppelt 'm aan de factuur. Geeft de checkout_url terug."""
    if not MOLLIE_API_KEY:
        raise RuntimeError("Geen MOLLIE_API_KEY ingesteld in .env.")
    if not APP_BASE_URL:
        raise RuntimeError(
            "Geen APP_BASE_URL ingesteld in .env. Mollie heeft een publiek bereikbare URL nodig "
            "voor de redirect en webhook (bv. via ngrok, Cloudflare Tunnel, of je hosting-domein)."
        )

    from mollie.api.client import Client

    mollie_client = Client()
    mollie_client.set_api_key(MOLLIE_API_KEY)
    payment = mollie_client.payments.create(
        {
            "amount": {"currency": "EUR", "value": f"{totaal:.2f}"},
            "description": f"Factuur {factuurnummer}",
            "redirectUrl": f"{APP_BASE_URL}{url_for('factuur_bekijken', factuur_id=factuur_id)}",
            "webhookUrl": f"{APP_BASE_URL}{url_for('mollie_webhook')}",
            "metadata": {"factuur_id": factuur_id},
        }
    )
    db = get_db()
    db.execute(
        "UPDATE facturen SET betaallink=?, mollie_payment_id=? WHERE id=?",
        (payment.checkout_url, payment.id, factuur_id),
    )
    db.commit()
    return payment.checkout_url


def volgend_factuurnummer(db):
    jaar = datetime.now().year
    row = db.execute(
        "SELECT factuurnummer FROM facturen WHERE factuurnummer LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{jaar}-%",),
    ).fetchone()
    if row:
        try:
            volgnr = int(row["factuurnummer"].split("-")[-1]) + 1
        except ValueError:
            volgnr = 1
    else:
        volgnr = 1
    return f"{jaar}-{volgnr:03d}"


# ---------- Dashboard ----------

@app.route("/")
def dashboard():
    db = get_db()
    jaar = datetime.now().year

    open_facturen = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM( (SELECT SUM(aantal*prijs_per_stuk*(1+btw_percentage/100.0)) FROM factuurregels WHERE factuur_id = facturen.id) ),0) AS bedrag "
        "FROM facturen WHERE status = 'open'"
    ).fetchone()

    vervallen_facturen = db.execute(
        "SELECT COUNT(*) AS n FROM facturen WHERE status='open' AND vervaldatum < ?",
        (date.today().isoformat(),),
    ).fetchone()

    omzet_dit_jaar = db.execute(
        "SELECT COALESCE(SUM(fr.aantal*fr.prijs_per_stuk),0) AS totaal FROM factuurregels fr "
        "JOIN facturen f ON f.id = fr.factuur_id WHERE f.factuurdatum LIKE ? AND f.status != 'concept'",
        (f"{jaar}-%",),
    ).fetchone()["totaal"]

    kosten_dit_jaar = db.execute(
        "SELECT COALESCE(SUM(bedrag_excl_btw * (zakelijk_percentage/100.0)),0) AS totaal FROM uitgaven WHERE datum LIKE ?",
        (f"{jaar}-%",),
    ).fetchone()["totaal"]

    recente_facturen = db.execute(
        "SELECT f.*, k.naam AS klant_naam FROM facturen f JOIN klanten k ON k.id = f.klant_id "
        "ORDER BY f.id DESC LIMIT 5"
    ).fetchall()

    return render_template(
        "dashboard.html",
        open_facturen=open_facturen,
        vervallen_facturen=vervallen_facturen,
        omzet_dit_jaar=round(omzet_dit_jaar, 2),
        kosten_dit_jaar=round(kosten_dit_jaar, 2),
        winst_dit_jaar=round(omzet_dit_jaar - kosten_dit_jaar, 2),
        recente_facturen=recente_facturen,
        jaar=jaar,
        bedrijfsnaam=BEDRIJFSNAAM,
    )


# ---------- Klanten ----------

@app.route("/klanten")
def klanten():
    db = get_db()
    alle_klanten = db.execute("SELECT * FROM klanten ORDER BY naam").fetchall()
    return render_template("klanten.html", klanten=alle_klanten)


@app.route("/klanten/nieuw", methods=["GET", "POST"])
def klant_nieuw():
    if request.method == "POST":
        db = get_db()
        db.execute(
            "INSERT INTO klanten (naam, contactpersoon, email, adres, postcode, plaats, land, kvk, btw_nummer) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                request.form["naam"],
                request.form.get("contactpersoon"),
                request.form.get("email"),
                request.form.get("adres"),
                request.form.get("postcode"),
                request.form.get("plaats"),
                request.form.get("land", "Nederland"),
                request.form.get("kvk"),
                request.form.get("btw_nummer"),
            ),
        )
        db.commit()
        flash("Klant toegevoegd.", "success")
        return redirect(url_for("klanten"))
    return render_template("klant_form.html", klant=None)


@app.route("/klanten/<int:klant_id>/bewerken", methods=["GET", "POST"])
def klant_bewerken(klant_id):
    db = get_db()
    if request.method == "POST":
        db.execute(
            "UPDATE klanten SET naam=?, contactpersoon=?, email=?, adres=?, postcode=?, plaats=?, land=?, kvk=?, btw_nummer=? WHERE id=?",
            (
                request.form["naam"],
                request.form.get("contactpersoon"),
                request.form.get("email"),
                request.form.get("adres"),
                request.form.get("postcode"),
                request.form.get("plaats"),
                request.form.get("land", "Nederland"),
                request.form.get("kvk"),
                request.form.get("btw_nummer"),
                klant_id,
            ),
        )
        db.commit()
        flash("Klant bijgewerkt.", "success")
        return redirect(url_for("klanten"))
    klant = db.execute("SELECT * FROM klanten WHERE id=?", (klant_id,)).fetchone()
    return render_template("klant_form.html", klant=klant)


@app.route("/klanten/<int:klant_id>/verwijderen", methods=["POST"])
def klant_verwijderen(klant_id):
    db = get_db()
    db.execute("DELETE FROM klanten WHERE id=?", (klant_id,))
    db.commit()
    flash("Klant verwijderd.", "success")
    return redirect(url_for("klanten"))


# ---------- Facturen ----------

@app.route("/facturen")
def facturen():
    db = get_db()
    alle_facturen = db.execute(
        "SELECT f.*, k.naam AS klant_naam FROM facturen f JOIN klanten k ON k.id = f.klant_id ORDER BY f.id DESC"
    ).fetchall()
    resultaten = []
    for f in alle_facturen:
        regels = db.execute(
            "SELECT * FROM factuurregels WHERE factuur_id=?", (f["id"],)
        ).fetchall()
        _, _, totaal = factuur_totalen(regels)
        resultaten.append({**dict(f), "totaal": totaal})
    return render_template("facturen.html", facturen=resultaten)


@app.route("/facturen/nieuw", methods=["GET", "POST"])
def factuur_nieuw():
    db = get_db()
    if request.method == "POST":
        factuurnummer = volgend_factuurnummer(db)
        cur = db.execute(
            "INSERT INTO facturen (factuurnummer, klant_id, factuurdatum, vervaldatum, status, notities) "
            "VALUES (?,?,?,?,?,?)",
            (
                factuurnummer,
                request.form["klant_id"],
                request.form["factuurdatum"],
                request.form["vervaldatum"],
                "open",
                request.form.get("notities"),
            ),
        )
        factuur_id = cur.lastrowid

        omschrijvingen = request.form.getlist("omschrijving")
        aantallen = request.form.getlist("aantal")
        prijzen = request.form.getlist("prijs_per_stuk")
        btws = request.form.getlist("btw_percentage")

        for omschr, aantal, prijs, btw in zip(omschrijvingen, aantallen, prijzen, btws):
            if omschr.strip():
                db.execute(
                    "INSERT INTO factuurregels (factuur_id, omschrijving, aantal, prijs_per_stuk, btw_percentage) "
                    "VALUES (?,?,?,?,?)",
                    (factuur_id, omschr, float(aantal), float(prijs), float(btw)),
                )
        db.commit()
        flash(f"Factuur {factuurnummer} aangemaakt.", "success")
        return redirect(url_for("factuur_bekijken", factuur_id=factuur_id))

    klanten_lijst = db.execute("SELECT * FROM klanten ORDER BY naam").fetchall()
    voorgesteld_nummer = volgend_factuurnummer(db)
    return render_template(
        "factuur_form.html",
        klanten=klanten_lijst,
        voorgesteld_nummer=voorgesteld_nummer,
        vandaag=date.today().isoformat(),
    )


@app.route("/facturen/<int:factuur_id>")
def factuur_bekijken(factuur_id):
    db = get_db()
    factuur = db.execute(
        "SELECT f.*, k.* , f.id as factuur_id FROM facturen f JOIN klanten k ON k.id = f.klant_id WHERE f.id=?",
        (factuur_id,),
    ).fetchone()
    regels = db.execute(
        "SELECT * FROM factuurregels WHERE factuur_id=?", (factuur_id,)
    ).fetchall()
    subtotaal, btw_totaal, totaal = factuur_totalen(regels)
    return render_template(
        "factuur_view.html",
        factuur=factuur,
        regels=regels,
        subtotaal=subtotaal,
        btw_totaal=btw_totaal,
        totaal=totaal,
        bedrijfsnaam=BEDRIJFSNAAM,
        kvk_nummer=KVK_NUMMER,
        btw_nummer=BTW_NUMMER,
        iban=IBAN,
        mollie_actief=bool(MOLLIE_API_KEY and APP_BASE_URL),
        smtp_actief=smtp_geconfigureerd(),
    )


@app.route("/facturen/<int:factuur_id>/status", methods=["POST"])
def factuur_status(factuur_id):
    db = get_db()
    db.execute(
        "UPDATE facturen SET status=? WHERE id=?", (request.form["status"], factuur_id)
    )
    db.commit()
    flash("Status bijgewerkt.", "success")
    return redirect(url_for("factuur_bekijken", factuur_id=factuur_id))


@app.route("/facturen/<int:factuur_id>/mollie-betaallink", methods=["POST"])
def factuur_mollie_betaallink(factuur_id):
    db = get_db()
    regels = db.execute("SELECT * FROM factuurregels WHERE factuur_id=?", (factuur_id,)).fetchall()
    factuur = db.execute("SELECT * FROM facturen WHERE id=?", (factuur_id,)).fetchone()
    _, _, totaal = factuur_totalen(regels)

    try:
        maak_mollie_payment(factuur_id, totaal, factuur["factuurnummer"])
        flash("Mollie betaallink aangemaakt.", "success")
    except Exception as e:
        flash(f"Mollie-fout: {e}", "danger")

    return redirect(url_for("factuur_bekijken", factuur_id=factuur_id))


@app.route("/facturen/<int:factuur_id>/versturen", methods=["POST"])
def factuur_versturen(factuur_id):
    """Verstuurt de factuur per e-mail naar de klant, met (indien geconfigureerd) een Mollie-betaallink."""
    db = get_db()
    factuur = db.execute(
        "SELECT f.*, k.naam AS klant_naam, k.email AS klant_email FROM facturen f "
        "JOIN klanten k ON k.id = f.klant_id WHERE f.id=?",
        (factuur_id,),
    ).fetchone()
    regels = db.execute("SELECT * FROM factuurregels WHERE factuur_id=?", (factuur_id,)).fetchall()
    subtotaal, btw_totaal, totaal = factuur_totalen(regels)

    if not factuur["klant_email"]:
        flash("Deze klant heeft geen e-mailadres. Vul dit eerst aan bij de klantgegevens.", "danger")
        return redirect(url_for("factuur_bekijken", factuur_id=factuur_id))

    betaallink = factuur["betaallink"]
    if not betaallink and MOLLIE_API_KEY and APP_BASE_URL:
        try:
            betaallink = maak_mollie_payment(factuur_id, totaal, factuur["factuurnummer"])
        except Exception as e:
            flash(f"Mollie-betaallink kon niet aangemaakt worden, factuur wordt zonder verstuurd: {e}", "danger")

    regels_html = "".join(
        f"<tr><td>{r['omschrijving']}</td><td>{r['aantal']}</td>"
        f"<td>&euro; {r['prijs_per_stuk']:.2f}</td><td>&euro; {r['aantal']*r['prijs_per_stuk']:.2f}</td></tr>"
        for r in regels
    )
    betaal_html = (
        f"<p><a href='{betaallink}'>Klik hier om direct online te betalen</a></p>" if betaallink else ""
    )
    html_body = f"""
    <p>Beste {factuur['klant_naam']},</p>
    <p>Hierbij ontvang je factuur <strong>{factuur['factuurnummer']}</strong>
    van {BEDRIJFSNAAM}, met vervaldatum {factuur['vervaldatum']}.</p>
    <table border="1" cellpadding="6" cellspacing="0">
        <tr><th>Omschrijving</th><th>Aantal</th><th>Prijs p/s</th><th>Bedrag excl.</th></tr>
        {regels_html}
    </table>
    <p>Subtotaal excl. BTW: &euro; {subtotaal:.2f}<br>
    BTW: &euro; {btw_totaal:.2f}<br>
    <strong>Totaal: &euro; {totaal:.2f}</strong></p>
    {betaal_html}
    <p>Met vriendelijke groet,<br>{BEDRIJFSNAAM}</p>
    """

    try:
        verstuur_email(factuur["klant_email"], f"Factuur {factuur['factuurnummer']}", html_body)
        db.execute("UPDATE facturen SET status='open' WHERE id=? AND status='concept'", (factuur_id,))
        db.commit()
        flash(f"Factuur verstuurd naar {factuur['klant_email']}.", "success")
    except Exception as e:
        flash(f"E-mail versturen mislukt: {e}", "danger")

    return redirect(url_for("factuur_bekijken", factuur_id=factuur_id))


@app.route("/mollie/webhook", methods=["POST"])
def mollie_webhook():
    """
    Mollie webhook endpoint. Mollie stuurt hier alleen een payment id naartoe (geen statusdata) -
    we vragen de status altijd opnieuw zelf op bij Mollie, nooit vertrouwen op de payload zelf.
    Let op: deze URL moet publiek bereikbaar zijn (zie APP_BASE_URL in .env / ngrok / hosting).
    """
    payment_id = request.form.get("id")
    if not payment_id or not MOLLIE_API_KEY:
        return "", 400

    from mollie.api.client import Client

    mollie_client = Client()
    mollie_client.set_api_key(MOLLIE_API_KEY)

    try:
        payment = mollie_client.payments.get(payment_id)
    except Exception:
        return "", 404

    factuur_id = (payment.metadata or {}).get("factuur_id")
    if not factuur_id:
        return "", 200

    db = get_db()
    if payment.is_paid():
        db.execute("UPDATE facturen SET status='betaald' WHERE id=?", (factuur_id,))
    elif payment.is_expired() or payment.is_canceled() or payment.is_failed():
        db.execute("UPDATE facturen SET status='vervallen' WHERE id=?", (factuur_id,))
    db.commit()
    return "", 200


@app.route("/facturen/<int:factuur_id>/verwijderen", methods=["POST"])
def factuur_verwijderen(factuur_id):
    db = get_db()
    db.execute("DELETE FROM facturen WHERE id=?", (factuur_id,))
    db.commit()
    flash("Factuur verwijderd.", "success")
    return redirect(url_for("facturen"))


# ---------- Uitgaven ----------

@app.route("/uitgaven")
def uitgaven():
    db = get_db()
    alle_uitgaven = db.execute("SELECT * FROM uitgaven ORDER BY datum DESC").fetchall()
    return render_template("uitgaven.html", uitgaven=alle_uitgaven)


@app.route("/uitgaven/nieuw", methods=["GET", "POST"])
def uitgave_nieuw():
    if request.method == "POST":
        db = get_db()
        db.execute(
            "INSERT INTO uitgaven (datum, omschrijving, categorie, bedrag_excl_btw, btw_percentage, zakelijk_percentage, leverancier, notities) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                request.form["datum"],
                request.form["omschrijving"],
                request.form.get("categorie"),
                float(request.form["bedrag_excl_btw"]),
                float(request.form.get("btw_percentage", 21)),
                float(request.form.get("zakelijk_percentage", 100)),
                request.form.get("leverancier"),
                request.form.get("notities"),
            ),
        )
        db.commit()
        flash("Uitgave toegevoegd.", "success")
        return redirect(url_for("uitgaven"))
    return render_template("uitgave_form.html", vandaag=date.today().isoformat())


@app.route("/uitgaven/<int:uitgave_id>/verwijderen", methods=["POST"])
def uitgave_verwijderen(uitgave_id):
    db = get_db()
    db.execute("DELETE FROM uitgaven WHERE id=?", (uitgave_id,))
    db.commit()
    flash("Uitgave verwijderd.", "success")
    return redirect(url_for("uitgaven"))


# ---------- BTW overzicht ----------

@app.route("/btw")
def btw_overzicht():
    db = get_db()
    jaar = int(request.args.get("jaar", datetime.now().year))

    kwartalen_data = []
    for q in range(1, 5):
        start_maand = (q - 1) * 3 + 1
        eind_maand = start_maand + 2
        start = f"{jaar}-{start_maand:02d}-01"
        eind = f"{jaar}-{eind_maand:02d}-31"

        btw_verschuldigd = db.execute(
            "SELECT COALESCE(SUM(fr.aantal*fr.prijs_per_stuk*fr.btw_percentage/100.0),0) AS totaal "
            "FROM factuurregels fr JOIN facturen f ON f.id = fr.factuur_id "
            "WHERE f.factuurdatum BETWEEN ? AND ? AND f.status != 'concept'",
            (start, eind),
        ).fetchone()["totaal"]

        omzet_excl = db.execute(
            "SELECT COALESCE(SUM(fr.aantal*fr.prijs_per_stuk),0) AS totaal "
            "FROM factuurregels fr JOIN facturen f ON f.id = fr.factuur_id "
            "WHERE f.factuurdatum BETWEEN ? AND ? AND f.status != 'concept'",
            (start, eind),
        ).fetchone()["totaal"]

        btw_voorbelasting = db.execute(
            "SELECT COALESCE(SUM(bedrag_excl_btw * btw_percentage/100.0 * (zakelijk_percentage/100.0)),0) AS totaal "
            "FROM uitgaven WHERE datum BETWEEN ? AND ?",
            (start, eind),
        ).fetchone()["totaal"]

        kosten_excl = db.execute(
            "SELECT COALESCE(SUM(bedrag_excl_btw * (zakelijk_percentage/100.0)),0) AS totaal "
            "FROM uitgaven WHERE datum BETWEEN ? AND ?",
            (start, eind),
        ).fetchone()["totaal"]

        kwartalen_data.append(
            {
                "kwartaal": q,
                "omzet_excl": round(omzet_excl, 2),
                "kosten_excl": round(kosten_excl, 2),
                "btw_verschuldigd": round(btw_verschuldigd, 2),
                "btw_voorbelasting": round(btw_voorbelasting, 2),
                "btw_te_betalen": round(btw_verschuldigd - btw_voorbelasting, 2),
            }
        )

    return render_template("btw.html", kwartalen=kwartalen_data, jaar=jaar)


# ---------- Jaaroverzicht / aangifte-hulp ----------

@app.route("/jaaroverzicht")
def jaaroverzicht():
    db = get_db()
    jaar = int(request.args.get("jaar", datetime.now().year))

    omzet = db.execute(
        "SELECT COALESCE(SUM(fr.aantal*fr.prijs_per_stuk),0) AS totaal FROM factuurregels fr "
        "JOIN facturen f ON f.id = fr.factuur_id WHERE f.factuurdatum LIKE ? AND f.status != 'concept'",
        (f"{jaar}-%",),
    ).fetchone()["totaal"]

    kosten_per_categorie = db.execute(
        "SELECT COALESCE(categorie,'Overig') AS categorie, "
        "COALESCE(SUM(bedrag_excl_btw*(zakelijk_percentage/100.0)),0) AS totaal "
        "FROM uitgaven WHERE datum LIKE ? GROUP BY categorie ORDER BY totaal DESC",
        (f"{jaar}-%",),
    ).fetchall()

    totale_kosten = sum(r["totaal"] for r in kosten_per_categorie)
    winst_voor_aftrek = round(omzet - totale_kosten, 2)

    return render_template(
        "jaaroverzicht.html",
        jaar=jaar,
        omzet=round(omzet, 2),
        kosten_per_categorie=kosten_per_categorie,
        totale_kosten=round(totale_kosten, 2),
        winst_voor_aftrek=winst_voor_aftrek,
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true", port=PORT)
