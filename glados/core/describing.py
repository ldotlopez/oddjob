"""What `describe` and the commands that call it share: the reply language,
the system prompt and the (cached) describer backend."""

from __future__ import annotations

import contextlib
import locale

from glados.core.cache import open_user_cache
from glados.core.session import Glados
from glados.lib.describe import CachedDescriber, DescriptionSettings
from glados.lib.language import language_name, locale_language
from glados.lib.protocols import Describer


def system_language() -> str | None:
    """The language name of the user's message locale (LC_ALL, LC_MESSAGES,
    LANG), or None when it is unset, unavailable or names no language."""
    try:
        locale.setlocale(locale.LC_MESSAGES, "")
    except locale.Error:
        return None
    return locale_language(locale.getlocale(locale.LC_MESSAGES)[0])


def describe_prompt(
    glados: Glados, instructions: str | None, language: str | None
) -> str:
    """The describe system prompt, replying in `language` or else the
    system locale's."""
    reply_language = language_name(language) if language else system_language()
    return glados.config().prompts.render_describe(instructions, reply_language)


def open_describer(
    stack: contextlib.ExitStack,
    glados: Glados,
    backend: str | None,
    model: str | None,
    *,
    use_cache: bool,
) -> Describer:
    """The selected describe backend, behind the user cache unless
    `use_cache` is false. The cache is closed with `stack`."""
    overrides = {"model": model}

    def make_describer() -> Describer:
        return glados.backend("describe", Describer, backend, overrides)

    if not use_cache:
        return make_describer()
    return CachedDescriber(
        stack.enter_context(open_user_cache()),
        make_describer,
        DescriptionSettings(*glados.backend_options("describe", backend, overrides)),
    )
