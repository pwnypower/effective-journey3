"""
Leren van gecorrigeerde facturen, per leverancier.

Een leveranciersprofiel onthoudt:
- kenmerken om de leverancier te herkennen (btw-nummer, KvK, IBAN, e-maildomein);
- standaardwaarden (categorie, btw%, zakelijk%, omschrijving);
- "ankers" per veld: het label links van de waarde ("Te betalen"), het label erboven
  (tabelkop) en de positie op de pagina — zodat dezelfde waarde op een volgende
  factuur van die leverancier teruggevonden wordt;
- de "regelzone": waar de factuurregels beginnen en in welke kolom het bedrag staat.

Alle functies hier zijn puur (geen database), zodat ze los te testen zijn.
"""
import re

import ocr

VELDEN_BEDRAG = {"totaal_incl_btw", "bedrag_excl_btw", "btw_bedrag"}
VELDEN_TEKST = {"leverancier", "omschrijving", "factuurnummer"}
ALLE_VELDEN = VELDEN_BEDRAG | VELDEN_TEKST | {"datum"}

_ALGEMENE_DOMEINEN = {"gmail.com", "hotmail.com", "outlook.com", "live.com", "icloud.com",
                      "yahoo.com", "ziggo.nl", "kpnmail.nl", "planet.nl", "home.nl",
                      "hotmail.nl", "live.nl", "outlook.nl", "me.com"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# ─── Kenmerken ────────────────────────────────────────────────────────────────

def kenmerken_uit(tekst: str, eigen: set[str] | None = None) -> list[str]:
    """Identificerende gegevens van de afzender. Eigen gegevens worden overgeslagen."""
    eigen = {e.upper().replace(" ", "") for e in (eigen or set()) if e}
    gevonden = []
    for m in re.finditer(r"\bNL\s?\d{9}\s?B\s?\d{2}\b", tekst, re.I):
        gevonden.append(("btw", re.sub(r"\s", "", m.group(0)).upper()))
    for m in re.finditer(r"(?:kvk|k\.v\.k\.?|kamer\s+van\s+koophandel|coc)[^\d\n]{0,20}(\d{8})\b",
                         tekst, re.I):
        gevonden.append(("kvk", m.group(1)))
    for m in re.finditer(r"\b[A-Z]{2}\d{2}\s?[A-Z]{4}(?:\s?\d{4}){2}\s?\d{2}\b", tekst):
        gevonden.append(("iban", re.sub(r"\s", "", m.group(0)).upper()))
    for m in re.finditer(r"(?:@|www\.)([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})", tekst, re.I):
        gevonden.append(("domein", m.group(1).lower()))
    out = []
    for soort, waarde in gevonden:
        if waarde.upper() in eigen or (soort == "domein" and waarde in _ALGEMENE_DOMEINEN):
            continue
        k = f"{soort}:{waarde}"
        if k not in out:
            out.append(k)
    return out


def kies_profiel(profielen: list[dict], kenmerken: list[str], tekst: str) -> dict | None:
    """Beste profiel: overeenkomende kenmerken wegen zwaar, naam in de tekst licht."""
    tekst_n = " " + _norm(tekst) + " "
    beste, beste_score = None, 0
    for p in profielen:
        score = 0
        pk = set(p.get("kenmerken") or [])
        for k in kenmerken:
            if k in pk:
                score += 3 if k.startswith(("btw:", "kvk:", "iban:")) else 2
        n = _norm(p.get("naam"))
        if len(n) >= 4 and f" {n} " in tekst_n:
            score += 1
        if score > beste_score:
            beste, beste_score = p, score
    return beste


# ─── Ankers toepassen ─────────────────────────────────────────────────────────

def _rijen(doc: dict) -> list[tuple[int, list[dict]]]:
    """[(pagina, [woorden van de rij])] in leesvolgorde."""
    out = []
    for pi, pagina in enumerate(doc.get("paginas", [])):
        rijen: dict[int, list[dict]] = {}
        for w in pagina["woorden"]:
            rijen.setdefault(w["r"], []).append(w)
        for ri in sorted(rijen):
            out.append((pi, sorted(rijen[ri], key=lambda w: w["x"])))
    return out


def _zoek_label(rij: list[dict], label: str) -> int | None:
    """Index van het laatste woord van `label` in de rij, of None."""
    doel = _norm(label).split()
    if not doel:
        return None
    tokens = [_norm(w["t"]) for w in rij]
    for i in range(len(rij)):
        j, k = i, 0
        while j < len(rij) and k < len(doel):
            if not tokens[j]:
                j += 1
                continue
            if tokens[j] != doel[k]:
                break
            j, k = j + 1, k + 1
        if k == len(doel):
            return j - 1
    return None


def _tot_gat(woorden: list[dict], max_gat: float = 0.03) -> list[dict]:
    out = []
    for w in woorden:
        if out and w["x"] - (out[-1]["x"] + out[-1]["w"]) > max_gat:
            break
        out.append(w)
    return out


def _waarde(veld: str, woorden: list[dict]):
    """Zet woorden om naar een waarde voor het veld; None als het niet klopt."""
    if not woorden:
        return None
    tekst = " ".join(w["t"] for w in woorden)
    if veld in VELDEN_BEDRAG:
        b = ocr.bedragen_in(tekst)
        return b[0] if b else None
    if veld == "datum":
        return ocr.datum_in(tekst)
    if veld == "factuurnummer":
        for w in woorden:
            t = w["t"].strip(":#.,")
            if re.search(r"\d", t) and len(t) >= 3:
                return t
        return None
    tekst = tekst.strip(" :-|")
    return tekst or None


def zoek_anker(doc: dict, veld: str, anker: dict):
    """Vindt de waarde van een veld met een geleerd anker. Geeft (waarde, woord-ids)."""
    rijen = _rijen(doc)
    box = anker.get("box") or [0, 0, 1, 1]
    pagina = anker.get("pagina", 0)
    tekstveld = veld in {"omschrijving", "leverancier"}

    # 1. Label links van de waarde, op dezelfde rij
    if anker.get("label"):
        for pi, rij in sorted(rijen, key=lambda r: r[0] != pagina):
            idx = _zoek_label(rij, anker["label"])
            if idx is None:
                continue
            rest = rij[idx + 1:]
            if tekstveld:
                rest = _tot_gat(rest, 0.04)
            v = _waarde(veld, rest)
            if v is not None:
                return v, [w["id"] for w in rest]

    # 2. Label erboven (tabelkop): woorden in de rij eronder in dezelfde kolom
    if anker.get("boven"):
        for n, (pi, rij) in enumerate(rijen):
            idx = _zoek_label(rij, anker["boven"])
            if idx is None:
                continue
            x0, x1 = box[0] - 0.02, box[2] + 0.02
            for pi2, onder in rijen[n + 1:n + 3]:
                if pi2 != pi:
                    break
                kolom = [w for w in onder if w["x"] < x1 and w["x"] + w["w"] > x0]
                v = _waarde(veld, kolom)
                if v is not None:
                    return v, [w["id"] for w in kolom]

    # 3. Zelfde plek op de pagina
    pag = doc.get("paginas", [])
    if pagina < len(pag):
        dx, dy = 0.015, 0.01
        kandidaten = [w for w in pag[pagina]["woorden"]
                      if box[0] - dx <= w["x"] + w["w"] / 2 <= box[2] + dx
                      and box[1] - dy <= w["y"] + w["h"] / 2 <= box[3] + dy]
        kandidaten.sort(key=lambda w: (w["r"], w["x"]))
        v = _waarde(veld, kandidaten)
        if v is not None:
            return v, [w["id"] for w in kandidaten]
    return None, []


def regels_uit_zone(doc: dict, zone: dict, standaard_pct) -> tuple[list[dict], list[int]]:
    """Factuurregels vanaf het geleerde startpunt tot aan de (sub)totalen."""
    regels, ids = [], []
    pagina = zone.get("pagina", 0)
    for pi, rij in _rijen(doc):
        if pi != pagina:
            continue
        cy = sum(w["y"] + w["h"] / 2 for w in rij) / len(rij)
        if cy < zone.get("y0", 0) - 0.008:
            continue
        tekst = ocr.rij_tekst(rij)
        if ocr._KW_EXCL.search(tekst) or ocr._KW_TOTAAL.search(tekst) or \
                (ocr._KW_BTW.search(tekst) and not ocr._KW_GEEN_BTW_BEDRAG.search(tekst)):
            break
        if zone.get("eind_label") and _zoek_label(rij, zone["eind_label"]) is not None:
            break
        # Bedrag uit de geleerde kolom halen (niet stukprijs of aantal)
        bedrag_w = None
        if zone.get("bedrag_x") is not None:
            met_bedrag = [w for w in rij if ocr.bedragen_in(w["t"])]
            if met_bedrag:
                bedrag_w = min(met_bedrag,
                               key=lambda w: abs(w["x"] + w["w"] / 2 - zone["bedrag_x"]))
                if abs(bedrag_w["x"] + bedrag_w["w"] / 2 - zone["bedrag_x"]) > 0.1:
                    bedrag_w = None
        reg = ocr.regel_uit_rij(tekst, standaard_pct)
        if not reg:
            continue
        if bedrag_w is not None:
            reg["bedrag"] = ocr.bedragen_in(bedrag_w["t"])[0]
        regels.append(reg)
        ids.extend(w["id"] for w in rij)
    return regels, ids


def omschrijving_uit_regels(regels: list[dict], leverancier: str = "",
                            nummer: str = "") -> str:
    """Omschrijving voor facturen zonder algemene omschrijving: samengesteld uit de
    factuurregels, of 'Factuur <leverancier> <nummer>' als er geen regels zijn."""
    namen = [r.get("omschrijving", "").strip() for r in regels if r.get("omschrijving", "").strip()]
    if not namen:
        return " ".join(x for x in ("Factuur", leverancier, nummer) if x).strip()
    if len(namen) <= 2:
        tekst = ", ".join(namen)
    else:
        tekst = f"{namen[0]}, {namen[1]} + {len(namen) - 2} meer"
    return tekst[:120]


def vul_afgeleid(v: dict) -> dict:
    """Vult ontbrekende bedragen aan uit de andere (totaal/excl/btw/btw%)."""
    t, e, b, p = (v.get(k) for k in ("totaal_incl_btw", "bedrag_excl_btw", "btw_bedrag",
                                        "btw_percentage"))
    if e is None and t is not None:
        if b is not None and b < t:
            e = round(t - b, 2)
        elif p is not None:
            e = round(t / (1 + p / 100), 2)
    if b is None and e is not None and t is not None and t >= e:
        b = round(t - e, 2)
    if t is None and e is not None and b is not None:
        t = round(e + b, 2)
    for k, val in (("totaal_incl_btw", t), ("bedrag_excl_btw", e), ("btw_bedrag", b)):
        if val is not None:
            v[k] = val
    return v


def _klopt_met_totalen(regels: list[dict], velden: dict) -> list[dict]:
    """Langste reeks regels vanaf boven waarvan de som klopt met excl. of incl.;
    als niets klopt blijven alle regels staan (de gebruiker controleert)."""
    doelen = [velden.get(k) for k in ("bedrag_excl_btw", "totaal_incl_btw")
              if velden.get(k) is not None]
    for n in range(len(regels), 0, -1):
        som = round(sum(r["bedrag"] for r in regels[:n]), 2)
        if any(abs(som - d) <= 0.05 for d in doelen):
            return regels[:n]
    return regels


def _regels_naar_excl(regels: list[dict], velden: dict) -> list[dict]:
    som = round(sum(r["bedrag"] for r in regels), 2)
    incl = (velden.get("totaal_incl_btw") is not None
            and abs(som - velden["totaal_incl_btw"]) <= 0.05
            and not (velden.get("bedrag_excl_btw") is not None
                     and abs(som - velden["bedrag_excl_btw"]) <= 0.05))
    out = []
    for r in regels:
        r = dict(r)
        b = r.pop("bedrag")
        r["bedrag_excl_btw"] = round(b / (1 + (r["btw_percentage"] or 0) / 100), 2) if incl else b
        out.append(r)
    return out


def analyseer(doc: dict, profielen: list[dict], eigen_namen: list[str],
              eigen_ids: set[str], bekende_leveranciers: list[str]) -> dict:
    """Combineert heuristieken met wat per leverancier geleerd is."""
    tekst = doc.get("tekst", "")
    velden = ocr.herken_factuur(tekst, eigen_namen, bekende_leveranciers)
    bronnen = {k: "herkend" for k in velden}
    gevonden: dict[str, list[int]] = {}
    kenmerken = kenmerken_uit(tekst, eigen_ids)
    profiel = kies_profiel(profielen, kenmerken, tekst)

    regels: list[dict] = []
    if profiel:
        velden["leverancier"] = profiel["naam"]
        bronnen["leverancier"] = "geleerd"
        for veld, anker in (profiel.get("ankers") or {}).items():
            if veld not in ALLE_VELDEN or veld == "leverancier":
                continue
            waarde, ids = zoek_anker(doc, veld, anker)
            if waarde is not None:
                velden[veld] = waarde
                bronnen[veld] = "geleerd"
                gevonden[veld] = ids
        # Bedragen die uit geleerde ankers komen gaan voor; afgeleide waarden opnieuw
        if any(bronnen.get(k) == "geleerd" for k in VELDEN_BEDRAG):
            for k in VELDEN_BEDRAG:
                if bronnen.get(k) != "geleerd":
                    velden.pop(k, None)
        for k in ("categorie", "btw_percentage", "zakelijk_percentage"):
            if profiel.get(k) is not None and bronnen.get(k) != "geleerd":
                if k == "btw_percentage" and "btw_percentage" in velden:
                    continue  # op de factuur gevonden percentage gaat voor
                velden[k] = profiel[k]
                bronnen[k] = "standaard"
        vul_afgeleid(velden)
        if profiel.get("regelzone"):
            ruw, ids = regels_uit_zone(doc, profiel["regelzone"], velden.get("btw_percentage"))
            if ruw:
                regels = _regels_naar_excl(_klopt_met_totalen(ruw, velden), velden)
                gevonden["regels"] = ids
        if "omschrijving" not in velden and profiel.get("omschrijving") \
                and not profiel.get("omschrijving_uit_regels"):
            velden["omschrijving"] = profiel["omschrijving"].replace(
                "{factuurnummer}", str(velden.get("factuurnummer", ""))).strip()
            bronnen["omschrijving"] = "standaard"

    if not regels:
        regels = ocr.herken_regels(tekst, velden)
    if regels and "omschrijving" not in velden:
        velden["omschrijving"] = omschrijving_uit_regels(regels)
        bronnen["omschrijving"] = "regels"

    return {
        "velden": velden,
        "bronnen": bronnen,
        "regels": regels,
        "gevonden": gevonden,
        "kenmerken": kenmerken,
        "profiel": {"id": profiel["id"], "naam": profiel["naam"],
                    "aantal": profiel.get("aantal", 0)} if profiel else None,
    }


# ─── Leren ────────────────────────────────────────────────────────────────────

def werk_profiel_bij(bestaand: dict | None, naam: str, standaard: dict,
                     kenmerken: list[str], ankers: dict, regelzone: dict | None) -> dict:
    """Combineert een bestaand profiel met een nieuwe, door de gebruiker gecontroleerde factuur."""
    p = dict(bestaand or {})
    p["naam"] = naam
    km = list(p.get("kenmerken") or [])
    for k in kenmerken:
        if k not in km:
            km.append(k)
    p["kenmerken"] = km[-20:]
    a = dict(p.get("ankers") or {})
    for veld, anker in (ankers or {}).items():
        if veld in ALLE_VELDEN and veld != "leverancier" and isinstance(anker, dict):
            a[veld] = {
                "label": str(anker.get("label") or "")[:60],
                "boven": str(anker.get("boven") or "")[:60],
                "box": [float(x) for x in (anker.get("box") or [0, 0, 1, 1])[:4]],
                "pagina": int(anker.get("pagina") or 0),
            }
    p["ankers"] = a
    if regelzone and isinstance(regelzone, dict):
        p["regelzone"] = {
            "pagina": int(regelzone.get("pagina") or 0),
            "y0": float(regelzone.get("y0") or 0),
            "bedrag_x": (float(regelzone["bedrag_x"])
                         if regelzone.get("bedrag_x") is not None else None),
            "eind_label": str(regelzone.get("eind_label") or "")[:60],
        }
    for k in ("categorie", "btw_percentage", "zakelijk_percentage", "omschrijving"):
        if standaard.get(k) not in (None, ""):
            p[k] = standaard[k]
    # Omschrijving automatisch uit de regels: geen vaste tekst onthouden, alleen de keuze
    if standaard.get("omschrijving_uit_regels"):
        p["omschrijving_uit_regels"] = True
        p.pop("omschrijving", None)
    elif standaard.get("omschrijving"):
        p["omschrijving_uit_regels"] = False
    p["aantal"] = int(p.get("aantal") or 0) + 1
    return p
