"""Import-direction guard for the canonical runtime package (issue #22).

``automation_service`` is the canonical runtime owner; ``scripts/`` is the legacy operator layer
that wires it. ``scripts.pnsctl`` imports ``automation_service``, so the reverse edge would be a
cycle. The scan is purely static (AST) and includes function-level imports and literal
``__import__``/``import_module`` calls, which is how the original cycle was hidden. It also follows
``scripts`` modules transitively: the ``flow_delivery_*`` wrappers reach ``scripts.pnsctl`` through
their lazy ``_pnsctl()`` shim, so a service import of such a wrapper is still a cycle.
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

# Known remaining debt (#22): service edges whose scripts module reaches scripts.pnsctl
# transitively. Remove an entry when its chain is broken; never add one.
KNOWN_INDIRECT_PNSCTL_EDGES = frozenset({
    ("automation_service.bioenhancer", "scripts.flow_delivery_bioenhancer_bluestacks"),
    ("automation_service.campaign", "scripts.flow_delivery_campaign_bluestacks"),
    ("automation_service.enhancement", "scripts.flow_delivery_enhancement_bluestacks"),
    ("automation_service.personal_might", "scripts.flow_delivery_personal_might_bluestacks"),
    ("automation_service.supply", "scripts.flow_delivery_supply_depot_bluestacks"),
    ("automation_service.ultimate", "scripts.flow_delivery_ultimate_challenge_bluestacks"),
})

_DYNAMIC_IMPORTERS = {"__import__", "import_module"}


def _service_module(path: Path) -> str:
    parts = path.relative_to(REPO_ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _scripts_edges(source: str, package: list[str]) -> set[str]:
    """Return every ``scripts.*`` module imported anywhere in ``source`` (any nesting depth)."""

    targets: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in _DYNAMIC_IMPORTERS and isinstance(node.args[0].value, str):
                targets.add(node.args[0].value)
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


def _module_path(module: str) -> Path | None:
    base = REPO_ROOT.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _reaches_pnsctl(start: str) -> bool:
    """Whether ``start`` (a scripts module) imports ``scripts.pnsctl`` directly or via other scripts modules."""

    seen, pending = {start}, [start]
    while pending:
        module = pending.pop()
        if module == "scripts.pnsctl" or module.startswith("scripts.pnsctl."):
            return True
        path = _module_path(module)
        if path is None:
            continue
        package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
        for target in _scripts_edges(path.read_text(encoding="utf-8"), package) - seen:
            seen.add(target)
            pending.append(target)
    return False


class AutomationServiceImportDirectionTests(unittest.TestCase):
    def test_automation_service_never_imports_pnsctl(self) -> None:
        offenders = sorted(edge for edge in _all_edges() if edge[1] == "scripts.pnsctl"
                           or edge[1].startswith("scripts.pnsctl."))
        self.assertEqual(offenders, [], "automation_service must not import scripts.pnsctl (cycle)")

    def test_no_new_indirect_pnsctl_cycles(self) -> None:
        indirect = {edge for edge in _all_edges() if _reaches_pnsctl(edge[1])}
        self.assertEqual(sorted(indirect - KNOWN_INDIRECT_PNSCTL_EDGES), [],
                         "new automation_service import reaches scripts.pnsctl through scripts (cycle)")
        self.assertEqual(sorted(KNOWN_INDIRECT_PNSCTL_EDGES - indirect), [],
                         "chain broken: remove it from KNOWN_INDIRECT_PNSCTL_EDGES")

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
            "zeta = __import__('scripts.zeta', fromlist=['x'])\n"
            "eta = importlib.import_module('scripts.eta')\n"
            "__import__('argparse')\n"
            "from tasks import unrelated\n"
            "from . import sibling\n"
        )
        self.assertEqual(
            _scripts_edges(source, ["automation_service"]),
            {"scripts.alpha", "scripts.beta", "scripts.gamma", "scripts.delta", "scripts.epsilon.sub",
             "scripts.zeta", "scripts.eta"},
        )


if __name__ == "__main__":
    unittest.main()
