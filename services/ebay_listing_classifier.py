from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CATEGORIES = (
    "FULL_SET",
    "INCOMPLETE_SET",
    "ACCESSORY",
    "PARTS",
    "INSTRUCTIONS",
    "BOX_ONLY",
    "COMPATIBLE_PRODUCT",
    "OTHER",
    "UNCERTAIN",
)


@dataclass(frozen=True)
class ListingClassification:
    category: str
    reasons: tuple[str, ...]


def _plain(value):
    return (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode()
        .casefold()
    )


def _contains(text, terms):
    return any(term in text for term in terms)


def _identity_matches(title, expected_terms):
    title_compact = re.sub(r"[^a-z0-9]", "", title)
    title_tokens = set(re.findall(r"[a-z0-9]+", title))
    stopwords = {"a", "and", "of", "the", "to"}
    for term in expected_terms:
        normalized = _plain(term)
        compact = re.sub(r"[^a-z0-9]", "", normalized)
        if compact and compact in title_compact:
            return True
        tokens = {
            token for token in re.findall(r"[a-z0-9]+", normalized)
            if token not in stopwords
        }
        required = max(2, (len(tokens) + 1) // 2)
        if len(tokens) >= 2 and len(tokens & title_tokens) >= required:
            return True
    return False


def classify_ebay_listing(item, *, set_num, expected_terms=()):
    title = _plain(item.get("title"))
    set_root = set_num.removesuffix("-1")
    exact_set = bool(re.search(
        rf"(?<!\d){re.escape(set_root)}(?:-1)?(?!\d)", title
    ))
    expected = _identity_matches(title, expected_terms)
    lego = bool(re.search(r"(?<![a-z0-9])lego(?![a-z0-9])", title))

    if _contains(title, (
        "box only", "empty box", "caja vacia", "solo caja", "boite vide",
        "scatola vuota", "leere ovp", "ovp leer", "karton ohne", "solo en caja",
    )):
        return ListingClassification("BOX_ONLY", ("title indicates empty/original box only",))

    if _contains(title, (
        "light kit", "led light", "lighting kit", "kit de luz", "kit luces",
        "luces led", "beleuchtungsset", "eclairage led", "luci led", "display case",
        "dust cover", "acrylic case", "vitrina", "urna", "wall mount",
        "montaje en pared", "soporte de pared", "display stand", "supporto display",
        "soporte display", "soporte de montaje", "soporte #", "showcase",
        "plexiglass", "acrilico", "teca per set",
        "expositor", "display plaque", "placa de exhibicion", "license plate",
        "placa de matricula", "sticker", "pegatina", "realistic wheels",
        "cerchi", "felgen", "rims for", "wheel set", "marco ", "frame for",
        "kit de iluminacion", "iluminacion led", "briksmax", "no incluido",
        "modelo de exhibicion", "supporto ", "panel de exhibicion",
        "kit de luces", "locolee", "custom wheels", "ruote ",
        "placa de identificacion solo", "soporte r2",
        "owners pack", "owner's pack", "vip pack", "tarjetero", "billetera",
        "wallet", "gwp",
    )):
        return ListingClassification("ACCESSORY", ("title indicates an accessory",))

    if _contains(title, (
        "parts only", "spare parts", "replacement part", "piece detachee",
        "ersatzteil", "repuesto", "minifig", "minifigure", "piezas sueltas",
        "solo piezas", "lote de piezas", "manual + bolsa", "bolsa sellada #",
        "motor completo", "piece de rechange", "bolsa #", "bolsas de follaje",
        "convolut", "konvolut",
    )):
        return ListingClassification("PARTS", ("title indicates parts or figures",))

    if _contains(title, (
        "instructions only", "instruction booklet", "instruction manual only",
        "manual only", "manual solo", "solo manual", "solo instrucciones",
        "manual de instrucciones", "folleto de instrucciones", "sin ladrillos",
        "manuale set", "libros de instrucciones", "manuales libro", "manuales solo",
        "solo libros", "libro solo", "instrucciones solo",
        "instrucciones de construccion", "manual para",
        "assembly manual", "book only", "bauanleitung", "notice de montage",
        "libretto istruzioni",
    )):
        return ListingClassification("INSTRUCTIONS", ("title indicates instructions only",))

    incomplete_terms = (
        "incomplete", "incompleto", "missing piece", "faltan piezas",
        "sin caja", "without box", "no box", "ohne ovp", "sans boite",
        "sin minifig", "without minifig", "not complete", "nicht komplett",
        "casi completo", "completitud desconocid", "falta hoja", "faltan bolsa",
        "missing sticker", "piezas faltantes", "pieces missing",
    )
    percentage_incomplete = bool(re.search(r"\b(?:9[0-9](?:[.,][0-9]+)?)%\s*(?:complete|completo)", title))
    if _contains(title, incomplete_terms) or percentage_incomplete:
        return ListingClassification("INCOMPLETE_SET", ("title indicates missing content",))

    set_numbers = {
        match for match in re.findall(r"(?<!\d)([1-9]\d{4})(?!\d)", title)
        if not 1900 <= int(match) <= 2099
    }
    if len(set_numbers) > 1:
        return ListingClassification("OTHER", ("listing contains multiple set numbers",))

    if re.search(r"(?<![a-z0-9])(?:2|3|4|5)x\s*lego", title):
        return ListingClassification("OTHER", ("listing contains multiple units",))

    if re.search(r"^listado\s+\d+:", title):
        return ListingClassification("UNCERTAIN", ("ambiguous numbered listing title",))

    if _contains(title, (
        "compatible with", "compatible con", "compatibles con", "for lego", "para lego",
        "fur lego", "pour lego", "compatibile con lego", "custom mod",
        "alternative model", "alternativem", "alternate build", "welcome pack",
    )) or bool(re.search(r"(?<![a-z0-9])moc(?![a-z0-9])", title)):
        return ListingClassification(
            "COMPATIBLE_PRODUCT", ("title indicates a compatible or alternate product",)
        )

    if exact_set and lego and expected:
        return ListingClassification(
            "FULL_SET", ("exact set number", "LEGO brand", "expected product terms")
        )
    full_set_signal = _contains(title, (
        "new", "nuevo", "nueva", "neu", "neuf", "nuovo", "sellado", "sealed",
        "precintado", "completo", "complete", "gebraucht", "used", "usado",
        "usato", "occasion", "embalaje original", "original box", "misb",
        "montado", "assembled", "retirado", "retired",
    ))
    if exact_set and lego and full_set_signal:
        return ListingClassification(
            "FULL_SET", ("exact set number", "LEGO brand", "full-set state signal")
        )
    if exact_set:
        return ListingClassification(
            "UNCERTAIN", ("exact set number without enough full-set identity signals",)
        )
    return ListingClassification("OTHER", ("exact set number not found",))


def normalized_condition(item):
    condition_id = str(item.get("conditionId") or "")
    condition = _plain(item.get("condition"))
    if condition_id in {"1000", "1500", "1750"} or _contains(
        condition, ("new", "nuevo", "neuf", "neu", "nuovo")
    ):
        return "NEW"
    if condition_id in {"2500", "2750", "3000", "4000", "5000", "6000", "7000"} or _contains(
        condition, ("used", "usado", "gebraucht", "occasion", "usato")
    ):
        return "USED"
    return "UNKNOWN"
