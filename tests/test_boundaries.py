"""The import boundary between glados and multitool (decision 0003):
multitool uses only glados' backend-free core, and glados never imports
multitool."""

import ast
import unittest
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Backend-bound modules multitool must not import.
FORBIDDEN_FOR_MULTITOOL = (
    "glados.core.backends",
    "glados.core.config",
    "glados.core.cli_common",
    "glados.core.text_backend",
    "glados.plugins",
    "glados.tasks",
)


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


def violations(package: str, forbidden: tuple[str, ...]) -> list[str]:
    """`file: module` for each import in `package` of a forbidden module or
    one of its submodules."""
    found: list[str] = []
    for source in sorted((ROOT / package).rglob("*.py")):
        for module in imported_modules(source):
            if any(module == f or module.startswith(f"{f}.") for f in forbidden):
                found.append(f"{source.relative_to(ROOT)}: {module}")
    return found


class BoundaryTests(unittest.TestCase):
    def test_multitool_imports_only_the_backend_free_core(self) -> None:
        self.assertEqual(violations("multitool", FORBIDDEN_FOR_MULTITOOL), [])

    def test_glados_never_imports_multitool(self) -> None:
        self.assertEqual(violations("glados", ("multitool",)), [])


if __name__ == "__main__":
    unittest.main()
