"""Language names for prompts: turning a locale or a `--language` value into
the name a model understands ("es_ES.UTF-8" -> "Spanish (Spain)")."""

from __future__ import annotations

import re

import langcodes

_ENCODING_OR_MODIFIER = re.compile(r"[.@].*$")


def language_name(value: str) -> str:
    """The English name of `value` when it is a language code ('es',
    'pt-BR'); any other text ('Spanish', 'formal French') is returned as it
    is, since it already names the language for a model."""
    tag = value.strip().replace("_", "-")
    if langcodes.tag_is_valid(tag):
        return langcodes.Language.get(tag).display_name()
    return value.strip()


def locale_language(locale_name: str | None) -> str | None:
    """The language name of a POSIX locale such as 'es_ES.UTF-8', or None for
    no locale and for the 'C' and 'POSIX' locales, which name no language."""
    if not locale_name:
        return None
    tag = _ENCODING_OR_MODIFIER.sub("", locale_name).replace("_", "-")
    if not langcodes.tag_is_valid(tag):
        return None
    return langcodes.Language.get(tag).display_name()
