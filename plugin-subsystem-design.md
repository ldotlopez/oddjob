# Plugin subsystem: design and decisions

A portable description of newstool's plugin subsystem, written to be adopted
by another project. It states the design, the reasons behind each choice and
the alternatives that were tried and dropped. newstool names (`newstool`,
`provider`, `sink`...) appear as examples; replace them with your domain's.

Sources: `docs/ARCHITECTURE.md`, decisions 0003, 0006, 0007, 0009, 0010 and
0013, `newstool/plugins/__init__.py`, `newstool/catalog.py` and the protocol
modules (`providers.py`, `processors.py`, `remixers.py`, `sinks.py`,
`llms.py`).

---

## 1. Goals

1. The core never imports a plugin's code. It knows only typed protocols.
2. Adding a plugin means dropping one module into a package; no core edit, no
   registration list to maintain.
3. Every configuration error (unknown plugin, bad option, missing dependency
   between runs) fails **at startup**, with the config path of the offending
   value, before any database or network is touched.
4. A plugin can be used several times with different options (two Telegram
   chats, two summarizers with different prompts) without the plugin knowing.
5. Expensive objects (LLM clients, connections) are built only when a run
   actually needs them.
6. Plugins are testable in isolation, with fakes for the shared resources.

---

## 2. Vocabulary

| Term | Meaning |
| :--- | :--- |
| **Bundle** | One Python module in the plugin namespace package (`app.plugins.<name>`). It may provide any number of classes of any types. |
| **Entry point** | Module-level function `__app_plugin__()` returning the bundle's classes. |
| **Type name** | The name a class is registered under (`summarize`, `telegram`). Unique per protocol, not globally. What the config refers to. |
| **Instance protocol** | What the core calls on an object: `Provider.retrieve_items`, `Processor.process`, `Sink.deliver`... |
| **Type protocol** | What the core requires of the *class*: `options_model`, `__call__(options, services)`, plus class methods the core needs before any object exists (`output_key`, `required_key`). |
| **Options model** | A pydantic model, one per class, validating that class's options. |
| **Section** | `plugins.<type name>` in config: default options for every use of that type. Builds nothing. |
| **Catalog** | The config lists of uses (`sources`, `processors`, `remixers`, `sinks`, `llms`). Each entry is a type name or `{<type>, id, key, options}`. |
| **Profile** | A resolved use: (class, validated options, config location). One object per profile, built lazily. |
| **Run** | A workflow's execution of a profile under a key. Several runs may share a profile and its object. |
| **Services** | One dataclass of shared resources (`db`, `fetcher`, `llm_factory`) handed to every constructor. |
| **Key** | The name under which a run's output is stored (annotation key, artifact namespace, ledger key). Defaults from the class; config may rename it. Never the type name implicitly. |

---

## 3. Architecture at a glance

```
plugins/<bundle>.py ──__app_plugin__()──► [(type name, TypeProtocol, cls), ...]
                                                   │
                         ClassRegister.register_found()   (imports every module)
                                                   │
                         ClassRegister.classes(TypeProtocol) -> {name: cls}
                                                   │   checks: is a class, conforms,
                                                   │   name unique per protocol
config.yaml ─► Config ─► Catalog(config, register)
                           ├─ check plugins.<type> sections against options_model
                           ├─ Profile per use: merge(section, entry.options) → validate
                           ├─ Run per workflow entry (workflow, key, profile)
                           └─ cross-run checks (keys written/read, LLM refs)
                                                   │   (all errors: ConfigError with path)
Application ─ builds Services once
            └─ _object(profile): cls(profile.options, services), cached per profile
                 └─ run.method(key=..., scope=...)
```

Startup order: register classes → build catalog (validates everything) →
open database → build objects on demand.

---

## 4. Discovery and registration

### Design

- One namespace package holds all plugins. Every module in it is imported on
  every command (`pkgutil.iter_modules` over the package's `__path__`).
- Each module exposes a zero-argument entry point:

  ```python
  def __app_plugin__() -> PluginTypes:
      return [
          ("telegram", SinkType, TelegramSink),
          ("telegram_artifacts", SinkType, TelegramArtifactSink),
      ]
  ```

  `type PluginTypes = list[tuple[str, type, type]]` — (type name, type
  protocol, class).
- The register indexes classes by declared type protocol. For each protocol it
  checks, raising a plugin error otherwise:
  1. the registered thing is a class, not an instance;
  2. `isinstance(cls, TypeProtocol)` holds (runtime-checkable protocol);
  3. the type name is not registered by another bundle under the same protocol.
- A module that fails to import, or whose entry point raises, fails **every**
  command. Broken plugins are not skipped silently.

### Reference implementation

```python
type PluginTypes = list[tuple[str, type, type]]

class ClassRegister(BaseRegister):          # BaseRegister: load module, call
    def register_found(self) -> None:       # entry point, store result by module
        for name in self.discover():
            self.register(name)

    def classes(self, protocol: type) -> dict[str, type]:
        classes: dict[str, type] = {}
        owners: dict[str, str] = {}
        for module in self._registry:
            for name, declared, cls in self.get(module):
                if declared is not protocol:
                    continue
                if not isinstance(cls, type):
                    raise PluginError(f"plugin '{module}' registered {protocol.__name__}"
                                      f" '{name}' as an instance, not a class")
                if not isinstance(cls, protocol):
                    raise ProtocolConformanceError(
                        f"plugin '{module}': {cls.__qualname__} does not conform"
                        f" to {protocol.__name__}")
                if name in owners:
                    raise PluginError(f"{protocol.__name__} '{name}' is registered by"
                                      f" both '{owners[name]}' and '{module}'")
                classes[name] = cls
                owners[name] = module
        return classes
```

The generic loader underneath (module loading by short name, entry-point
call, transactional registration, `discover()`) comes from newstool's internal
library `foundation.plugin`. Appendix A contains a self-contained copy of the
parts this design uses, so the subsystem can be adopted without that library.

### Why

- **Register classes, not instances** (decision 0010). An entry point that
  builds objects must receive options, so one module = one object = one set of
  options; a second use with other options is impossible. A class with an
  `options_model` *is* the factory; no separate factory functions.
- **Import everything, always.** Validating only what is named would let a
  broken plugin surface hours later in another cron line. Importing is cheap;
  building objects is what is deferred (section 7).
- **Declared protocol in the triple.** `runtime_checkable` protocols only check
  that attributes exist, not signatures, and a protocol whose members are a
  subset of another's matches both. The explicit declaration is the real
  discriminator; the `isinstance` check is a sanity net.

### Rejected

- One package and loader per plugin type: every new type needs a new package
  and loader, and related classes (two sinks sharing an HTTP helper) cannot
  live together.
- Loading a plugin only when the config names it: invalid options surface on
  first use, not at startup.
- Hand-written `importlib` factories per plugin.
- Factories or lazy wrappers registered per task argument: objects are built
  once, per-task inputs are method arguments.

---

## 5. Protocols: two per plugin type

Each plugin type has an **instance protocol** (what the core calls) and a
**type protocol** (what the core needs from the class). Both are
`@runtime_checkable typing.Protocol`s in a core module per type
(`providers.py`, `processors.py`, `remixers.py`, `sinks.py`, `llms.py`).

```python
@runtime_checkable
class Processor(Protocol):
    def process(self, *, key: str, scope: ProcessingScope | None = None,
                force: bool = False) -> RunSummary: ...

@runtime_checkable
class ProcessorType(Protocol):
    options_model: type[pydantic.BaseModel]
    def __call__(self, options: Any, services: Services) -> Processor: ...
    def output_key(self, options: Any) -> str: ...          # class method on impls
    def required_key(self, options: Any) -> str | None: ... # class method on impls
```

Rules:

- **Each instance protocol has a method name of its own**, named after the
  phase that calls it (`retrieve_items`, `process`, `remix`, `deliver`,
  `prompt`/`embed`). A shared `run()` made protocols indistinguishable to
  structural checks (remixers loaded as processors and vice versa).
- **Static facts are class methods on the type**, taking the validated options:
  which key a run writes (`output_key`), which key it reads (`required_key`).
  The catalog computes and cross-checks them at startup without building any
  object.
- **`name` is not part of any protocol.** As a data attribute it breaks
  structural checks; as a method it is noise. Base classes carry `name` as a
  class attribute (used to record who wrote an output); the registered type
  name comes from the triple.
- **A type can have alternative instance protocols.** `ProviderType.__call__`
  returns `Provider | PreflightProvider`; the core dispatches on
  `isinstance(obj, PreflightProvider)` (two-stage import: list cheap
  identifiers, fetch only what is new).
- **Protocols for the core, base classes for plugins.** The core depends only
  on protocols; plugins usually subclass an optional base (`BaseProcessor`,
  `BaseRemixer`, `BaseItemSink`, `IndexSiteProvider`) that implements the
  protocol method as a template and leaves one hook to fill (`process_item`,
  `produce`, `send`, `parse_index`/`parse_item`). Registering against base
  classes instead of protocols was rejected: it forces inheritance.

---

## 6. Options

### Model per class

```python
class PluginOptions(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")   # unknown keys are errors

class NoOptions(PluginOptions): ...

class UsesLLMOptions(PluginOptions):
    llm: str | None = None       # an `llms` id or LLM type; None = first entry

class SummarizeOptions(ProcessorOptions, UsesLLMOptions):
    model: str | None = None
    prompt: str = SUMMARY_PROMPT
```

- Every class declares `options_model`, a `PluginOptions` subclass with
  **defaults for the general case**, so a bare type name is a valid use.
- Shared option groups are mixin models (`ProcessorOptions` with
  `max_retries`, `DeliveryOptions` with `interval`, `max_per_run`, `lookback`,
  `UsesLLMOptions`). Composition by multiple inheritance of models.
- Secrets are `pydantic.SecretStr` so they never appear in a `repr` or
  traceback.
- Cross-field rules are model validators; they run per use, not on sections.
- An option holds its value for every call of its object. A value that changes
  per call is a method argument, not an option.

### Precedence and merge

Type defaults (the model) → `plugins.<type>` section → entry `options`.

```python
def merge_options(defaults: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for name, value in overrides.items():
        default = merged.get(name)
        if isinstance(default, Mapping) and isinstance(value, Mapping):
            merged[name] = merge_options(default, value)
        else:
            merged[name] = value       # scalars and lists replace whole
    return merged
```

Deep merge was chosen so nested defaults survive partial overrides; the cost
is that an inherited nested key cannot be unset.

### Sections

`plugins.<type name>` holds defaults for **every** use of that type. It builds
nothing. At startup each section must name a registered type, and each value is
checked against the type's model on its own (cross-field validators wait until
a use is validated, since a section may be deliberately partial).

```yaml
plugins:
  telegram:
    bot_token: ${TELEGRAM_BOT_TOKEN}   # default for every telegram use
sinks:
  - id: telegram-main
    sink: telegram
    options: {chat_id: "-100123", interval: 30m}
```

Sections are per **type**, not per bundle: `telegram` and `telegram_artifacts`
are separate sections even though one module provides both. Bundle sections
were rejected: a second namespace beside type names, and options whose meaning
depends on which class reads them.

### Errors

A `pydantic.ValidationError` becomes a `ConfigError` carrying the config path
of the value: `workflows.juntas.deliver.0.options.chat_id: Field required`,
`sources.some-blog.options.fetch_artcle: Extra inputs are not permitted`.

### Rejected

- Options split into a per-instance model and a per-use model
  (`use_options(overrides)`): an option could not be both, so two uses could
  not pick different LLMs; every plugin declared two models.
- Per-use options as keyword arguments bound to the method signature: each
  option declared twice, types unchecked until the call, `x or self.x`
  fallbacks that cannot unset a default.
- Option models owned or validated by the core: the core would know every
  plugin.
- A map of per-source values inside a plugin section (`source_id: value`): a
  mistyped id goes unnoticed and a source's settings live in two places.

---

## 7. Construction: one object per use, built lazily

```python
@dataclasses.dataclass(eq=False, slots=True)
class Profile:
    name: str                    # type name
    cls: Any
    options: pydantic.BaseModel  # validated
    location: str                # config path, for messages

class Application:
    def _object(self, profile: Profile) -> Any:
        if profile not in self._objects:
            self._objects[profile] = profile.cls(profile.options, self._services)
        return self._objects[profile]
```

- Uniform constructor: `cls(options, services)`. The object keeps
  `self.options` and whatever it takes from `services`.
- `Profile` compares by identity (`eq=False`): all runs that refer to one
  profile share one object.
- A bare type name used in several places resolves to **one** profile per type
  (the type with its section's options).
- Objects are built when a run first needs them, never at startup: a workflow
  without LLMs never builds an LLM client. Validation, by contrast, is eager
  and covers the whole catalog.

### Rejected

- Building every object at startup: pays for (and can fail on) unused
  connections.
- Setting dependencies on objects after construction: objects are incomplete
  in between.
- Inspecting constructor signatures to pass only what each declares: one
  uniform signature is simpler.

---

## 8. Services: shared resources at construction

```python
@dataclasses.dataclass(slots=True, kw_only=True)
class Services:
    db: Database
    fetcher: HTTPClient
    llm_factory: Callable[[str | None], LLM] | None = None

    def llm(self, name: str | None = None) -> LLM:
        if self.llm_factory is None:
            raise LLMUnavailableError("no llm is configured (`llms`)")
        return self.llm_factory(name)
```

- Built once by the application. Passed to every constructor, used or not.
- Resources that never change for an object (database, HTTP client) are taken
  in `__init__` and kept (`self.db`, `self.fetcher`). **Methods receive only
  per-run arguments** (`retrieve_items(source)`, `process(key=..., scope=...)`,
  hooks `process_item(item)`, `send(subject)`).
- Plugins that are themselves services (LLM backends) are reached through a
  factory on `Services`, resolved by config id or type name and built on first
  use (cached by profile like any other object).

```python
class SummarizeProcessor(BaseProcessor):
    def __init__(self, options: SummarizeOptions, services: Services) -> None:
        super().__init__(options, services)
        self.llm = services.llm(options.llm)
```

### Why one object rather than one argument per resource

A new resource would change every plugin's constructor; `Services` grows
instead (decision 0013). Passing resources per call repeated an argument that
never changes for an object.

### Plugin-provided services (LLMs)

History worth copying the conclusion of:

1. First, one bundle held the Ollama client and every processor using it; new
   consumers had to join the bundle.
2. Then LLM backends became their own plugin type, registered before
   consumers, looked up by name from `Services`; a missing LLM produced an
   `Unavailable*` stand-in object that logged an error when run. This made
   config order matter and hid configuration mistakes until run time.
3. Final (0010): LLMs are a catalog list (`llms:`) like everything else.
   A consumer names one with `llm:` (id or type; none = first entry). A name
   that resolves to nothing is a **startup `ConfigError`**. No stand-ins, no
   ordering constraints.

---

## 9. The catalog: configuration resolved against classes

`Catalog(config, register)` does all resolution and validation and builds
nothing. Its output is profiles and runs.

### Config shape

```yaml
plugins:            # defaults per type
  ollama: {api_base: http://localhost:11434}

llms: [ollama]
sources:
  - {id: some-blog, provider: feedreader, url: ..., options: {fetch_article: true}}
processors:
  - markdownify
  - {processor: summarize, key: summary/es, options: {prompt: "..."}, skip_default: true}
remixers: [digest]
sinks:
  - {id: telegram-main, sink: telegram, options: {chat_id: "..."}}

workflows:
  - name: juntas-channel
    sources: [juntagobiernolocal]
    process: [markdownify, summarize]          # catalog ids or type names
    deliver:
      - {sink: telegram, options: {chat_id: ..., interval: 30m}}   # own entry
```

- A catalog entry is a type name, or `{<type>: name, id, key, options}`.
- `id` names a use so workflows can refer to it; it must not equal a type name
  of its kind (no ambiguity in references).
- `key` names what the use writes; default from the class (`output_key`).
- A workflow entry is a catalog id, a type name, or an inline entry of its own
  (no `id`, no `skip_default`). **A reference cannot override options**: one
  id is one run, otherwise "same id, same run" needs its own checks.
- An implicit `default` workflow runs every catalog entry without
  `skip_default: true`, in order.

### Startup checks (all raise `ConfigError` with a path)

- every `plugins.<name>` section names a registered type; values type-check;
- every use names a registered type of the right kind;
- every use's merged options validate;
- ids are unique and are not type names; keys match a key pattern;
- one run per output key within a workflow; two *different* types writing the
  same key on shared inputs is an error (each would invalidate the other's
  version stamp and redo all work); same type with different options is a
  warning;
- every key a run reads (`required_key`) is written by some run on its inputs;
- every LLM reference resolves.

**The whole catalog is validated whatever workflow is run.** Each workflow
runs from its own cron line; validating only the active one would delay errors
by hours, and validating everything is cheap.

### Data model

```python
@dataclasses.dataclass(frozen=True, slots=True)
class Kind:            # a plugin type: label for messages + its type protocol
    label: str
    protocol: type

@dataclasses.dataclass(frozen=True, slots=True)
class Run:
    workflow: Workflow
    key: str
    profile: Profile
    location: str
```

---

## 10. Keys and identity

- What a run writes is stored under the run's **key**, never under the type
  name (which is only the default key). This lets the same class run twice with
  different options (`summary` and `summary/es`) and lets config rename outputs.
- Identity follows ownership: per-item outputs keyed by (item, key); global
  outputs (artifacts) by key, unique across workflows; external side-effect
  records (delivery ledger) by `<workflow>/<key>`.
- Renaming a key starts its outputs from scratch; that is a documented
  consequence, not a migration.
- Base classes stamp outputs with the class `name` (who wrote it) and an
  optional `version`; bumping `version` makes previous outputs stale.

---

## 11. Plugins never import each other

Bundles share data only through stored outputs, by key: `embed` stores vectors
as `<input>_embedding` annotations that `grouping.embeddings` reads; every
consumer of summaries reads the `summary` key. Code used by a single bundle
lives in that bundle. Dependencies are declared (`requires` / `required_key`)
and checked at startup, so a missing producer is a config error.

---

## 12. Separating derived work from side effects

Plugin types were split by the nature of what they produce, not by item vs.
collection:

| Type | Input → output | Regenerable | Side effects |
| :--- | :--- | :--- | :--- |
| Provider | outside world → items | — | reads only |
| Processor | item → annotation | yes (`--force`) | none |
| Remixer | many items/annotations → artifacts | yes (every run) | none |
| Sink | items/artifacts → outside world + ledger | **no** | yes |
| LLM | service used by others | — | — |

A remixer once posted to Telegram and kept its state in an artifact; that
made `remix` unsafe to re-run and put records of external facts in
regenerable storage. Side effects moved to a dedicated type with its own
ledger table, states (`queued`, `sending`, `done`, `error`), and a template
cycle in the base class (queue → select/pace → send), so a sink plugin only
implements `send(subject) -> external_ref`.

---

## 13. Errors from plugins

- A plugin reports an **expected** failure (page without the expected
  structure, empty LLM answer, API rejection) by raising `PluginFailure` with a
  message written for the user. It subclasses `ValueError` so existing
  `except ValueError` skip-paths keep working.
- `EXPECTED_ERRORS = (PluginFailure, *network, LLM backend, DB operational
  errors)`: logged as one line; traceback only with debug logging.
- Anything else is unexpected and always logged with its traceback.
- Per-item failure semantics live in base classes: in processors `SkipItem`
  marks the item `ignored`, any other exception `error` with retry/backoff.
- Plugins whose URLs or payloads embed secrets re-raise request errors
  `from None` with the class only.

---

## 14. Writing a plugin (checklist)

```python
from ..processors import BaseProcessor, ProcessorOptions, ProcessorType
from . import PluginTypes, Services, UsesLLMOptions

class SummarizeOptions(ProcessorOptions, UsesLLMOptions):
    model: str | None = None

class SummarizeProcessor(BaseProcessor):
    name = "summarize"          # who wrote the output
    key = "summary"             # default output key
    requires = "markdown"       # key it reads; checked at startup
    options_model = SummarizeOptions
    options: SummarizeOptions

    def __init__(self, options: SummarizeOptions, services: Services) -> None:
        super().__init__(options, services)
        self.llm = services.llm(options.llm)

    def process_item(self, item: SourceItem) -> str:
        ...

def __app_plugin__() -> PluginTypes:
    return [(SummarizeProcessor.name, ProcessorType, SummarizeProcessor)]
```

1. One module in the plugin package; expose the entry point.
2. Subclass the type's base class; fill the hook.
3. Declare `options_model` with defaults for the common case; secrets as
   `SecretStr`.
4. Declare `name`, default `key` and `requires` as class attributes (or
   override `output_key` / `required_key` when they depend on options).
5. Take resources from `services` in `__init__`; keep methods per-run.
6. Raise `PluginFailure` for expected failures.
7. Keep parsing pure (`bytes -> model`) so tests run offline on saved samples;
   build the object in tests with `Services(db=fake_db, fetcher=fake_fetcher)`.

---

## 15. Consequences and trade-offs to accept

- A broken plugin module fails every command, including read-only ones.
- Every protocol needs a distinct method name; a protocol whose members are a
  subset of another's is ambiguous to structural checks.
- `services` is passed to every constructor even when unused.
- Deep option merge cannot unset an inherited nested key.
- Renaming a source id or a run key restarts that data from scratch; renaming
  a pure catalog `id` changes nothing stored.
- Configurations that share storage are not checked against each other.
- Adding a resource to `Services` is cheap; adding a method argument to a
  protocol changes every plugin.

---

## 16. Evolution summary (why it looks like this)

| Stage | Shape | Problem that forced the next |
| :--- | :--- | :--- |
| 1 | Hand-written `importlib` factories, pipelines in core | Every plugin needed core edits. |
| 2 | One package + `ClassLoader` per type, objects built per use | New type = new loader; related plugins couldn't share code or options. |
| 3 | One namespace, entry point receives `**options`, returns **instances** (one object per module) | Two uses of one plugin with different options impossible; per-instance vs per-use option split; LLM ordering constraints; `Unavailable*` stand-ins. |
| 4 (0010) | Entry point returns **classes**; one object per configured use; sections are per-type defaults; catalog validates all at startup | Shared resources still threaded through every method. |
| 5 (0013) | `Services` (db, fetcher, llm factory) at construction; methods take only per-run args; every reader declares `required_key` | — current — |

---

## Appendix A: self-contained registry code

This is everything the registry needs: the error hierarchy, `ModuleLoader`,
`BaseRegister` (the parts of `foundation.plugin` this design uses, with the
same behavior) and `ClassRegister`, newstool's subclass of it. Two modules:
a generic one (`plugin_loader.py`) and the application's plugin package
`__init__`.

Not copied, because the design does not use them: `ClassLoader`, `Register`
(the registry for entry points that return instances), `Lazy`, and
`BaseRegister.register_all` (best-effort registration that skips broken
modules). Section 4 explains why broken modules must not be skipped.

### `plugin_loader.py` (generic)

```python
"""Loads modules from a namespace package and stores what each module's
entry point returns.

- Nothing is imported until `register()` or `discover()` is called.
- Every failure is a `PluginError` subclass, never a raw ImportError or
  AttributeError.
- `register()` is transactional: the module is loaded and its entry point
  called before anything is stored, so a failure leaves the registry as it
  was.
- Registering the same name twice raises; nothing is silently overwritten.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Any

__all__ = [
    "AlreadyRegisteredError",
    "BaseRegister",
    "EntryPointError",
    "EntryPointMissingError",
    "ModuleLoader",
    "NotRegisteredError",
    "PluginError",
    "PluginImportError",
    "PluginNotFoundError",
    "ProtocolConformanceError",
]


class PluginError(Exception):
    """Base class for all plugin-system errors."""


class PluginNotFoundError(PluginError):
    """No module of the given name exists in the namespace."""


class PluginImportError(PluginError):
    """The module exists but raised while being imported."""


class EntryPointMissingError(PluginError):
    """The module has no entry point attribute."""


class EntryPointError(PluginError):
    """The module's entry point raised when called."""


class AlreadyRegisteredError(PluginError):
    """`register()` was called again for a registered name."""


class NotRegisteredError(PluginError):
    """`get()` was called for a name that is not registered."""


class ProtocolConformanceError(PluginError):
    """A registered class does not conform to the Protocol it was declared
    under."""


class ModuleLoader:
    """Loads modules by short name from a fixed namespace package."""

    def __init__(self, ns: str) -> None:
        self.ns = ns

    def load(self, name: str) -> ModuleType:
        """Import and return the module `{ns}.{name}`.

        A missing module is a `PluginNotFoundError`; a module that raises
        while importing, including one whose own dependency is missing, is a
        `PluginImportError`.
        """
        full_name = f"{self.ns}.{name}"
        try:
            return importlib.import_module(full_name)
        except ModuleNotFoundError as e:
            if e.name == full_name:
                raise PluginNotFoundError(
                    f"No plugin named {name!r} in namespace {self.ns!r}"
                ) from e
            raise PluginImportError(
                f"Module {full_name!r} failed to import due to missing "
                f"dependency {e.name!r}"
            ) from e
        except Exception as e:
            raise PluginImportError(
                f"Module {full_name!r} raised while importing: {e}"
            ) from e

    def discover(self) -> list[str]:
        """The sorted short names of every module directly under the
        namespace (one level, not recursive). Only the namespace package is
        imported, so a broken module is still listed."""
        try:
            namespace_module = importlib.import_module(self.ns)
        except ModuleNotFoundError as e:
            if e.name == self.ns:
                raise PluginNotFoundError(
                    f"Namespace {self.ns!r} does not exist"
                ) from e
            raise PluginImportError(
                f"Namespace {self.ns!r} failed to import due to missing "
                f"dependency {e.name!r}"
            ) from e
        except Exception as e:
            raise PluginImportError(
                f"Namespace {self.ns!r} raised while importing: {e}"
            ) from e

        return sorted(
            module_info.name
            for module_info in pkgutil.iter_modules(namespace_module.__path__)
        )


def _resolve_attr(
    module: ModuleType, attr_name: str, missing_error: type[PluginError]
) -> Any:
    """`getattr(module, attr_name)`, or `missing_error` if it is not there."""
    try:
        return getattr(module, attr_name)
    except AttributeError as e:
        raise missing_error(
            f"Module {module.__name__!r} has no attribute {attr_name!r}"
        ) from e


class BaseRegister:
    """Calls each module's entry point and stores its return value, as is,
    under the module's short name."""

    def __init__(self, ns: str, entry_point: str) -> None:
        self.ns = ns
        self.entry_point = entry_point
        self._module_loader = ModuleLoader(ns)
        self._registry: dict[str, Any] = {}

    def register(self, name: str, *args: Any, **kwargs: Any) -> None:
        """Load module `name`, call its entry point with `args` and
        `kwargs`, and store the result. Nothing is stored unless every step
        succeeds."""
        if name in self._registry:
            raise AlreadyRegisteredError(f"{name!r} is already registered")

        module = self._module_loader.load(name)
        entry_point_fn = _resolve_attr(module, self.entry_point, EntryPointMissingError)

        try:
            result = entry_point_fn(*args, **kwargs)
        except Exception as e:
            raise EntryPointError(
                f"Entry point {module.__name__}.{self.entry_point} raised: {e}"
            ) from e

        self._registry[name] = result

    def discover(self) -> list[str]:
        """The module names available in the namespace."""
        return self._module_loader.discover()

    def get(self, name: str) -> Any:
        """What module `name`'s entry point returned."""
        try:
            return self._registry[name]
        except KeyError as e:
            raise NotRegisteredError(f"{name!r} has not been registered") from e
```

### `app/plugins/__init__.py` (the application's plugin package)

The registry, the option base models, `merge_options` and `Services`, as
newstool has them. `Database`, `HTTPClient`, `LLM` and `LLMUnavailableError`
are the application's own types; replace them with yours.

```python
"""Plugin bundles. Every module is a bundle: it exposes `__app_plugin__()`,
which returns the classes it provides as `(type name, type Protocol, class)`
triples. The core builds one object of a class per configured use, with that
use's options.
"""

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

import pydantic

from ..db import Database
from ..httpclient import HTTPClient
from ..llms import LLM, LLMUnavailableError
from ..plugin_loader import BaseRegister, PluginError, ProtocolConformanceError

PLUGINS_NAMESPACE = __name__
PLUGIN_ENTRY_POINT = "__app_plugin__"

# What an entry point returns: (type name, type Protocol, class) per class.
type PluginTypes = list[tuple[str, type, type]]


class PluginOptions(pydantic.BaseModel):
    """Base for a plugin's options: unknown keys are errors."""

    model_config = pydantic.ConfigDict(extra="forbid")


class NoOptions(PluginOptions):
    """The options of an object that takes none."""


class UsesLLMOptions(PluginOptions):
    """Options of an object that uses an LLM: `llm` names an `llms` entry by
    id, or an LLM type; None is the first `llms` entry."""

    llm: str | None = None


def merge_options(
    defaults: Mapping[str, Any], overrides: Mapping[str, Any]
) -> dict[str, Any]:
    """`overrides` over `defaults`, merged key by key in nested mappings; any
    other value, lists included, replaces the default whole."""
    merged = dict(defaults)
    for name, value in overrides.items():
        default = merged.get(name)
        if isinstance(default, Mapping) and isinstance(value, Mapping):
            merged[name] = merge_options(default, value)
        else:
            merged[name] = value
    return merged


@dataclasses.dataclass(slots=True, kw_only=True)
class Services:
    """What the core shares with plugin objects: the database, the HTTP
    client, and `llm_factory`, which returns the LLM a name refers to (see
    `UsesLLMOptions`), built on first use."""

    db: Database
    fetcher: HTTPClient
    llm_factory: Callable[[str | None], LLM] | None = None

    def llm(self, name: str | None = None) -> LLM:
        """The LLM `name` refers to. Raise `LLMUnavailableError` if there is
        none."""
        if self.llm_factory is None:
            raise LLMUnavailableError("no llm is configured (`llms`)")
        return self.llm_factory(name)


class ClassRegister(BaseRegister):
    """A register of plugin classes: every entry point returns
    `PluginTypes`, and classes are looked up by their type Protocol."""

    def register_found(self) -> None:
        """Register every module of the namespace. A module that fails to
        load fails the whole register."""
        for name in self.discover():
            self.register(name)

    def classes(self, protocol: type) -> dict[str, type]:
        """The classes registered under `protocol`, by type name, in module
        order. Names are unique per protocol, and every class must conform
        to it."""
        classes: dict[str, type] = {}
        owners: dict[str, str] = {}
        for module in self._registry:
            for name, declared, cls in self.get(module):
                if declared is not protocol:
                    continue
                if not isinstance(cls, type):
                    raise PluginError(
                        f"plugin '{module}' registered {protocol.__name__} '{name}'"
                        " as an instance, not a class"
                    )
                if not isinstance(cls, protocol):
                    raise ProtocolConformanceError(
                        f"plugin '{module}': {cls.__qualname__} does not"
                        f" conform to {protocol.__name__}"
                    )
                if name in owners:
                    raise PluginError(
                        f"{protocol.__name__} '{name}' is registered by both"
                        f" plugin '{owners[name]}' and plugin '{module}'"
                    )
                classes[name] = cls
                owners[name] = module
        return classes
```

### Wiring at the entry point

```python
register = ClassRegister(PLUGINS_NAMESPACE, PLUGIN_ENTRY_POINT)
register.register_found()            # any PluginError: abort the command
catalog = Catalog(config, register)  # any ConfigError: abort the command
services = Services(db=db, fetcher=HTTPClient(cache=cache), llm_factory=app._llm)
```

Notes on using this code:

- Every type protocol must be `@runtime_checkable`; `classes()` checks
  conformance with `isinstance(cls, protocol)`.
- `classes()` compares the declared protocol by identity (`declared is
  protocol`), not by subclassing. A class is found only under the exact
  protocol its triple names.
- `ClassRegister` reads `BaseRegister._registry` directly, which assumes the
  two classes live in the same codebase. If the generic loader stays in a
  separate library, add a public method there that lists the registered
  names.

