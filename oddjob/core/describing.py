"""What `describe` and the commands that call it share: the reply language,
the system prompt and the (cached) describer backend."""

from __future__ import annotations

import contextlib
import locale

from oddjob.core.cache import open_user_cache
from oddjob.core.session import Session
from oddjob.lib.describe import CachedDescriber, DescriptionSettings
from oddjob.lib.language import language_name, locale_language
from oddjob.lib.protocols import Describer


def system_language() -> str | None:
    """The language name of the user's message locale (LC_ALL, LC_MESSAGES,
    LANG), or None when it is unset, unavailable or names no language."""
    try:
        locale.setlocale(locale.LC_MESSAGES, "")
    except locale.Error:
        return None
    return locale_language(locale.getlocale(locale.LC_MESSAGES)[0])


def describe_prompt(
    session: Session, instructions: str | None, language: str | None
) -> str:
    """The describe system prompt, replying in `language` or else the
    system locale's."""
    reply_language = language_name(language) if language else system_language()
    return session.config().prompts.render_describe(instructions, reply_language)


def open_describer(
    stack: contextlib.ExitStack,
    session: Session,
    backend: str | None,
    model: str | None,
    *,
    use_cache: bool,
) -> Describer:
    """The selected describe backend, behind the user cache unless
    `use_cache` is false. The cache is closed with `stack`."""
    overrides = {"model": model}

    def make_describer() -> Describer:
        return session.backend("describe", Describer, backend, overrides)

    if not use_cache:
        return make_describer()
    return CachedDescriber(
        stack.enter_context(open_user_cache()),
        make_describer,
        DescriptionSettings(*session.backend_options("describe", backend, overrides)),
    )
