"""translate: which file name a translation lands at.

The translation itself is a single TextStep on the Translator backend; the
only task logic is turning the free-text target language into the infix
of the output name (notes.txt -> notes.es.txt, notes.brazilian-portuguese.txt).
"""

from __future__ import annotations

import re

_NOT_NAME_CHARACTERS = re.compile(r"[^\w]+")


def language_infix(language: str) -> str:
    """`language` lowercased, every run of non-word characters turned into
    one '-', trimmed of '-' at the ends. ValueError if nothing is left."""
    infix = _NOT_NAME_CHARACTERS.sub("-", language.lower()).strip("-_")
    if not infix:
        raise ValueError(f"language gives no usable file name infix: {language!r}")
    return infix
