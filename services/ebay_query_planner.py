from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from models.product_aliases import ProductAliases, get_product_aliases

_LOW_VALUE_TOKENS = {
    "and", "building", "construction", "creator", "edition", "expert",
    "icons", "kit", "lego", "model", "of", "set", "the",
}


@dataclass(frozen=True)
class NormalizedProductName:
    full_name: str
    short_name: str
    important_tokens: tuple[str, ...]


@dataclass(frozen=True)
class EbayQueryPlan:
    set_num: str
    name: NormalizedProductName
    aliases: ProductAliases
    queries: tuple[str, ...]

    @property
    def identity_terms(self) -> tuple[str, ...]:
        return (self.aliases.canonical_name, *self.aliases.aliases)


def _ascii(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode()
    )


def normalize_product_name(name: str) -> NormalizedProductName:
    full_name = " ".join(str(name).split())
    plain = _ascii(full_name)
    tokens = re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?", plain)
    important = tuple(
        token for token in tokens if token.casefold() not in _LOW_VALUE_TOKENS
    )

    lowered = plain.casefold()
    if "porsche" in lowered and "911" in lowered:
        short_name = "Porsche 911"
    elif "lamborghini" in lowered and "sian" in lowered:
        short_name = "Lamborghini Sian"
    elif "back to the future" in lowered:
        short_name = "Back to the Future"
    elif "tree house" in lowered:
        short_name = "Tree House"
    else:
        short_name = " ".join(important[:3]) or plain

    return NormalizedProductName(
        full_name=full_name,
        short_name=short_name,
        important_tokens=important,
    )


def plan_ebay_queries(
    set_num: str,
    name: str,
    aliases: tuple[str, ...] | list[str] = (),
    *,
    max_queries: int = 5,
) -> EbayQueryPlan:
    if not 1 <= max_queries <= 5:
        raise ValueError("max_queries must be between 1 and 5")

    root = re.sub(r"-\d+$", "", str(set_num))
    normalized = normalize_product_name(name)
    product_aliases = get_product_aliases(set_num, name, aliases)
    full_name_key = _ascii(normalized.full_name).casefold()
    terms = (
        normalized.short_name,
        product_aliases.canonical_name,
        *(
            alias for alias in product_aliases.aliases
            if _ascii(alias).casefold() != full_name_key
        ),
    )
    queries = [f"LEGO {root}"]
    seen = {queries[0].casefold()}
    for term in terms:
        clean = " ".join(_ascii(term).split())
        if len(clean.split()) > 5:
            continue
        query = f"LEGO {root} {clean}"
        if clean and query.casefold() not in seen:
            queries.append(query)
            seen.add(query.casefold())
        if len(queries) >= max_queries:
            break

    return EbayQueryPlan(
        set_num=set_num,
        name=normalized,
        aliases=product_aliases,
        queries=tuple(queries),
    )
