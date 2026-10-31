"""
OCR en herkenning van (inkoop)facturen.

- Lezen: PDF met tekstlaag via `pdftotext -bbox-layout`, gescande PDF via
  `pdftoppm` + `tesseract`, afbeeldingen direct via `tesseract`. Alleen externe
  command-line tools (poppler-utils + tesseract-ocr), geen extra Python-dependencies.
- Elk woord krijgt een positie (genormaliseerd 0..1 per pagina) en een rij-nummer,
  zodat de gebruiker woorden op de factuur kan aanklikken ("taggen") en de app per
  leverancier kan leren waar velden staan (zie leren.py).
- Herkennen: heuristieken voor datum, leverancier, factuurnummer, totaal,
  btw-bedrag, btw-percentage, bedrag excl. btw en factuurregels (NL + EN).
"""
import base64
import functools
import html
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date

PDF_EXT = {".pdf"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif"}
TOEGESTANE_EXT = PDF_EXT | IMG_EXT

OCR_TALEN = os.environ.get("OCR_LANG", "nld+eng")
MAX_PAGINAS = 3
_TIMEOUT = 120


def ocr_beschikbaar() -> bool:
    return shutil.which("tesseract") is not None


def pdf_beschikbaar() -> bool:
    return shutil.which("pdftotext") is not None


def _run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)
    return res.stdout.decode("utf-8", errors="replace")


@functools.lru_cache(maxsize=1)
def _talen() -> str:
    """Gebruik alleen talen die tesseract daadwerkelijk heeft geïnstalleerd."""
    try:
        out = _run(["tesseract", "--list-langs"])
        beschikbaar = {l.strip() for l in out.splitlines()[1:] if l.strip()}
    except Exception:
        return "eng"
    gewenst = [t for t in OCR_TALEN.split("+") if t in beschikbaar]
    return "+".join(gewenst) or "eng"


# ─── Woorden met posities ─────────────────────────────────────────────────────

def _tesseract_woorden(pad: str) -> tuple[list[dict], float, float]:
    """Woorden uit een afbeelding via tesseract TSV. Coördinaten genormaliseerd."""
    out = _run(["tesseract", pad, "stdout", "-l", _talen(), "--psm", "4", "tsv"])
    breedte = hoogte = 0.0
    ruw = []
    for regel in out.splitlines()[1:]:
        k = regel.split("\t")
        if len(k) < 12:
            continue
        if k[0] == "1":
            breedte, hoogte = float(k[8]), float(k[9])
        elif k[0] == "5" and k[11].strip():
            ruw.append((float(k[6]), float(k[7]), float(k[8]), float(k[9]), k[11].strip()))
    if not breedte or not hoogte:
        return [], 0, 0
    woorden = [{"t": t, "x": x / breedte, "y": y / hoogte, "w": w / breedte, "h": h / hoogte}
               for x, y, w, h, t in ruw]
    return woorden, breedte, hoogte


def _pdf_woorden(pad: str) -> list[dict]:
    """Per pagina een lijst woorden uit de tekstlaag van een PDF."""
    out = _run(["pdftotext", "-bbox-layout", "-l", str(MAX_PAGINAS), pad, "-"])
    paginas = []
    for pm in re.finditer(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', out, re.S):
        pw, ph = float(pm.group(1)), float(pm.group(2))
        woorden = []
        for wm in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" '
                              r'yMax="([\d.]+)">(.*?)</word>', pm.group(3)):
            x0, y0, x1, y1 = (float(wm.group(i)) for i in range(1, 5))
            t = html.unescape(wm.group(5)).strip()
            if t:
                woorden.append({"t": t, "x": x0 / pw, "y": y0 / ph,
                                "w": (x1 - x0) / pw, "h": (y1 - y0) / ph})
        paginas.append(woorden)
    return paginas


def _png_data_url(pad: str) -> str:
    with open(pad, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def _render_pdf(pad: str, tmp: str, dpi: int, prefix: str) -> list[str]:
    subprocess.run(["pdftoppm", "-r", str(dpi), "-l", str(MAX_PAGINAS), "-png", pad,
                    os.path.join(tmp, prefix)], capture_output=True, timeout=_TIMEOUT)
    return sorted(os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith(prefix))


def maak_rijen(woorden: list[dict]) -> list[list[dict]]:
    """Groepeert woorden tot visuele rijen (op y-positie), van boven naar onder."""
    rijen: list[list[dict]] = []
    for w in sorted(woorden, key=lambda w: (w["y"] + w["h"] / 2, w["x"])):
        cy = w["y"] + w["h"] / 2
        if rijen:
            r = rijen[-1]
            rcy = sum(v["y"] + v["h"] / 2 for v in r) / len(r)
            rh = sum(v["h"] for v in r) / len(r)
            if abs(cy - rcy) <= max(rh, w["h"]) * 0.5:
                r.append(w)
                continue
        rijen.append([w])
    for r in rijen:
        r.sort(key=lambda w: w["x"])
    return rijen


def rij_tekst(rij: list[dict]) -> str:
    """Tekst van een rij; grote horizontale gaten worden 3+ spaties (zoals -layout)."""
    delen = []
    for i, w in enumerate(rij):
        if i:
            vorige = rij[i - 1]
            gat = w["x"] - (vorige["x"] + vorige["w"])
            delen.append("    " if gat > max(vorige["h"], w["h"]) * 1.5 else " ")
        delen.append(w["t"])
    return "".join(delen)


def lees_document(pad: str, met_afbeelding: bool = True) -> dict:
    """
    Leest een factuur. Resultaat:
      {methode, tekst, paginas: [{afbeelding, woorden: [{id,t,x,y,w,h,r}], rijen: [tekst]}]}
    `afbeelding` is een PNG data-URL voor PDF's; bij afbeeldingen None (de browser
    toont het originele bestand zelf).
    """
    ext = os.path.splitext(pad)[1].lower()
    methode = ""
    pagina_woorden: list[list[dict]] = []
    afbeeldingen: list[str | None] = []

    with tempfile.TemporaryDirectory() as tmp:
        if ext in PDF_EXT:
            if pdf_beschikbaar():
                pagina_woorden = _pdf_woorden(pad)
                if sum(len(p) for p in pagina_woorden) >= 5:
                    methode = "pdf-tekst"
            if not methode and ocr_beschikbaar() and shutil.which("pdftoppm"):
                pagina_woorden = [_tesseract_woorden(p)[0]
                                  for p in _render_pdf(pad, tmp, 300, "ocr")]
                methode = "ocr"
            if methode and met_afbeelding and shutil.which("pdftoppm"):
                afbeeldingen = [_png_data_url(p) for p in _render_pdf(pad, tmp, 110, "toon")]
        elif ext in IMG_EXT and ocr_beschikbaar():
            pagina_woorden = [_tesseract_woorden(pad)[0]]
            methode = "ocr"

    paginas = []
    teksten = []
    wid = 0
    for i, woorden in enumerate(pagina_woorden):
        rijen = maak_rijen(woorden)
        rij_teksten = []
        for ri, rij in enumerate(rijen):
            for w in rij:
                w.update(id=wid, r=ri, p=i)
                for k in ("x", "y", "w", "h"):
                    w[k] = round(w[k], 5)
                wid += 1
            rij_teksten.append(rij_tekst(rij))
        teksten.append("\n".join(rij_teksten))
        paginas.append({
            "afbeelding": afbeeldingen[i] if i < len(afbeeldingen) else None,
            "woorden": [w for rij in rijen for w in rij],
            "rijen": rij_teksten,
        })
    return {"methode": methode, "tekst": "\n\n".join(teksten), "paginas": paginas}


# ─── Herkenning ───────────────────────────────────────────────────────────────

_MAANDEN = {
    "jan": 1, "januari": 1, "january": 1, "feb": 2, "februari": 2, "february": 2,
    "mrt": 3, "maart": 3, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "mei": 5, "may": 5, "jun": 6, "juni": 6, "june": 6, "jul": 7, "juli": 7, "july": 7,
    "aug": 8, "augustus": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Bedrag: 1.234,56 | 1,234.56 | 1234,56 | 12.50 | 12,- ; optioneel met €/EUR ervoor
_BEDRAG_RE = re.compile(
    r"(?<![\d.,])-?(?:€|eur|euro)?\s*"
    r"(\d{1,3}(?:[.\s]\d{3})+,\d{2}|\d{1,3}(?:,\d{3})+\.\d{2}|\d+[.,]\d{2}|\d+,-)"
    r"(?![\d]|[.,/-]\d)",
    re.IGNORECASE,
)
_PCT_RE = re.compile(r"(?<!\d)(21|9|6|0)(?:[.,]0+)?\s*%")


def parse_bedrag(s: str) -> float | None:
    s = s.strip().replace(" ", "").replace(" ", "")
    if s.endswith(",-"):
        s = s[:-2]
    elif re.search(r",\d{2}$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def bedragen_in(regel: str) -> list[float]:
    # Percentages (21%) niet als bedrag meetellen
    schoon = _PCT_RE.sub(" ", regel)
    out = []
    for m in _BEDRAG_RE.finditer(schoon):
        b = parse_bedrag(m.group(1))
        if b is not None:
            out.append(b)
    return out


def datum_in(regel: str) -> str | None:
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", regel)
    if m:
        j, mnd, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b", regel)
        if m:
            d, mnd, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.search(r"\b(\d{1,2})[\s\-/.]+([a-zA-Z]{3,9})\.?[\s\-/.']+(\d{4}|\d{2})\b", regel)
            if not m or m.group(2).lower() not in _MAANDEN:
                return None
            d, mnd, j = int(m.group(1)), _MAANDEN[m.group(2).lower()], int(m.group(3))
    if j < 100:
        j += 2000
    try:
        return date(j, mnd, d).isoformat()
    except ValueError:
        return None


_KW_TOTAAL = re.compile(r"te\s+betalen|te\s+voldoen|factuurbedrag|totaal\s*(?:incl|bedrag|factuur)|totaalbedrag|"
                        r"total\s*(?:due|incl|amount)|amount\s+due|grand\s+total|"
                        r"\btotaal\b|\btotal\b", re.I)
_KW_EXCL = re.compile(r"subtotaal|sub-totaal|subtotal|excl\.?\s*(?:btw|vat)|"
                      r"totaal\s*excl|netto|net\s+amount", re.I)
_KW_BTW = re.compile(r"\bbtw\b|\bvat\b|\bomzetbelasting\b|\bb\.t\.w\.?", re.I)
_KW_GEEN_BTW_BEDRAG = re.compile(r"btw[-\s]*(?:nr|nummer|id)|vat[-\s]*(?:no|number|id|reg)|"
                                 r"\bNL\d{9}B\d{2}\b", re.I)
# Rijen die nooit een factuurregel of leveranciersnaam zijn
_KW_GEEN_REGEL = re.compile(
    r"\bfactuur|\binvoice|\bdatum\b|\bdate\b|\bverval|\bdue\b|\biban\b|\bbic\b|"
    r"\bswift\b|\bkvk\b|k\.v\.k|\bbtw\b|\bvat\b|\btel\b|telefoon|\bphone\b|"
    r"e-?mail|www\.|http|@|\bpagina\b|\bpage\b|klantnummer|klantnr|debiteur|"
    r"referentie|\breference\b|ordernummer|order\s*(?:no|nr|number)|"
    r"\bbetaal|\bpayment\b|\brekening\b|\baccount\b|postbus|\btotaal|\btotal\b|"
    r"\bkorting\b", re.I)
_RE_ADRES = re.compile(r"\b\d{4}\s?[A-Z]{2}\b|(?:straat|weg|laan|plein|kade|gracht|"
                       r"singel|dijk|park|hof|steeg|street|road|avenue)\b\.?\s*\d|"
                       r"\b(?:postbus|p\.?o\.?\s*box)\b", re.I)
_RE_RECHTSVORM = re.compile(r"(?:\bb\.?v\.?(?=\s|$)|\bn\.v\.|\bv\.o\.f\.?|\bvof\b|\bc\.v\.|"
                            r"\bltd\b|\bgmbh\b|\binc\b|\bllc\b|\bholding\b|\bgroep\b|\bgroup\b)", re.I)


_RE_LABELWOORD = re.compile(
    r"^(?:kvk|k\.v\.k\.?|coc|btw(?:-?(?:nr|nummer|id))?|vat|iban|bic|swift|tel(?:efoon)?|"
    r"phone|fax|e-?mail|web(?:site)?|www\..*|klant(?:nr|nummer)?|debiteur(?:nr|nummer)?|"
    r"referentie|ref|order(?:nr|nummer)?|vervaldatum|due|pagina|page)[:.]?$", re.I)
_RE_IDENTIFICATIE = re.compile(
    r"^(?:NL\d{9}B\d{2}|[A-Z]{2}\d{2}[A-Z]{4}\d{6,}|\d{8}|(?:\+|00|0)\d[\d\s-]{8,})$", re.I)


def is_labelwoord(t: str) -> bool:
    """Woord dat een nieuw veld aankondigt ("KvK:", "IBAN", "Tel.", "Vervaldatum:")."""
    t = t.strip()
    return bool(_RE_LABELWOORD.match(t)) or (t.endswith(":") and len(t) > 2
                                             and bool(re.search(r"[A-Za-z]", t)))


def is_identificatie(t: str) -> bool:
    """KvK-nummer, btw-nummer, IBAN of telefoonnummer."""
    return bool(_RE_IDENTIFICATIE.match(t.strip(" :;,.")))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def herken_leverancier(regels: list[str], eigen_namen: list[str] | None = None,
                       bekende: list[str] | None = None) -> str | None:
    tekst_n = " " + _norm("\n".join(regels)) + " "
    # 1. Een eerder gebruikte leverancier die letterlijk in de tekst staat
    for naam in sorted(bekende or [], key=len, reverse=True):
        n = _norm(naam)
        if len(n) >= 3 and f" {n} " in tekst_n:
            return naam
    eigen = [_norm(n) for n in (eigen_namen or []) if n and len(_norm(n)) >= 3]
    kandidaten = []
    eigen_blok = -1  # rijen direct na je eigen naam zijn jouw adresblok
    for i, r in enumerate(regels):
        if bedragen_in(r):
            continue  # rij met een bedrag is een factuurregel of totaal, geen naam
        # Rijen opsplitsen in kolommen en voettekst-segmenten ("Naam B.V. | KvK ...")
        for deel in re.split(r"\s{3,}|\s[|•·]\s|\s-\s", r):
            deel = deel.strip(" |•·-")
            n = _norm(deel)
            if not re.search(r"[A-Za-z]{3,}", deel) or len(n) < 3:
                continue
            if any(e in n or n in e for e in eigen):
                eigen_blok = i
                continue  # eigen bedrijfsnaam (de factuur is aan jou gericht)
            if 0 <= eigen_blok and i - eigen_blok <= 4:
                continue
            if re.match(r"^(factuur|invoice|rekening|creditnota|pagina|page|datum|date|aan|to|"
                        r"bill\s*to|ship\s*to|t\.?a\.?v\.?|omschrijving|description)\b", deel, re.I):
                continue
            if _KW_GEEN_REGEL.search(deel) or _RE_ADRES.search(deel) or bedragen_in(deel) \
                    or datum_in(deel) or len(deel) > 60:
                continue
            score = 0.0
            if i < 6:
                score += 6 - i  # bovenaan (logo/briefhoofd)
            if i >= len(regels) - 3:
                score += 3      # voettekst
            if _RE_RECHTSVORM.search(deel):
                score += 8
            if deel.isupper() and len(deel) > 3:
                score += 1
            kandidaten.append((score, -i, deel[:80]))
    if not kandidaten:
        return None
    return max(kandidaten)[2]


def herken_factuur(tekst: str, eigen_namen: list[str] | None = None,
                   bekende_leveranciers: list[str] | None = None) -> dict:
    """Haalt velden uit factuurtekst. Ontbrekende velden worden weggelaten."""
    regels = [r.strip() for r in tekst.splitlines() if r.strip()]
    res: dict = {}

    lev = herken_leverancier(regels, eigen_namen, bekende_leveranciers)
    if lev:
        res["leverancier"] = lev

    m = re.search(r"(?:factuur\s*(?:nummer|nr\.?|no\.?)|invoice\s*(?:number|no\.?|nr\.?|#)|"
                  r"factuur\s*#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/._]{2,})", tekst, re.I)
    if m:
        res["factuurnummer"] = m.group(1).rstrip(".")

    datum = None
    for r in regels:
        if re.search(r"factuurdatum|invoice\s*date|\bdatum\b|\bdate\b", r, re.I) and \
                not re.search(r"verval|due|leverdatum", r, re.I):
            datum = datum_in(r)
            if datum:
                break
    if not datum:
        for r in regels:
            datum = datum_in(r)
            if datum:
                break
    if datum:
        res["datum"] = datum

    totaal = excl = btw_bedrag = None
    pct = None
    for r in regels:
        bedragen = bedragen_in(r)
        if _KW_EXCL.search(r):
            if bedragen and excl is None:
                excl = bedragen[-1]
            continue
        if _KW_BTW.search(r) and not _KW_GEEN_BTW_BEDRAG.search(r) and not _KW_TOTAAL.search(r):
            pm = _PCT_RE.search(r)
            if pm and pct is None:
                pct = int(pm.group(1))
            if bedragen:
                btw_bedrag = (btw_bedrag or 0) + bedragen[-1]
            continue
        if _KW_TOTAAL.search(r) and bedragen:
            totaal = bedragen[-1]
    if pct is None:
        pm = _PCT_RE.search(tekst)
        if pm:
            pct = int(pm.group(1))

    if excl is None and totaal is not None:
        if btw_bedrag is not None and btw_bedrag < totaal:
            excl = round(totaal - btw_bedrag, 2)
        elif pct is not None:
            excl = round(totaal / (1 + pct / 100), 2)
    if btw_bedrag is None and excl is not None and totaal is not None and totaal >= excl:
        btw_bedrag = round(totaal - excl, 2)
    if pct is None and excl and btw_bedrag is not None:
        geschat = btw_bedrag / excl * 100
        pct = min((21, 9, 0), key=lambda p: abs(p - geschat))

    if totaal is not None:
        res["totaal_incl_btw"] = totaal
    if excl is not None:
        res["bedrag_excl_btw"] = excl
    if btw_bedrag is not None:
        res["btw_bedrag"] = round(btw_bedrag, 2)
    if pct is not None:
        res["btw_percentage"] = pct if pct in (21, 9, 0) else 21
    return res


def is_totaalregel(r: str) -> bool:
    """(Sub)totaal- of btw-regel mét bedrag: daar houden de factuurregels op.
    Kopjes zonder bedrag ('Totaal' als kolomkop, 'BTW: NL…') tellen niet."""
    if not bedragen_in(r):
        return False
    return bool(_KW_EXCL.search(r) or _KW_TOTAAL.search(r)
                or (_KW_BTW.search(r) and not _KW_GEEN_BTW_BEDRAG.search(r)))


def regel_uit_rij(tekst: str, standaard_pct: int | None) -> dict | None:
    """Maakt van één rij tekst een factuurregel {omschrijving, bedrag, btw_percentage}."""
    bedragen = bedragen_in(tekst)
    if not bedragen:
        return None
    pm = _PCT_RE.search(tekst)
    oms = _PCT_RE.sub(" ", tekst)
    oms = _BEDRAG_RE.sub(" ", oms)
    # losse getallen/eenheden (aantal, stuks) aan het eind weghalen
    oms = re.sub(r"(?:\s+(?:\d+(?:[.,]\d+)?|x|st|stk|stuks?|pcs|uur|u|€|eur))+\s*$", "",
                 oms.strip(), flags=re.I)
    oms = re.sub(r"\s{2,}", " ", oms).strip(" -:|")
    if not re.search(r"[A-Za-z]{3,}", oms):
        return None
    pct = int(pm.group(1)) if pm else standaard_pct
    return {"omschrijving": oms[:120], "bedrag": bedragen[-1],
            "btw_percentage": pct if pct in (21, 9, 0) else (standaard_pct or 21)}


def herken_regels(tekst: str, velden: dict) -> list[dict]:
    """
    Zoekt factuurregels: rijen met omschrijving + bedrag vóór de (sub)totalen.
    Geeft alleen regels terug als hun som klopt met het bedrag excl. of incl. btw.
    Bedragen in het resultaat zijn altijd excl. btw.
    """
    pct = velden.get("btw_percentage")
    kandidaten = []
    for r in (r.strip() for r in tekst.splitlines()):
        if not r:
            continue
        if is_totaalregel(r):
            break
        if _KW_GEEN_REGEL.search(r) or datum_in(r):
            continue
        reg = regel_uit_rij(r, pct)
        if reg:
            kandidaten.append(reg)
    excl, totaal = velden.get("bedrag_excl_btw"), velden.get("totaal_incl_btw")
    # Langste reeks regels (vanaf boven) waarvan de som klopt; zo vallen onbekende
    # subtotaal-regels ("Som regels  29,45") er vanzelf af.
    for n in range(len(kandidaten), 0, -1):
        deel = kandidaten[:n]
        som = round(sum(k["bedrag"] for k in deel), 2)
        if excl is not None and abs(som - excl) <= 0.05:
            return [{"omschrijving": k["omschrijving"], "bedrag_excl_btw": k["bedrag"],
                     "btw_percentage": k["btw_percentage"]} for k in deel]
        if totaal is not None and abs(som - totaal) <= 0.05:
            return [{"omschrijving": k["omschrijving"],
                     "bedrag_excl_btw": round(k["bedrag"] / (1 + (k["btw_percentage"] or 0) / 100), 2),
                     "btw_percentage": k["btw_percentage"]} for k in deel]
    return []
    som = round(sum(k["bedrag"] for k in kandidaten), 2)
    excl, totaal = velden.get("bedrag_excl_btw"), velden.get("totaal_incl_btw")
    if excl is not None and abs(som - excl) <= 0.05:
        return [dict(k, bedrag_excl_btw=k.pop("bedrag")) for k in kandidaten]
    if totaal is not None and abs(som - totaal) <= 0.05:
        return [dict(k, bedrag_excl_btw=round(k.pop("bedrag") / (1 + (k["btw_percentage"] or 0) / 100), 2))
                for k in kandidaten]
    return []
