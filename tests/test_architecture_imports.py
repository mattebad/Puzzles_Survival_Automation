"""Import-direction guard for the canonical runtime package (issue #22).

``automation_service`` is the canonical runtime owner; ``scripts/`` is the legacy operator layer
that wires it. ``scripts.pnsctl`` imports ``automation_service``, so the reverse edge would be a
cycle. The scan is purely static (AST) and includes function-level imports, which is how the
original cycle was hidden.
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = REPO_ROOT / "automation_service"
SCRIPTS_ROOT = REPO_ROOT / "scripts"

# Ratchet: number of distinct (automation_service module, scripts module) import edges.
# Lower it whenever an edge is removed; never raise it.
MAX_AUTOMATION_SERVICE_TO_SCRIPTS_EDGES = 40


def _service_module(path: Path) -> str:
    parts = path.relative_to(REPO_ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _scripts_edges(source: str, package: list[str]) -> set[str]:
    """Return every ``scripts.*`` module imported anywhere in ``source`` (any nesting depth)."""

    targets: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            if module == "scripts":
                # ``from scripts import x`` imports the submodule ``scripts.x``.
                targets.update(f"scripts.{alias.name}" for alias in node.names)
            else:
                targets.add(module)
    return {target for target in targets if target == "scripts" or target.startswith("scripts.")}


def _all_edges() -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for path in sorted(SERVICE_ROOT.rglob("*.py")):
        module = _service_module(path)
        package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
        edges.update((module, target) for target in _scripts_edges(path.read_text(encoding="utf-8"), package))
    return edges


class AutomationServiceImportDirectionTests(unittest.TestCase):
    def test_automation_service_never_imports_pnsctl(self) -> None:
        offenders = sorted(edge for edge in _all_edges() if edge[1] == "scripts.pnsctl"
                           or edge[1].startswith("scripts.pnsctl."))
        self.assertEqual(offenders, [], "automation_service must not import scripts.pnsctl (cycle)")

    def test_automation_service_to_scripts_edges_do_not_grow(self) -> None:
        edges = sorted(_all_edges())
        self.assertLessEqual(
            len(edges),
            MAX_AUTOMATION_SERVICE_TO_SCRIPTS_EDGES,
            f"{len(edges)} automation_service -> scripts edges exceed the ratchet "
            f"({MAX_AUTOMATION_SERVICE_TO_SCRIPTS_EDGES}); edges: {edges}",
        )

    def test_scan_sees_function_level_and_aliased_imports(self) -> None:
        source = (
            "import scripts.alpha\n"
            "from scripts import beta, gamma as g\n"
            "def lazy():\n"
            "    from scripts.delta import thing\n"
            "    class Inner:\n"
            "        def method(self):\n"
            "            import scripts.epsilon.sub\n"
            "from tasks import unrelated\n"
            "from . import sibling\n"
        )
        self.assertEqual(
            _scripts_edges(source, ["automation_service"]),
            {"scripts.alpha", "scripts.beta", "scripts.gamma", "scripts.delta", "scripts.epsilon.sub"},
        )


if __name__ == "__main__":
    unittest.main()
