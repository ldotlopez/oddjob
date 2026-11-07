"""Import boundaries of the repository.

- filejobs, the backend-free core, imports nothing from glados.
- glados.lib, the domain modules, knows nothing about config, backends or
  the CLI: it imports none of glados.core, glados.plugins and
  glados.commands. glados.plugins (the backends) build on glados.lib only,
  never on glados.core or glados.commands.
- `cli.py` holds the click group and `commands/<command>.py` one click
  command each; every other module is domain or core code with no CLI. So
  click is imported only there and in the shared CLI plumbing
  (`filejobs/cli_*.py`, `glados/core/cli_*.py`).
"""

import ast
import unittest
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("filejobs", "glados", "multitool")

# Packages whose modules may import click: plumbing named `cli_*.py`.
CLI_PLUMBING = (Path("filejobs"), Path("glados/core"))

CLICK_MODULES = ("click", "rich_click")


def imported_modules(source: Path) -> Iterator[str]:
    """Every absolute module name `source` imports. `from a import b` yields
    both `a` and `a.b`, since `b` may be a submodule."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def imports_any(module: str, targets: tuple[str, ...]) -> bool:
    """Whether `module` is one of `targets` or a submodule of one."""
    return any(module == t or module.startswith(f"{t}.") for t in targets)


def sources(package: str) -> list[Path]:
    return sorted((ROOT / package).rglob("*.py"))


def violations(package: str, forbidden: tuple[str, ...]) -> list[str]:
    """`file: module` for each import in `package` of a forbidden module or
    one of its submodules."""
    return [
        f"{source.relative_to(ROOT)}: {module}"
        for source in sources(package)
        for module in imported_modules(source)
        if imports_any(module, forbidden)
    ]


def may_import_click(relative: Path) -> bool:
    """Entry points, command modules and the shared CLI plumbing."""
    return (
        relative.name == "cli.py"
        or "commands" in relative.parts[:-1]
        or (relative.parent in CLI_PLUMBING and relative.stem.startswith("cli_"))
    )


class BoundaryTests(unittest.TestCase):
    def test_filejobs_imports_no_glados(self) -> None:
        self.assertEqual(violations("filejobs", ("glados", "multitool")), [])

    def test_lib_knows_no_config_backends_or_cli(self) -> None:
        forbidden = ("glados.core", "glados.plugins", "glados.commands")
        self.assertEqual(violations("glados/lib", forbidden), [])

    def test_plugins_build_on_lib_only(self) -> None:
        forbidden = ("glados.core", "glados.commands")
        self.assertEqual(violations("glados/plugins", forbidden), [])

    def test_click_only_in_entry_points_and_commands(self) -> None:
        found = [
            violation
            for package in PACKAGES
            for violation in violations(package, CLICK_MODULES)
            if not may_import_click(Path(violation.split(":")[0]))
        ]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
