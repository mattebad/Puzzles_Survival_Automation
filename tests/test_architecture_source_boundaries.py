"""Architecture guards: structural source boundaries between modules.

Unit tests assert behaviour. The invariants below are structural ("module X
must never import / reference Y"), so they are checked here, and only here, by
parsing each module with ``ast``. Comments are never inspected; docstrings and
other string constants are inspected only where a rule says so.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class BoundaryRule:
    """What one module (or package tree) must never import or reference."""

    reason: str
    targets: tuple[str, ...]
    # Case-insensitive substrings forbidden in any imported module/alias name.
    import_fragments: tuple[str, ...] = ()
    # Exact identifiers (Name, Attribute, def/class, argument, keyword, alias) forbidden.
    identifiers: tuple[str, ...] = ()
    # Substrings forbidden in identifiers and string constants (docstrings included).
    text_fragments: tuple[str, ...] = ()
    case_sensitive: bool = False
    # Fixed-length integer tuple literals (e.g. a hard-coded frame size) forbidden.
    integer_tuples: tuple[tuple[int, ...], ...] = ()


def _import_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        base = "." * node.level + (node.module or "")
        return [base, *(alias.name for alias in node.names)]
    return []


def _identifiers(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.keyword):
        return [node.arg] if node.arg else []
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [part for alias in node.names for part in (alias.name, alias.asname or "")]
    return []


def _dynamic_import_argument(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    function = node.func
    name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", None)
    argument = node.args[0]
    if name in {"import_module", "__import__"} and isinstance(argument, ast.Constant):
        return argument.value if isinstance(argument.value, str) else None
    return None


def boundary_violations(source: str, rule: BoundaryRule) -> list[tuple[int, str, str]]:
    """Return ``(line, kind, text)`` for every real violation of ``rule`` in ``source``."""

    fold = (lambda text: text) if rule.case_sensitive else str.lower
    import_fragments = tuple(fold(item) for item in rule.import_fragments)
    text_fragments = tuple(fold(item) for item in rule.text_fragments)
    exact = frozenset(rule.identifiers)
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", 0)
        imported = _import_names(node)
        dynamic = _dynamic_import_argument(node)
        if dynamic is not None:
            imported.append(dynamic)
        for name in imported:
            folded = fold(name)
            found.extend(
                (line, "import", name) for fragment in import_fragments if fragment in folded
            )
            found.extend((line, "text", name) for fragment in text_fragments if fragment in folded)
        for identifier in _identifiers(node):
            if identifier in exact:
                found.append((line, "identifier", identifier))
            folded = fold(identifier)
            found.extend(
                (line, "text", identifier) for fragment in text_fragments if fragment in folded
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            folded = fold(node.value)
            found.extend(
                (line, "text", node.value[:60]) for fragment in text_fragments if fragment in folded
            )
        if isinstance(node, ast.Tuple) and rule.integer_tuples:
            values = tuple(
                element.value
                for element in node.elts
                if isinstance(element, ast.Constant) and type(element.value) is int
            )
            if len(values) == len(node.elts) and values in rule.integer_tuples:
                found.append((line, "literal", repr(values)))
    return sorted(set(found))


def function_attribute_calls(source: str, function_name: str, attributes: frozenset[str]) -> list[int]:
    """Line numbers of ``.attr`` accesses (``attr`` in ``attributes``) inside one function."""

    functions = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ]
    if not functions:
        raise LookupError(function_name)
    return sorted(
        node.lineno
        for function in functions
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute) and node.attr in attributes
    )


def _package_files(*packages: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for package in packages
            for path in (REPO_ROOT / package).rglob("*.py")
            if "__pycache__" not in path.parts
        )
    )


RULES: dict[str, BoundaryRule] = {
    "home_safe_exit_has_no_dispatch_or_adb": BoundaryRule(
        reason="the Home safe-exit binder only binds evidence; it must never reach transport",
        targets=("tasks/bluestacks_home_safe_exit.py",),
        import_fragments=("adb", "pnsctl", "subprocess", "native_runtime", "scripts"),
        identifiers=(
            "dispatch_tap",
            "dispatch_swipe",
            "LocalBlueStacksRuntime",
            "ADBRunner",
            "connect_runtime",
        ),
        text_fragments=("input tap", "pnsctl", "adb "),
    ),
    "radial_semantics_is_adapter_neutral": BoundaryRule(
        reason="shared radial semantics must not know BlueStacks, ADB, pnsctl, cv2/numpy or a frame size",
        targets=("tasks/radial_semantics.py",),
        import_fragments=("cv2", "numpy", "adb", "pnsctl", "bluestacks", "native_runtime", "scripts"),
        identifiers=("CapturedNativeFrame", "dispatch_input", "runtime_profile_id"),
        text_fragments=("bluestacks", "unraid", "pnsctl", "adb ", "tap(", "dispatch_input"),
        integer_tuples=((800, 1280), (400, 640)),
    ),
    "perception_bundle_has_no_capture_dependency": BoundaryRule(
        reason="the neutral perception bundle must not depend on capture, ADB, cv2 or numpy",
        targets=("tasks/perception_bundle.py",),
        import_fragments=("cv2", "numpy", "bluestacks_native_runtime", "adb"),
        identifiers=("CapturedNativeFrame", "ADBRunner", "capture"),
        text_fragments=("bluestacks_native_runtime",),
        case_sensitive=True,
    ),
    "shared_navigation_boundary_is_task_agnostic": BoundaryRule(
        reason="shared navigation boundary code must not name any specific task",
        targets=("scripts/navigation_development_boundary.py",),
        text_fragments=("nova", "research lab", "research_lab", "praise"),
    ),
    "noahs_tavern_adapter_reads_no_delivery_or_governance_state": BoundaryRule(
        reason="the Noah's Tavern navigation adapter must not read delivery or governance state",
        targets=("scripts/noahs_tavern_recruit_bluestacks.py",),
        text_fragments=(
            "flow_delivery_queue",
            "flow-delivery-lease",
            "validate_governance",
            "validation-receipt",
            "gameplay_flow_contracts",
            "current_handoff",
        ),
    ),
    "pnsctl_has_no_legacy_remote_transport_or_task_literals": BoundaryRule(
        reason="pnsctl must not carry the retired remote transport or retired task literals",
        targets=("scripts/pnsctl.py",),
        text_fragments=(
            "PnS-BlissOS-PoC",
            "UNRAID_TEMP_",
            "plink",
            "pscp",
            "docker",
            "mvp_quest_to_claim",
            "MVP-QUEST-TO-CLAIM",
        ),
        case_sensitive=True,
    ),
    "production_scheduler_does_not_reach_delivery_flows": BoundaryRule(
        reason="the production scheduler must not reference the flow-delivery queue or the UC delivery flow",
        targets=("automation_service/scheduler.py",),
        text_fragments=("flow_delivery_queue", "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"),
        case_sensitive=True,
    ),
    "safe_action_executor_has_no_campaign_atlas_tap_allowlist": BoundaryRule(
        reason="SafeAction ROI-change allowlists must not be expanded for Campaign Atlas map taps",
        targets=("safe_action_core/executor.py",),
        text_fragments=("CAMPAIGN_ATLAS_MAP_TAP",),
        case_sensitive=True,
    ),
    "campaign_atlas_collector_has_no_direct_transport": BoundaryRule(
        reason="the Campaign Atlas collector must not spawn processes or construct ADB/runtime transports",
        targets=("scripts/campaign_atlas_bluestacks.py",),
        import_fragments=("subprocess",),
        identifiers=("ADBRunner", "LocalBlueStacksRuntime"),
        case_sensitive=True,
    ),
    "reference_tree_is_not_a_runtime_dependency": BoundaryRule(
        reason="the vendor reference tree is research material and must not be a runtime dependency",
        targets=_package_files("safe_action_core", "tasks", "scripts"),
        text_fragments=(".local-reference", "gnbots-trial", "decoded/scripts"),
        case_sensitive=True,
    ),
}

_SURVEY_MODULE = "scripts/flow_delivery_campaign_atlas_bluestacks.py"
_SURVEY_OFFLINE_RECONCILER = "reconcile_campaign_atlas_survey_action_offline"


class SourceBoundaryArchitectureTests(unittest.TestCase):
    def test_every_boundary_rule_holds_for_its_modules(self) -> None:
        for name, rule in RULES.items():
            for relative in rule.targets:
                with self.subTest(rule=name, module=relative):
                    path = REPO_ROOT / relative
                    self.assertTrue(path.is_file(), relative)
                    violations = boundary_violations(path.read_text(encoding="utf-8"), rule)
                    self.assertEqual(violations, [], rule.reason)

    def test_boundary_rules_name_a_reason_and_existing_targets(self) -> None:
        for name, rule in RULES.items():
            with self.subTest(rule=name):
                self.assertTrue(rule.reason.strip())
                self.assertTrue(rule.targets)
                self.assertTrue(
                    rule.import_fragments or rule.identifiers or rule.text_fragments or rule.integer_tuples
                )

    def test_offline_survey_reconciler_never_touches_transport(self) -> None:
        source = (REPO_ROOT / _SURVEY_MODULE).read_text(encoding="utf-8")
        self.assertEqual(
            function_attribute_calls(source, _SURVEY_OFFLINE_RECONCILER, frozenset({"swipe", "tap"})),
            [],
        )


class SourceBoundaryScannerSelfTests(unittest.TestCase):
    def test_scanner_flags_imports_identifiers_literals_and_text(self) -> None:
        rule = BoundaryRule(
            reason="self-test",
            targets=("unused.py",),
            import_fragments=("subprocess",),
            identifiers=("ADBRunner",),
            text_fragments=("Secret-Token",),
            integer_tuples=((800, 1280),),
        )
        flagged = (
            "import subprocess\n",
            "import os.subprocess_helpers\n",
            "from subprocess import run\n",
            "from . import subprocess\n",
            "def f():\n    import subprocess\n",
            "import importlib\nimportlib.import_module('subprocess')\n",
            "__import__('subprocess')\n",
            "x = ADBRunner\n",
            "x = module.ADBRunner()\n",
            "class ADBRunner: pass\n",
            "def f(ADBRunner): pass\n",
            "f(ADBRunner=1)\n",
            "from m import ADBRunner as Other\n",
            "name = 'a secret-token b'\n",
            "def f(): return 'Secret-Token'\n",
            "size = (800, 1280)\n",
        )
        for source in flagged:
            with self.subTest(source=source):
                self.assertTrue(boundary_violations(source, rule))

    def test_scanner_ignores_comments_and_unrelated_nodes(self) -> None:
        rule = BoundaryRule(
            reason="self-test",
            targets=("unused.py",),
            import_fragments=("subprocess",),
            identifiers=("ADBRunner",),
            text_fragments=("Secret-Token",),
            integer_tuples=((800, 1280),),
        )
        ignored = (
            "# import subprocess\n# ADBRunner Secret-Token\n",
            "import os\nfrom pathlib import Path\n",
            "x = 'ADBRunner'\n",
            "size = (800, 1281)\nother = (800, 1280, 3)\nmixed = (800, width)\n",
            "from . import adb_helpers\n",
        )
        for source in ignored:
            with self.subTest(source=source):
                self.assertEqual(boundary_violations(source, rule), [])

    def test_case_sensitivity_follows_the_rule(self) -> None:
        sensitive = BoundaryRule(reason="r", targets=("x",), text_fragments=("docker",), case_sensitive=True)
        folded = BoundaryRule(reason="r", targets=("x",), text_fragments=("docker",))
        self.assertEqual(boundary_violations("x = 'Docker'\n", sensitive), [])
        self.assertTrue(boundary_violations("x = 'Docker'\n", folded))

    def test_every_production_rule_fails_when_violated(self) -> None:
        for name, rule in RULES.items():
            samples = [f"import {fragment}\n" for fragment in rule.import_fragments]
            samples += [f"{identifier} = 1\n" for identifier in rule.identifiers]
            samples += [f"value = {fragment!r}\n" for fragment in rule.text_fragments]
            samples += [f"value = {values!r}\n" for values in rule.integer_tuples]
            self.assertTrue(samples, name)
            for sample in samples:
                with self.subTest(rule=name, sample=sample):
                    self.assertTrue(boundary_violations(sample, rule))

    def test_function_scanner_is_scoped_to_one_function(self) -> None:
        source = (
            "def offline(x):\n    return x.pending\n\n"
            "def live(runtime):\n    runtime.swipe()\n    runtime.tap()\n"
        )
        attributes = frozenset({"swipe", "tap"})
        self.assertEqual(function_attribute_calls(source, "offline", attributes), [])
        self.assertEqual(function_attribute_calls(source, "live", attributes), [5, 6])
        nested = "def offline(runtime):\n    def inner():\n        runtime.tap()\n    return inner\n"
        self.assertEqual(function_attribute_calls(nested, "offline", attributes), [3])
        with self.assertRaises(LookupError):
            function_attribute_calls(source, "missing", attributes)


if __name__ == "__main__":
    unittest.main()
