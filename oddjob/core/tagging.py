"""What `tag` needs from the session: the backends of the tasks it composes
(rewrite, describe, transcribe), each as configured for its own task, and
its system prompt in the reply language."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from oddjob.core.describing import system_language
from oddjob.core.session import Session
from oddjob.lib.language import language_name
from oddjob.lib.protocols import Describer, Rewriter, Transcriber


class SessionBackends:
    """lib.tag.TaskBackends over the session: each task's backend is the
    one selected for it (`[tasks]`, ODDJOB_<TASK>_BACKEND, the only one
    installed), loaded only when called."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def rewriter(self) -> Rewriter:
        return self.session.backend("rewrite", Rewriter)

    def describer(self) -> Describer:
        return self.session.backend("describe", Describer)

    def transcriber(self) -> Transcriber:
        return self.session.backend("transcribe", Transcriber)

    def settings(self, task: str) -> tuple[str, Mapping[str, Any]]:
        return self.session.backend_options(task)


def tag_prompt(session: Session, language: str | None) -> str:
    """The tag system prompt, replying in `language` or else the system
    locale's."""
    reply_language = language_name(language) if language else system_language()
    return session.config().prompts.render_tag(reply_language)
