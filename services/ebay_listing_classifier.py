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


def classify_ebay_listing(item, *, set_num, expected_terms=()):
    title = _plain(item.get("title"))
    set_root = set_num.removesuffix("-1")
    exact_set = bool(re.search(
        rf"(?<!\d){re.escape(set_root)}(?:-1)?(?!\d)", title
    ))
    expected = any(_plain(term) in title for term in expected_terms)
    lego = bool(re.search(r"(?<![a-z0-9])lego(?:®)?(?![a-z0-9])", title))

    if _contains(title, (
        "box only", "empty box", "caja vacia", "solo caja", "boite vide",
        "scatola vuota", "leere ovp", "ovp leer", "karton ohne",
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
        "cerchi", "felgen", "rims for", "wheel set",
    )):
        return ListingClassification("ACCESSORY", ("title indicates an accessory",))

    if _contains(title, (
        "parts only", "spare parts", "replacement part", "piece detachee",
        "ersatzteil", "repuesto", "minifig", "minifigure", "piezas sueltas",
        "solo piezas", "lote de piezas", "manual + bolsa", "convolut", "konvolut",
    )):
        return ListingClassification("PARTS", ("title indicates parts or figures",))

    if _contains(title, (
        "instructions only", "instruction booklet", "instruction manual only",
        "manual only", "manual solo", "solo manual", "solo instrucciones",
        "manual de instrucciones", "folleto de instrucciones", "sin ladrillos",
        "manuale set",
        "bauanleitung", "notice de montage", "libretto istruzioni",
    )):
        return ListingClassification("INSTRUCTIONS", ("title indicates instructions only",))

    incomplete_terms = (
        "incomplete", "incompleto", "missing piece", "faltan piezas",
        "sin caja", "without box", "no box", "ohne ovp", "sans boite",
        "sin minifig", "without minifig", "not complete", "nicht komplett",
        "casi completo", "completitud desconocid",
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
