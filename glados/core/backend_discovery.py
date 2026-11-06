"""Backend discovery, built on foundation.plugin.Register.

Lives in core/, not backends/ — it's the mechanism that discovers
backends, not a backend itself. Keeping it out of the glados.backends
namespace matters concretely: Register.discover() enumerates every
module directly under that namespace, so if this module lived inside
it, discover() would list it too and register_all() would attempt (and
harmlessly fail) to register it as a plugin.

One shared Register instance covers the whole namespace — a single
backend module can implement several task Protocols at once (e.g. a
future OpenAI-compatible backend registering Rewriter, Summarizer,
Expander and Describer together), so there's exactly one place tracking
"what's been loaded", queried per-task by whichever Protocol that task
cares about.
"""

from __future__ import annotations

from foundation.plugin import Register

_NAMESPACE = "glados.backends"
_ENTRY_POINT = "register"

_register = Register(ns=_NAMESPACE, entry_point=_ENTRY_POINT)
_loaded = False


def _ensure_loaded() -> None:
    """Register every backend module found under glados.backends, once
    per process. discover() enumerates them automatically — no more
    hand-maintained module list — and register_all()'s best-effort
    semantics mean a backend that fails to load (e.g. a missing optional
    dependency) is skipped rather than taking down discovery for every
    other backend.
    """
    global _loaded
    if _loaded:
        return
    _register.register_all(_register.discover())
    _loaded = True


def backends_for(protocol: type) -> dict[str, object]:
    """Return {object_name: instance} for every backend implementing
    `protocol`. `object_name` is the per-object name each backend chose
    in its register() triples (see whisper_backend.register()'s
    "whisper") — used directly as the -b/--backend CLI value; it's
    scoped per-plugin, not globally unique, so two different plugin
    modules picking the same object_name would collide here (acceptable
    for now — nothing stops a future backend from choosing a
    distinguishing name).
    """
    _ensure_loaded()
    return {
        object_name: obj
        for _plugin_name, object_name, obj in _register.get_by_protocol(protocol)
    }
