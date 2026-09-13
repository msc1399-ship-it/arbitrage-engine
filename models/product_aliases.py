from __future__ import annotations

import unicodedata
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ProductAliases:
    canonical_name: str
    aliases: tuple[str, ...] = ()


PRODUCT_ALIASES: dict[str, ProductAliases] = {
    "10295": ProductAliases(
        canonical_name="Porsche 911",
        aliases=("Porsche Turbo", "Porsche Targa", "911 Turbo", "911 Targa"),
    ),
    "75308": ProductAliases(canonical_name="R2-D2", aliases=("R2D2", "R2 D2")),
    "42115": ProductAliases(
        canonical_name="Lamborghini Sian",
        aliases=("Sian FKP 37", "Lamborghini FKP37"),
    ),
    "21318": ProductAliases(
        canonical_name="Tree House",
        aliases=(
            "Treehouse", "Casa del Arbol", "Baumhaus",
            "Cabane dans l arbre", "Casa sull albero",
        ),
    ),
    "10300": ProductAliases(
        canonical_name="Back to the Future",
        aliases=(
            "Time Machine", "DeLorean", "Regreso al Futuro",
            "Maquina del Tiempo", "Ritorno al Futuro",
        ),
    ),
}


def _key(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode()
        .casefold()
    )


def get_product_aliases(
    set_num: str,
    name: str,
    extra_aliases: tuple[str, ...] | list[str] = (),
) -> ProductAliases:
    """Return configured and caller-provided aliases without duplicates."""
    root = re.sub(r"-\d+$", "", str(set_num))
    configured = PRODUCT_ALIASES.get(root)
    canonical = configured.canonical_name if configured else name.strip()
    candidates = (name, *(configured.aliases if configured else ()), *extra_aliases)
    aliases = []
    seen = {_key(canonical)}
    for candidate in candidates:
        clean = " ".join(str(candidate).split())
        normalized = _key(clean)
        if clean and normalized not in seen:
            aliases.append(clean)
            seen.add(normalized)
    return ProductAliases(canonical_name=canonical, aliases=tuple(aliases))
