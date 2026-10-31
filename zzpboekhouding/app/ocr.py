"""
OCR en herkenning van (inkoop)facturen.

- Tekst ophalen: PDF met tekstlaag via `pdftotext`, gescande PDF via `pdftoppm` +
  `tesseract`, afbeeldingen direct via `tesseract`. Er worden alleen externe
  command-line tools gebruikt (poppler-utils + tesseract-ocr), geen extra
  Python-dependencies.
- Herkennen: heuristieken voor datum, leverancier, factuurnummer, totaal,
  btw-bedrag, btw-percentage en bedrag excl. btw (NL + EN facturen).
"""
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
_TIMEOUT = 120


def ocr_beschikbaar() -> bool:
    return shutil.which("tesseract") is not None


def pdf_beschikbaar() -> bool:
    return shutil.which("pdftotext") is not None


def _run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT)
    return res.stdout.decode("utf-8", errors="replace")


def _talen() -> str:
    """Gebruik alleen talen die tesseract daadwerkelijk heeft geïnstalleerd."""
    try:
        out = _run(["tesseract", "--list-langs"])
        beschikbaar = {l.strip() for l in out.splitlines()[1:] if l.strip()}
    except Exception:
        return "eng"
    gewenst = [t for t in OCR_TALEN.split("+") if t in beschikbaar]
    return "+".join(gewenst) or "eng"


def _tesseract(pad: str) -> str:
    return _run(["tesseract", pad, "stdout", "-l", _talen(), "--psm", "4"])


def tekst_uit_bestand(pad: str) -> tuple[str, str]:
    """Geeft (tekst, methode) terug. Methode: 'pdf-tekst', 'ocr' of ''."""
    ext = os.path.splitext(pad)[1].lower()
    if ext in PDF_EXT:
        tekst = ""
        if pdf_beschikbaar():
            tekst = _run(["pdftotext", "-layout", "-l", "3", pad, "-"])
        if len(tekst.strip()) >= 30:
            return tekst, "pdf-tekst"
        # Gescande PDF: pagina's renderen en OCR'en
        if ocr_beschikbaar() and shutil.which("pdftoppm"):
            with tempfile.TemporaryDirectory() as tmp:
                prefix = os.path.join(tmp, "p")
                subprocess.run(["pdftoppm", "-r", "300", "-l", "3", "-png", pad, prefix],
                               capture_output=True, timeout=_TIMEOUT)
                delen = [_tesseract(os.path.join(tmp, f)) for f in sorted(os.listdir(tmp))]
            return "\n".join(delen), "ocr"
        return tekst, "pdf-tekst" if tekst.strip() else ""
    if ext in IMG_EXT and ocr_beschikbaar():
        return _tesseract(pad), "ocr"
    return "", ""


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
    r"(?![\d])",
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


def _bedragen(regel: str) -> list[float]:
    # Percentages (21%) niet als bedrag meetellen
    schoon = _PCT_RE.sub(" ", regel)
    out = []
    for m in _BEDRAG_RE.finditer(schoon):
        b = parse_bedrag(m.group(1))
        if b is not None:
            out.append(b)
    return out


def _datum_uit(regel: str) -> str | None:
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", regel)
    if m:
        j, mnd, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b", regel)
        if m:
            d, mnd, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.search(r"\b(\d{1,2})\s+([a-zA-Z]{3,9})\.?\s+(\d{4})\b", regel)
            if not m or m.group(2).lower() not in _MAANDEN:
                return None
            d, mnd, j = int(m.group(1)), _MAANDEN[m.group(2).lower()], int(m.group(3))
    if j < 100:
        j += 2000
    try:
        return date(j, mnd, d).isoformat()
    except ValueError:
        return None


_KW_TOTAAL = re.compile(r"te\s+betalen|totaal\s*(?:incl|bedrag|factuur)|totaalbedrag|"
                        r"total\s*(?:due|incl|amount)|amount\s+due|grand\s+total|"
                        r"\btotaal\b|\btotal\b", re.I)
_KW_EXCL = re.compile(r"subtotaal|sub-totaal|subtotal|excl\.?\s*(?:btw|vat)|"
                      r"totaal\s*excl|netto|net\s+amount", re.I)
_KW_BTW = re.compile(r"\bbtw\b|\bvat\b|\bomzetbelasting\b|\bb\.t\.w\.?", re.I)
_KW_GEEN_BTW_BEDRAG = re.compile(r"btw[-\s]*(?:nr|nummer|id)|vat[-\s]*(?:no|number|id|reg)|"
                                 r"\bNL\d{9}B\d{2}\b", re.I)


def herken_factuur(tekst: str) -> dict:
    """Haalt velden uit factuurtekst. Ontbrekende velden worden weggelaten."""
    regels = [r.strip() for r in tekst.splitlines() if r.strip()]
    res: dict = {}

    # Leverancier: eerste regel met letters die geen standaardkop is
    for r in regels[:8]:
        if re.search(r"[A-Za-z]{3,}", r) and not re.match(
                r"^(factuur|invoice|rekening|creditnota|pagina|page|datum|date)\b", r, re.I):
            res["leverancier"] = re.split(r"\s{3,}", r)[0][:80]
            break

    # Factuurnummer
    m = re.search(r"(?:factuur\s*(?:nummer|nr\.?|no\.?)|invoice\s*(?:number|no\.?|nr\.?|#)|"
                  r"factuur\s*#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/._]{2,})", tekst, re.I)
    if m:
        res["factuurnummer"] = m.group(1).rstrip(".")

    # Datum: voorkeur voor regel met 'factuurdatum'/'datum'/'date'
    datum = None
    for r in regels:
        if re.search(r"factuurdatum|invoice\s*date|\bdatum\b|\bdate\b", r, re.I) and \
                not re.search(r"verval|due|leverdatum", r, re.I):
            datum = _datum_uit(r)
            if datum:
                break
    if not datum:
        for r in regels:
            datum = _datum_uit(r)
            if datum:
                break
    if datum:
        res["datum"] = datum

    # Bedragen
    totaal = excl = btw_bedrag = None
    pct = None
    for r in regels:
        bedragen = _bedragen(r)
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
            # laatste 'totaal' wint (meestal het eindbedrag onderaan)
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


def verwerk_bestand(pad: str) -> dict:
    tekst, methode = tekst_uit_bestand(pad)
    velden = herken_factuur(tekst) if tekst.strip() else {}
    return {"methode": methode, "tekst": tekst[:5000], "velden": velden}
