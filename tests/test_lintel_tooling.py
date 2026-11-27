import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lintel.adapters import config as config_adapter, contract_facts, contract_lock, incremental_cache, lean_generator
import lintel.adapters.runtime as runtime_module
from lintel.adapters import agent_files
from lintel.adapters import typescript_extractor
from lintel.adapters import rust_extractor
from lintel.adapters import go_extractor
from lintel.adapters import decision_model
from lintel.core import hooks, review
from lintel.adapters.language import PythonSourceAnalyzer, analyzer_for_suffix
from lintel.adapters.runtime import LintelRuntime
from lintel.core.checker import (
    check_boundary_concerns,
    check_executables,
    check_wrapper_operations,
    check,
    module_name_from_path,
    region_for,
    check_semantic_review,
)
from lintel.core.model import (
    BoundaryConcernUse,
    Dependency,
    Entrypoint,
    FactSet,
    Module,
    facts_from_dict,
    policy_from_dict,
    ScopeAssignment,
    PathOverrides,
    SemanticReview,
    SemanticDecision,
    facts_with_decisions,
    merge_decisions,
    Violation,
    WrapperOperation,
)
from lintel.core.ratchet import compare_baseline, violation_fingerprint

CONFIG_PATH = os.path.join(ROOT, "lintel.toml")


def real_policy():
    config = config_adapter.load_config(CONFIG_PATH)
    return policy_from_dict(config_adapter.policy_from_config(config))


def module_ctor(source, name):
    suffix = f'=> "{name}"'
    for line in source.splitlines():
        if line.startswith("  | GeneratedModule.m") and line.endswith(suffix):
            return line.split("=>", 1)[0].strip().removeprefix("| ").removeprefix("GeneratedModule.").strip()
    raise AssertionError(f"missing generated module for {name}")

def declared_rows(source):
    lines = source.splitlines()
    start = lines.index("def generatedWrapperDeclaredBool : GeneratedModule → Bool")
    end = lines.index(
        "def generatedWrapperDeclared (a : GeneratedModule) : Prop := generatedWrapperDeclaredBool a = true"
    )
    return "\n".join(lines[start:end])


def generated_rank(source, ctor):
    prefix = f"  | GeneratedModule.{ctor} => "
    lines = source.splitlines()
    start = lines.index("def generatedRank : GeneratedModule → Nat")
    for line in lines[start:]:
        if line.startswith(prefix) and line[len(prefix) :].isdigit():
            return int(line[len(prefix) :])
    raise AssertionError(f"missing generated rank for {ctor}")


def declared_modules(policy):
    return tuple(
        Module(module_name_from_path(item.path), item.path)
        for item in policy.executables
    )


def rules(violations):
    return {item.rule for item in violations}


class ConfigValidationTests(unittest.TestCase):
    def test_unknown_key_and_bad_reference(self):
        config = {
            "version": 1,
            "default_layer": "external",
            "default_scope": "external",
            "analysis": {"source_suffixes": [".py"]},
            "unexpected": True,
            "layers": {
                "external": {"priority": 1000, "allowed": ["missing"]},
            },
            "scopes": {"external": {"patterns": ["*"]}},
            "executables": [],
        }
        violations = config_adapter.validate_config(config)
        self.assertIn("config_unknown_key", rules(violations))
        self.assertIn("config_bad_reference", rules(violations))

    def test_missing_source_suffixes_is_rejected(self):
        config = config_adapter.load_config(CONFIG_PATH)
        del config["analysis"]["source_suffixes"]
        violations = config_adapter.validate_config(config, ROOT)
        self.assertIn("config_invalid", rules(violations))

    def test_invalid_source_suffixes_are_rejected(self):
        config = config_adapter.load_config(CONFIG_PATH)
        config["analysis"]["source_suffixes"] = ".py"
        violations = config_adapter.validate_config(config, ROOT)
        self.assertIn("config_invalid", rules(violations))

    def test_new_adapters_subpackages_use_adapters_layer(self):
        self.assertEqual(
            region_for("lintel.adapters.language.future_analyzer", real_policy()).name,
            "adapters",
        )

    def test_boundary_patterns_key_is_rejected(self):
        config = config_adapter.load_config(CONFIG_PATH)
        config["boundary_concerns"]["mechanism"]["patterns"] = ["print"]
        violations = config_adapter.validate_config(config, ROOT)
        self.assertIn("config_unknown_key", rules(violations))

    def test_decision_api_is_configurable(self):
        config = config_adapter.load_config(CONFIG_PATH)
        config["semantic_decision"]["model"] = "custom/vendor-model"
        config["semantic_decision"]["api_key_env"] = "CUSTOM_KEY"
        violations = config_adapter.validate_config(config, ROOT)
        self.assertEqual(violations, ())
        policy = policy_from_dict(config_adapter.policy_from_config(config))
        self.assertEqual(policy.semantic_decision["model"], "custom/vendor-model")
        self.assertEqual(policy.semantic_decision["api_key_env"], "CUSTOM_KEY")

    def test_decision_api_bounds_are_validated(self):
        config = config_adapter.load_config(CONFIG_PATH)
        config["semantic_decision"]["min_confidence"] = 2
        config["semantic_decision"]["timeout"] = 0
        violations = config_adapter.validate_config(config, ROOT)
        self.assertIn("config_invalid", rules(violations))


class ExecutableRuleTests(unittest.TestCase):
    def test_undeclared_entrypoint_is_reported(self):
        policy = real_policy()
        facts = FactSet(
            modules=declared_modules(policy),
            entrypoints=(Entrypoint("unknown_cli", "lintel/cli/unknown.py"),),
        )
        self.assertIn("undeclared_executable", rules(check_executables(facts, policy)))

    def test_declared_entrypoint_is_allowed(self):
        policy = real_policy()
        facts = FactSet(
            modules=declared_modules(policy),
            entrypoints=(Entrypoint("lintel.cli.check_self", "lintel/cli/check_self.py"),),
        )
        self.assertEqual(check_executables(facts, policy), ())

    def test_wrong_owner_is_reported(self):
        policy = real_policy()
        executable = policy.executables[0]
        wrong = policy.__class__(
            **{
                **policy.__dict__,
                "executables": (
                    executable.__class__("renamed", executable.path, "adapters"),
                ),
            }
        )
        facts = FactSet(modules=declared_modules(policy))
        self.assertIn("executable_owner_mismatch", rules(check_executables(facts, wrong)))


class BoundaryConcernTests(unittest.TestCase):
    def test_entrypoint_only_concern_in_adapter_is_reported(self):
        policy = real_policy()
        facts = FactSet(
            concerns=(
                BoundaryConcernUse(
                    "adapters.demo_extractor", "argv_parse", "entrypoint_only",
                    "adapters/demo_extractor.py", 7,
                ),
            )
        )
        self.assertIn("adapter_cli_concern", rules(check_boundary_concerns(facts, policy)))

    def test_mechanism_concern_in_adapter_is_allowed(self):
        policy = real_policy()
        facts = FactSet(
            concerns=(
                BoundaryConcernUse(
                    "adapters.demo_extractor", "env", "mechanism",
                    "adapters/demo_extractor.py", 7,
                ),
            )
        )
        self.assertEqual(check_boundary_concerns(facts, policy), ())

    def test_entrypoint_and_build_artifact_concerns_are_allowed(self):
        policy = real_policy()
        facts = FactSet(
            concerns=(
                BoundaryConcernUse(
                    "lintel.cli.check_self", "argv_parse", "entrypoint_only",
                    "lintel/cli/check_self.py", 10,
                ),
            ),
            scopes=(
                ScopeAssignment(
                    "lintel/adapters/go-extractor/main.go", "build_artifact", "lintel/adapters/go-extractor/main.go", 30
                ),
            ),
        )
        facts = FactSet(
            concerns=facts.concerns + (
                BoundaryConcernUse(
                    "main", "argv_parse", "entrypoint_only",
                    "lintel/adapters/go-extractor/main.go", 5,
                ),
            ),
            scopes=facts.scopes,
        )
        self.assertEqual(check_boundary_concerns(facts, policy), ())

    def test_plain_attribute_use_is_detected(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/example.py",
            "import sys\nvalue = sys.argv[1]\nimport os\nenv = os.environ\n",
        )
        found = {item.concern for item in analysis.concerns}
        self.assertIn("argv", found)
        self.assertIn("env", found)

    def test_native_analyzers_are_language_specific(self):
        go = analyzer_for_suffix(".go")
        javascript = analyzer_for_suffix(".ts")
        self.assertEqual(
            go.analyze("adapter/main.go", 'text = "process.env"\n').concerns,
            (),
        )
        self.assertEqual(
            javascript.analyze("adapter/main.ts", 'text = "fmt.Print"\n').concerns,
            (),
        )
        self.assertIsNone(analyzer_for_suffix(".zzz"))


class WrapperOperationTests(unittest.TestCase):
    def test_composition_is_not_fat(self):
        policy = real_policy()
        facts = FactSet(
            wrapper_operations=(
                WrapperOperation(
                    "lintel.cli.extract_python", "import",
                    "lintel.adapters.python_extractor.extract", "lintel/cli/extract_python.py", 13,
                ),
                WrapperOperation(
                    "lintel.cli.extract_rust_native", "subprocess",
                    "cargo", "lintel/cli/extract_rust_native.py", 22,
                ),
            )
        )
        self.assertEqual(check_wrapper_operations(facts, policy), ())

    def test_checker_import_is_fat(self):
        policy = real_policy()
        facts = FactSet(
            wrapper_operations=(
                WrapperOperation(
                    "lintel.cli.bad", "import", "lintel.core.checker",
                    "lintel/cli/bad.py", 3,
                ),
            )
        )
        self.assertIn("fat_entrypoint", rules(check_wrapper_operations(facts, policy)))

    def test_analyzer_detects_run_with_cwd(self):
        analysis = PythonSourceAnalyzer().analyze(
            "lintel/cli/sample.py",
            "runtime.run([\"lake\", \"build\"], cwd=runtime.tool_root)\n",
        )
        self.assertTrue(
            any(
                item.operation == "subprocess" and item.target == "lake"
                for item in analysis.wrapper_operations
            )
        )


class RatchetTests(unittest.TestCase):
    def test_new_violation_and_stale_entry(self):
        violation = Violation("edge_not_allowed", "bad edge", {"location": "a.py:12"})
        key = violation_fingerprint(violation)
        self.assertEqual(compare_baseline((violation,), [{"fingerprint": key}]), ())
        self.assertIn(
            "baseline_violation",
            rules(compare_baseline((violation,), [])),
        )
        self.assertIn(
            "baseline_stale",
            rules(compare_baseline((), [{"fingerprint": key, "rule": "edge_not_allowed"}])),
        )

    def test_stale_only_when_accepted_finding_is_no_longer_live(self):
        old = Violation(
            "semantic_review",
            "dynamic access",
            {"location": "adapters/old.py:4", "source": "adapters/old.py", "line": 4, "reason": "dynamic"},
        )
        changed = Violation(
            "semantic_review",
            "dynamic access",
            {"location": "adapters/new.py:9", "source": "adapters/new.py", "line": 9, "reason": "dynamic"},
        )
        old_key = violation_fingerprint(old)
        self.assertNotEqual(old_key, violation_fingerprint(changed))
        accepted = [{"fingerprint": old_key, "rule": "semantic_review"}]
        self.assertEqual(compare_baseline((), accepted, frozenset({old_key})), ())
        self.assertIn(
            "baseline_stale",
            rules(compare_baseline((), accepted, frozenset())),
        )

    def test_non_baselineable_violations_pass_through(self):
        violation = Violation("unparsed_source", "bad", {"location": "a.py:1"})
        key = violation_fingerprint(violation)
        result = compare_baseline(
            (violation,), [{"fingerprint": key, "rule": "unparsed_source"}]
        )
        self.assertEqual(result, (violation,))

    def test_accept_baseline_rejects_contract_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = LintelRuntime(directory)
            with self.assertRaises(SystemExit):
                runtime.accept_baseline(
                    "lintel.toml", (Violation("config_invalid", "bad"),)
                )


class LockTests(unittest.TestCase):
    def test_config_digest_changes_with_semantic_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, "lintel.toml")
            with open(config, "w", encoding="utf-8") as handle:
                handle.write('version = 1\n[paths]\nentrypoints_root = "cli"\n')
            first = contract_lock.config_digest(config)
            with open(config, "w", encoding="utf-8") as handle:
                handle.write('version = 1\n[paths]\nentrypoints_root = "lintel/cli"\n')
            self.assertNotEqual(first, contract_lock.config_digest(config))

    def test_checker_artifact_digest_changes_with_code_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = "checker.py"
            path = os.path.join(directory, artifact)
            with patch.object(contract_lock, "CHECKER_ARTIFACTS", (artifact,)):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("def check(): return 1\n")
                first = contract_lock.checker_artifact_digest(directory)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("def check(): return 2\n")
                self.assertNotEqual(first, contract_lock.checker_artifact_digest(directory))


class ScaffoldTests(unittest.TestCase):
    def test_scaffolded_config_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = LintelRuntime(directory)
            runtime.scaffold("clean", directory)
            config = os.path.join(directory, "lintel.toml")
            data = config_adapter.load_config(config)
            self.assertEqual(config_adapter.validate_config(data, directory), ())
            with open(os.path.join(directory, "lintel.baseline.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["violations"], [])
            with open(os.path.join(directory, ".gitignore"), encoding="utf-8") as handle:
                ignored = handle.read().splitlines()
            self.assertEqual(ignored.count("lintel.cache.json"), 1)
            runtime.scaffold("clean", directory)
            with open(os.path.join(directory, ".gitignore"), encoding="utf-8") as handle:
                ignored = handle.read().splitlines()
            self.assertEqual(ignored.count("lintel.cache.json"), 1)

    def test_scaffold_preserves_existing_gitignore(self):
        with tempfile.TemporaryDirectory() as directory:
            ignore = os.path.join(directory, ".gitignore")
            with open(ignore, "w", encoding="utf-8") as handle:
                handle.write("node_modules/")
            LintelRuntime(directory).scaffold("clean", directory)
            with open(ignore, "r", encoding="utf-8") as handle:
                ignored = handle.read().splitlines()
            self.assertEqual(
                ignored, ["node_modules/", "lintel.cache.json"]
            )

    def test_scaffold_preserves_existing_agent_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            instructions = os.path.join(directory, "AGENTS.md")
            with open(instructions, "w", encoding="utf-8") as handle:
                handle.write("custom harness instructions\n")
            runtime = LintelRuntime(directory)
            runtime.scaffold("clean", directory)
            runtime.scaffold("clean", directory)
            with open(instructions, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "custom harness instructions\n")





class IncrementalCacheTests(unittest.TestCase):
    def test_fact_cache_hit_avoids_reextraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "adapters"))
            source = os.path.join(tmp, "adapters", "demo.py")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("value = 1\n")
            runtime = LintelRuntime(tmp)
            config = runtime.load_self_config(CONFIG_PATH, True)
            calls = []

            def fake_run(command, cwd=None):
                calls.append(command)
                out = command[command.index("--out") + 1]
                with open(out, "w", encoding="utf-8") as handle:
                    json.dump(
                        {
                            "modules": [
                                {"name": "adapters.demo", "path": "adapters/demo.py"}
                            ],
                            "dependencies": [],
                        },
                        handle,
                    )
                return None

            with patch.object(runtime, "run", side_effect=fake_run):
                first = runtime.collect_self_facts(config, PathOverrides())
                self.assertEqual(len(calls), 2)
                calls.clear()
                second = runtime.collect_self_facts(config, PathOverrides())
                self.assertEqual(calls, [])
                self.assertEqual(first, second)
                with open(source, "w", encoding="utf-8") as handle:
                    handle.write("value = 2\n")
                runtime.collect_self_facts(config, PathOverrides())
                self.assertEqual(len(calls), 2)

    def test_lean_check_cache_tracks_generated_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LintelRuntime(tmp)
            output = os.path.join(tmp, "GeneratedFacts.lean")
            with open(output, "w", encoding="utf-8") as handle:
                handle.write("def generated := 1\n")
            key = runtime.lean_check_key(output)
            self.assertFalse(runtime.lean_check_is_cached(key))
            runtime.mark_lean_check(key)
            self.assertTrue(runtime.lean_check_is_cached(key))
            with open(output, "w", encoding="utf-8") as handle:
                handle.write("def generated := 2\n")
            changed = runtime.lean_check_key(output)
            self.assertNotEqual(changed, key)
            self.assertFalse(runtime.lean_check_is_cached(changed))

    def test_malformed_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(incremental_cache.cache_path(tmp), "w", encoding="utf-8") as handle:
                handle.write("{not json")
            self.assertEqual(incremental_cache.load_facts(tmp, "key"), None)
            self.assertFalse(incremental_cache.lean_ok(tmp, "key"))
class LeanGeneratorTests(unittest.TestCase):

    def test_generated_instance_is_deterministic(self):
        script = """
import sys
root = sys.argv[1]
sys.path.insert(0, root)
from lintel.adapters import config as config_adapter, lean_generator
from lintel.core.model import Dependency, FactSet, Module, policy_from_dict
config = config_adapter.load_config(root + "/lintel.toml")
policy = policy_from_dict(config_adapter.policy_from_config(config))
facts = FactSet(
    modules=(
        Module("lintel.adapters.one", "lintel/adapters/one.py"),
        Module("lintel.core.two", "lintel/core/two.py"),
        Module("lintel.cli.three", "lintel/cli/three.py"),
    ),
    dependencies=(
        Dependency("lintel.adapters.one", "lintel.core.two"),
        Dependency("lintel.cli.three", "lintel.adapters.one"),
    ),
)
sys.stdout.write(lean_generator.generate(facts, policy))
"""
        outputs = []
        for seed in ("1", "2"):
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = seed
            outputs.append(
                subprocess.check_output(
                    [sys.executable, "-c", script, ROOT],
                    env=env,
                    text=True,
                )
            )
        self.assertEqual(outputs[0], outputs[1])
    def test_generated_instance_uses_spec_structures(self):
        policy = real_policy()
        facts = FactSet(
            modules=(
                Module("lintel.adapters.contract_facts"),
                Module("lintel.core.checker"),
            ),
            dependencies=(
                Dependency("lintel.adapters.contract_facts", "lintel.core.checker"),
            ),
        )
        source = lean_generator.generate(facts, policy)
        self.assertIn("import Lintel", source)
        for declaration in (
            "def generatedArchitecture : Architecture where",
            "def generatedEdgePolicy : EdgePolicy GeneratedRegion where",
            "def generatedPolicyArchitecture : PolicyArchitecture where",
            "def generatedAcyclicArchitecture : AcyclicArchitecture where",
            "def generatedNestedArchitecture : NestedArchitecture where",
            "def generatedPortOf",
            "def generatedAdapterOf",
            "def generatedInvertedCallOf",
            "def generatedRegionOrder : RegionOrder GeneratedRegion where",
            "def generatedLayered : MultiCoreLayeredArchitecture where",
            "def generatedUseCaseBoundary : UseCaseBoundary generatedArchitecture where",
            "def generatedEntrypoints : EntrypointInventory generatedArchitecture GeneratedRegion where",
            "def generatedScopes : ScopeInventory generatedArchitecture GeneratedScope where",
            "def generatedPathScopes : PathScopeInventory GeneratedScope where",
            "def generatedBoundaryConcerns : BoundaryConcernInventory generatedArchitecture where",
            "def generatedWrappers : WrapperInventory generatedArchitecture where",
            "def generatedReviews : ReviewInventory generatedArchitecture where",
            "theorem generated_core_cannot_reach_outer",
            "theorem generated_path_allowed",
            "theorem generated_acyclic : Acyclic generatedDep",
            "theorem generated_core_region_path",
            "theorem generated_adapter_unreachable_from_core",
            "theorem generated_inverted_call_avoids_adapter",
        ):
            self.assertIn(declaration, source)

    def test_wrapper_declarations_cover_only_subprocess_callers(self):
        policy = real_policy()
        facts = FactSet(
            modules=(
                Module("lintel.cli.caller", "lintel/cli/caller.py"),
                Module("adapters.other", "adapters/other.py"),
            ),
            wrapper_operations=(
                WrapperOperation(
                    "lintel.cli.caller",
                    "subprocess",
                    "tools/cargo",
                    "lintel/cli/caller.py",
                    1,
                ),
            ),
        )
        source = lean_generator.generate(facts, policy)
        caller = module_ctor(source, "lintel.cli.caller")
        other = module_ctor(source, "adapters.other")
        rows = declared_rows(source)
        self.assertIn(f"| GeneratedModule.{caller} => true", rows)
        self.assertNotIn(f"| GeneratedModule.{other} => true", rows)

    def test_baseline_semantic_review_source_is_used(self):
        policy = real_policy()
        facts = FactSet(
            modules=(Module("adapters.impl", "adapters/impl.py"),),
            reviews=(
                SemanticReview("adapters.impl", "adapters/impl.py", 1, "ambiguous"),
            ),
        )
        violations = check_semantic_review(facts, policy)
        self.assertTrue(violations)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LintelRuntime(tmp)
            runtime.accept_baseline(CONFIG_PATH, violations)
            path = os.path.join(tmp, "lintel.baseline.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["violations"][0].get("location"), "adapters/impl.py:1")
            self.assertEqual(
                runtime.accepted_review_sources(path, facts, policy),
                ("adapters/impl.py",),
            )


    def test_generated_rank_decreases_along_dependencies(self):
        policy = real_policy()
        facts = FactSet(
            modules=(
                Module("lintel.adapters.contract_facts"),
                Module("lintel.core.model"),
            ),
            dependencies=(
                Dependency("lintel.adapters.contract_facts", "lintel.core.model"),
            ),
        )
        source = lean_generator.generate(facts, policy)
        source_ctor = module_ctor(source, "lintel.adapters.contract_facts")
        target_ctor = module_ctor(source, "lintel.core.model")
        self.assertLess(
            generated_rank(source, target_ctor),
            generated_rank(source, source_ctor),
        )

    def test_accepted_review_is_not_pending(self):
        policy = real_policy()
        facts = FactSet(
            modules=(Module("adapters.impl", "adapters/impl.py"),),
            reviews=(
                SemanticReview("adapters.impl", "adapters/impl.py", 1, "ambiguous"),
            ),
        )
        pending = lean_generator.generate(facts, policy)
        accepted = lean_generator.generate(facts, policy, ("adapters/impl.py",))
        ctor = module_ctor(pending, "adapters.impl")
        pending_row = f"| ReviewState.pending, GeneratedModule.{ctor} => true"
        accepted_row = f"| ReviewState.accepted, GeneratedModule.{ctor} => true"
        self.assertIn(pending_row, pending)
        self.assertNotIn(accepted_row, pending)
        self.assertNotIn(pending_row, accepted)
        self.assertIn(accepted_row, accepted)




class PipelineTests(unittest.TestCase):
    def test_aggregate_pipeline_includes_use_cases(self):
        policy = real_policy()
        facts = FactSet(
            modules=(
                Module("lintel.core.use_cases.bad"),
                Module("adapters.impl"),
            ),
            dependencies=(
                Dependency(
                    "lintel.core.use_cases.bad",
                    "adapters.impl",
                    "import",
                    "bad.py",
                    1,
                ),
            ),
        )
        self.assertTrue(
            any(item.rule == "use_case_dependency" for item in check(facts, policy))
        )


class SelfFactPipelineTests(unittest.TestCase):
    def test_collect_self_facts_emits_semantic_review(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = LintelRuntime(directory)
            runtime.scaffold("clean", directory)
            path = os.path.join(directory, "adapters", "review_me.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("import os\nvalue = getattr(os, \"environ\")\n")
            config = runtime.load_self_config("lintel.toml", True)
            facts = runtime.collect_self_facts(config, PathOverrides())
            violations = check(facts, config.policy)
        self.assertTrue(
            any(item.rule == "semantic_review" for item in violations)
        )

class EscapeHatchTests(unittest.TestCase):
    def test_declared_unsupported_suffix_fails_closed(self):
        config = config_adapter.load_config(os.path.join(ROOT, "lintel.toml"))
        config["analysis"]["source_suffixes"] = [
            *config["analysis"]["source_suffixes"],
            ".zig",
        ]
        policy = policy_from_dict(config_adapter.policy_from_config(config))
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "widget.zig"), "w", encoding="utf-8") as handle:
                handle.write("export fn main() void {}\n")
            facts = contract_facts.discover(directory, policy, policy.entrypoints_root)
            violations = check(facts_from_dict(facts), policy)
        self.assertTrue(
            any(
                item["reason"] == "unsupported source suffix: .zig"
                for item in facts["unparsed"]
            )
        )
        self.assertTrue(any(item.rule == "unparsed_source" for item in violations))

    def test_undeclared_known_source_suffix_fails_closed(self):
        config = config_adapter.load_config(os.path.join(ROOT, "lintel.toml"))
        policy = policy_from_dict(config_adapter.policy_from_config(config))
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "widget.rb"), "w", encoding="utf-8") as handle:
                handle.write("puts 'hello'\n")
            facts = contract_facts.discover(directory, policy, policy.entrypoints_root)
            violations = check(facts_from_dict(facts), policy)
        self.assertTrue(
            any(
                item["reason"] == "undeclared source suffix: .rb"
                for item in facts["unparsed"]
            )
        )
        self.assertTrue(any(item.rule == "unparsed_source" for item in violations))

    def test_undeclared_analyzable_suffix_fails_closed(self):
        config = config_adapter.load_config(os.path.join(ROOT, "lintel.toml"))
        config["analysis"]["source_suffixes"] = [
            suffix
            for suffix in config["analysis"]["source_suffixes"]
            if suffix != ".py"
        ]
        policy = policy_from_dict(config_adapter.policy_from_config(config))
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "widget.py"), "w", encoding="utf-8") as handle:
                handle.write("value = 1\n")
            facts = contract_facts.discover(directory, policy, policy.entrypoints_root)
        self.assertTrue(
            any(
                item["reason"] == "undeclared source suffix: .py"
                for item in facts["unparsed"]
            )
        )

    def test_semantic_review_flag_is_reported_and_excluded_scope_skipped(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/example.py", "import os\nvalue = getattr(os, \"environ\")\n"
        )
        self.assertTrue(
            any(item.reason == "dynamic access to os.environ" for item in analysis.reviews)
        )
        policy = real_policy()
        excluded = FactSet(
            reviews=analysis.reviews,
            scopes=(ScopeAssignment("adapters/example.py", "example"),),
        )
        self.assertEqual(check_semantic_review(excluded, policy), ())
        included = FactSet(reviews=analysis.reviews)
        self.assertTrue(
            any(item.rule == "semantic_review" for item in check_semantic_review(included, policy))
        )


class HookProtocolTests(unittest.TestCase):
    def test_hook_result_has_stable_shape_and_fingerprint(self):
        violation = Violation(
            "semantic_review",
            "dynamic access",
            {"source": "adapters/example.py", "location": "adapters/example.py:1"},
        )
        result = hooks.build("post-edit", (violation,))
        self.assertEqual(set(result), {"block", "context", "findings", "commands"})
        self.assertTrue(result["block"])
        self.assertEqual(
            result["findings"][0]["fingerprint"], violation_fingerprint(violation)
        )
        self.assertEqual(hooks.build("session-start", (violation,))["block"], False)

    def test_semantic_review_fingerprints_are_per_finding(self):
        first = Violation(
            "semantic_review",
            "dynamic access",
            {
                "source": "adapters/example.py",
                "line": 1,
                "reason": "dynamic access",
                "location": "adapters/example.py:1",
            },
        )
        second = Violation(
            "semantic_review",
            "dynamic access",
            {
                "source": "adapters/example.py",
                "line": 2,
                "reason": "dynamic access",
                "location": "adapters/example.py:2",
            },
        )
        self.assertNotEqual(
            violation_fingerprint(first), violation_fingerprint(second)
        )

    def test_session_start_hook_command_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            output = subprocess.check_output(
                [
                    sys.executable,
                    os.path.join(ROOT, "lintel", "cli", "main.py"),
                    "--root",
                    directory,
                    "hook",
                    "session-start",
                ],
                text=True,
            )
        payload = json.loads(output)
        self.assertFalse(payload["block"])
        self.assertIn("lintel check --format json", payload["commands"])


class ReviewDecisionTests(unittest.TestCase):
    def test_decisions_are_validated_and_only_compliant_accepts(self):
        self.assertTrue(review.is_decision("compliant"))
        self.assertFalse(review.is_decision("ignore"))
        self.assertTrue(review.is_accepting("compliant"))
        self.assertFalse(review.is_accepting("needs-human-review"))
        self.assertEqual(review.validate_reason("  reviewed  "), "reviewed")
        with self.assertRaises(ValueError):
            review.validate_reason("   ")

    def test_record_review_persists_reason_and_accepted_source(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = LintelRuntime(directory)
            runtime.scaffold("clean", directory)
            path = os.path.join(directory, "adapters", "review_me.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("import os\nvalue = getattr(os, \"environ\")\n")
            config = runtime.load_self_config("lintel.toml", True)
            facts = runtime.collect_self_facts(config, PathOverrides())
            findings = check_semantic_review(facts, config.policy)
            self.assertTrue(findings)
            key = violation_fingerprint(findings[0])
            record = runtime.record_review(
                key, "compliant", "dynamic access is intentional"
            )
            self.assertEqual(record["decision"], "compliant")
            with open(os.path.join(directory, "lintel.baseline.json"), encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["decisions"][0]["reason"], "dynamic access is intentional")
            self.assertEqual(data["violations"][0]["fingerprint"], key)
            self.assertIn("adapters/review_me.py", runtime.accepted_review_sources(
                os.path.join(directory, "lintel.baseline.json"), facts, config.policy
            ))



class DecisionModelTests(unittest.TestCase):
    def _settings(self):
        return dict(
            real_policy().semantic_decision,
            model="custom/vendor-model",
            answer_key="review",
            api_key_env="TEST_DECISION_KEY",
            min_confidence=0.8,
        )

    def _policy(self):
        return replace(real_policy(), semantic_decision=self._settings())

    def _finding(self, policy):
        item = SemanticReview(
            "adapters/example.py",
            "adapters/example.py",
            3,
            "dynamic access to os.environ",
        )
        return check_semantic_review(FactSet(reviews=(item,)), policy)[0]

    def test_payload_uses_configured_model_and_question_prefix(self):
        policy = self._policy()
        finding = self._finding(policy)
        bundle = decision_model.build_payload((finding,), policy)
        question_id = f"review:{violation_fingerprint(finding)}"
        self.assertEqual(bundle["payload"]["model"], "custom/vendor-model")
        self.assertIn(question_id, bundle["payload"]["questions"])
        self.assertEqual(
            bundle["payload"]["questions"][question_id]["type"], "choice"
        )

    def test_evaluate_validates_typed_choice_and_audits_state(self):
        policy = self._policy()
        finding = self._finding(policy)
        question_id = f"review:{violation_fingerprint(finding)}"

        class Response:
            def read(self, limit=-1):
                payload = {
                    "model": "custom/vendor-model-1",
                    "answers": {
                        question_id: {
                            "type": "choice",
                            "choice": "compliant",
                            "confidence": 0.96,
                        }
                    },
                }
                return json.dumps(payload).encode("utf-8")

            def close(self):
                pass

        with patch.dict(os.environ, {"TEST_DECISION_KEY": "secret"}):
            decisions = decision_model.evaluate(
                (finding,), policy, opener=lambda request, timeout=None: Response()
            )
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].decision, "compliant")
        self.assertEqual(decisions[0].model, "custom/vendor-model-1")
        self.assertTrue(decisions[0].evidence_hash)
        self.assertTrue(decisions[0].state_hash)

    def test_low_confidence_is_downgraded(self):
        policy = self._policy()
        finding = self._finding(policy)
        question_id = f"review:{violation_fingerprint(finding)}"

        class Response:
            def read(self, limit=-1):
                payload = {
                    "answers": {
                        question_id: {
                            "type": "choice",
                            "choice": "compliant",
                            "confidence": 0.2,
                        }
                    }
                }
                return json.dumps(payload).encode("utf-8")

            def close(self):
                pass

        with patch.dict(os.environ, {"TEST_DECISION_KEY": "secret"}):
            decisions = decision_model.evaluate(
                (finding,), policy, opener=lambda request, timeout=None: Response()
            )
        self.assertEqual(decisions[0].decision, "needs-human-review")

    def test_checker_accepts_high_confidence_compliant_decision(self):
        policy = self._policy()
        item = SemanticReview("adapters/example.py", "adapters/example.py", 3, "dynamic")
        facts = FactSet(reviews=(item,))
        finding = check_semantic_review(facts, policy)[0]
        key = violation_fingerprint(finding)
        decision = SemanticDecision(key, "compliant", "test", 0.99, "test/model")
        decided = facts_with_decisions(facts, (decision,))
        self.assertEqual(check_semantic_review(decided, policy, (decision,)), ())

    def test_missing_confidence_defaults_to_human_level(self):
        facts = facts_from_dict(
            {"decisions": [{"fingerprint": "abc", "decision": "compliant"}]}
        )
        self.assertEqual(facts.decisions[0].confidence, 1.0)

    def test_probability_distribution_supplies_confidence(self):
        policy = self._policy()
        finding = self._finding(policy)
        question_id = f"review:{violation_fingerprint(finding)}"

        class Response:
            def read(self, limit=-1):
                payload = {
                    "model": "alternate/model-1",
                    "answers": {
                        question_id: {
                            "type": "choice",
                            "choice": "violating",
                            "probabilities": {"compliant": 0.07, "violating": 0.93},
                        }
                    },
                }
                return json.dumps(payload).encode("utf-8")

            def close(self):
                pass

        with patch.dict(os.environ, {"TEST_DECISION_KEY": "secret"}):
            decisions = decision_model.evaluate(
                (finding,), policy, opener=lambda request, timeout=None: Response()
            )
        self.assertEqual(decisions[0].decision, "violating")
        self.assertEqual(decisions[0].confidence, 0.93)

    def test_missing_confidence_fails_closed(self):
        policy = self._policy()
        finding = self._finding(policy)
        question_id = f"review:{violation_fingerprint(finding)}"

        class Response:
            def read(self, limit=-1):
                payload = {
                    "answers": {
                        question_id: {"type": "choice", "choice": "compliant"}
                    }
                }
                return json.dumps(payload).encode("utf-8")

            def close(self):
                pass

        with patch.dict(os.environ, {"TEST_DECISION_KEY": "secret"}):
            with self.assertRaises(decision_model.DecisionModelError):
                decision_model.evaluate(
                    (finding,), policy, opener=lambda request, timeout=None: Response()
                )

    def test_merge_decisions_keeps_unreviewed_findings(self):
        existing = SemanticDecision("a", "compliant", "human", 1.0, "human")
        incoming = (
            SemanticDecision("b", "violating", "model", 0.9, "test/model"),
            SemanticDecision("a", "needs-human-review", "model", 0.7, "test/model"),
        )
        merged = merge_decisions((existing,), incoming)
        by_fingerprint = {item.fingerprint: item.decision for item in merged}
        self.assertEqual(
            by_fingerprint, {"a": "needs-human-review", "b": "violating"}
        )

    def test_record_model_decisions_persists_audit_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = LintelRuntime(directory)
            runtime.scaffold("clean", directory)
            path = os.path.join(directory, "adapters", "review_me.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("import os\nvalue = getattr(os, \"environ\")\n")
            config = runtime.load_self_config("lintel.toml", True)
            facts = runtime.collect_self_facts(config, PathOverrides())
            findings = runtime.semantic_review_findings(facts, config.policy)
            finding = findings[0]
            key = violation_fingerprint(finding)
            decision = SemanticDecision(
                key,
                "compliant",
                "model choice=compliant confidence=0.9900",
                0.99,
                "test/model",
                "1",
                "evidence",
                "state",
            )
            runtime.record_model_decisions((decision,), findings)
            with open(
                os.path.join(directory, "lintel.baseline.json"), encoding="utf-8"
            ) as handle:
                data = json.load(handle)
            record = data["decisions"][0]
            self.assertEqual(record["evidence_hash"], "evidence")
            self.assertEqual(record["state_hash"], "state")
            self.assertEqual(record["model"], "test/model")
            self.assertEqual(
                data["violations"][0]["fingerprint"], key
            )

class InstalledToolRootTests(unittest.TestCase):
    def test_tool_root_is_the_package_directory(self):
        runtime = LintelRuntime(".")
        self.assertEqual(runtime.tool_root, os.path.dirname(os.path.dirname(runtime_module.__file__)))
        for name in ("Lintel.lean", "lean-toolchain", "lakefile.toml"):
            self.assertTrue(os.path.isfile(os.path.join(runtime.tool_root, name)))


class AgentInstructionTests(unittest.TestCase):
    def test_scaffold_writes_harness_neutral_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            LintelRuntime(directory).scaffold("clean", directory)
            for name, content in agent_files.FILES.items():
                with open(os.path.join(directory, name), encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), content)
            with open(os.path.join(directory, "AGENTS.md"), encoding="utf-8") as handle:
                self.assertIn("lintel hook", handle.read())
            with open(os.path.join(directory, "SKILL.md"), encoding="utf-8") as handle:
                self.assertIn("lintel check", handle.read())
            with open(os.path.join(directory, "HARNESS_SETUP.md"), encoding="utf-8") as handle:
                self.assertIn("lintel hook", handle.read())


class TypeScriptExtractorTests(unittest.TestCase):
    def test_multiline_imports_and_exports_produce_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            source_dir = os.path.join(directory, "src")
            os.makedirs(source_dir)
            with open(os.path.join(source_dir, "a.ts"), "w", encoding="utf-8") as handle:
                handle.write(
                    'import {\n  first,\n  second as alias\n} from "./b";\n'
                    'export {\n  alias\n} from "./b";\n'
                )
            with open(os.path.join(source_dir, "b.ts"), "w", encoding="utf-8") as handle:
                handle.write("export const first = 1;\n")

            data = typescript_extractor.extract(directory)
            dependencies = {
                (item["from"], item["to"], item["line"])
                for item in data["dependencies"]
            }
            self.assertIn(("src/a", "src/b", 1), dependencies)
            self.assertIn(("src/a", "src/b", 5), dependencies)
            self.assertEqual(data["unparsed"], [])

    def test_non_literal_dynamic_dependency_stays_unparsed(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "a.ts"), "w", encoding="utf-8") as handle:
                handle.write('const name = "b";\nimport(name);\n')
            data = typescript_extractor.extract(directory)
            self.assertEqual(len(data["unparsed"]), 1)
            self.assertEqual(data["unparsed"][0]["line"], 2)
            self.assertEqual(
                data["unparsed"][0]["reason"],
                "dynamic dependency with non-literal specifier",
            )


class RustExtractorTests(unittest.TestCase):
    @staticmethod
    def write(directory, relative, content):
        path = os.path.join(directory, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_literal_path_attribute_maps_file_to_declared_module(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "Cargo.toml", '[package]\nname = "demo"\nversion = "0.1.0"\n')
            self.write(directory, "src/lib.rs", '#[path = "custom.rs"]\nmod inner;\n')
            self.write(directory, "src/custom.rs", "use crate::helper;\n")
            self.write(directory, "src/helper.rs", "pub fn helper() {}\n")

            data = rust_extractor.extract(directory)
            modules = {item["name"]: item["path"] for item in data["modules"]}
            self.assertEqual(modules.get("demo::inner"), "src/custom.rs")
            self.assertNotIn("demo::custom", modules)
            dependencies = {
                (item["from"], item["to"], item["source"])
                for item in data["dependencies"]
            }
            self.assertIn(("demo::inner", "demo::helper", "src/custom.rs"), dependencies)
            self.assertEqual(data["unparsed"], [])

    def test_literal_include_attributes_items_to_including_module(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "Cargo.toml", '[package]\nname = "demo"\nversion = "0.1.0"\n')
            self.write(directory, "src/lib.rs", 'include!("defs.rs");\n')
            self.write(directory, "src/defs.rs", "use crate::helper;\n")
            self.write(directory, "src/helper.rs", "pub fn helper() {}\n")

            data = rust_extractor.extract(directory)
            modules = {item["name"] for item in data["modules"]}
            self.assertNotIn("demo::defs", modules)
            dependencies = {
                (item["from"], item["to"], item["source"])
                for item in data["dependencies"]
            }
            self.assertIn(("demo", "demo::helper", "src/defs.rs"), dependencies)
            self.assertEqual(data["unparsed"], [])

    def test_non_literal_forms_and_macros_stay_unparsed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(
                directory,
                "src/lib.rs",
                'include!(format!("{}.rs", name));\n'
                "#[path = module_name()] mod inner;\n"
                "macro_rules! generate { () => {} }\n",
            )
            data = rust_extractor.extract(directory)
            reasons = {item["reason"] for item in data["unparsed"]}
            self.assertIn("include! can inject dependencies", reasons)
            self.assertIn("#[path] changes module paths", reasons)
            self.assertIn("macro_rules! can generate imports", reasons)
            self.assertEqual(data["dependencies"], [])

    def test_literal_path_attribute_handles_pub_mod(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "Cargo.toml", '[package]\nname = "demo"\nversion = "0.1.0"\n')
            self.write(
                directory,
                "src/lib.rs",
                '#[path = "custom.rs"]\npub(crate) mod inner;\n',
            )
            self.write(directory, "src/custom.rs", "use crate::helper;\n")
            self.write(directory, "src/helper.rs", "pub fn helper() {}\n")

            data = rust_extractor.extract(directory)
            modules = {item["name"]: item["path"] for item in data["modules"]}
            self.assertEqual(modules.get("demo::inner"), "src/custom.rs")
            self.assertEqual(data["unparsed"], [])

    def test_missing_literal_include_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "src/lib.rs", 'include!("missing.rs");\n')
            data = rust_extractor.extract(directory)
            self.assertEqual(len(data["unparsed"]), 1)
            self.assertEqual(data["unparsed"][0]["reason"], "include! target not found")


class GoExtractorTests(unittest.TestCase):
    TARGET = ("linux", "amd64", None)

    @staticmethod
    def write(directory, relative, content):
        path = os.path.join(directory, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_active_go_build_tag_produces_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "go.mod", "module example.com/demo\n")
            self.write(
                directory,
                "main.go",
                '//go:build linux && amd64\n\npackage main\n\n'
                'import "example.com/demo/helper"\n',
            )
            self.write(directory, "helper/helper.go", "package helper\n")

            data = go_extractor.extract(directory, target=self.TARGET)
            dependencies = {
                (item["from"], item["to"], item["source"])
                for item in data["dependencies"]
            }
            self.assertIn(
                ("example.com/demo", "example.com/demo/helper", "main.go"),
                dependencies,
            )
            self.assertEqual(data["unparsed"], [])

    def test_inactive_go_build_tag_is_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "go.mod", "module example.com/demo\n")
            self.write(
                directory,
                "main.go",
                '//go:build windows\n\npackage main\n\n'
                'import "example.com/demo/helper"\n',
            )
            self.write(directory, "helper/helper.go", "package helper\n")

            data = go_extractor.extract(directory, target=self.TARGET)
            self.assertEqual(data["dependencies"], [])
            self.assertEqual([item["name"] for item in data["modules"]], ["example.com/demo/helper"])
            self.assertEqual(data["unparsed"], [])

    def test_legacy_plus_build_tags_are_evaluated(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "go.mod", "module example.com/demo\n")
            self.write(
                directory,
                "active.go",
                '// +build linux,amd64 darwin\n\npackage main\n\n'
                'import "example.com/demo/helper"\n',
            )
            self.write(
                directory,
                "inactive.go",
                '// +build windows\n\npackage main\n\n'
                'import "example.com/demo/helper"\n',
            )
            self.write(directory, "helper/helper.go", "package helper\n")

            data = go_extractor.extract(directory, target=self.TARGET)
            sources = {item["source"] for item in data["dependencies"]}
            self.assertEqual(sources, {"active.go"})
            self.assertEqual(data["unparsed"], [])

    def test_indeterminate_constraint_stays_unparsed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "go.mod", "module example.com/demo\n")
            self.write(
                directory,
                "main.go",
                '//go:build customtag\n\npackage main\n\n'
                'import "example.com/demo/helper"\n',
            )
            self.write(directory, "helper/helper.go", "package helper\n")

            data = go_extractor.extract(directory, target=self.TARGET)
            self.assertEqual(
                [item["reason"] for item in data["unparsed"]],
                ["indeterminate build constraint"],
            )
            self.assertEqual(len(data["dependencies"]), 1)

    def test_unsupported_legacy_constraint_with_go_build_stays_unparsed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "go.mod", "module example.com/demo\n")
            self.write(
                directory,
                "main.go",
                '//go:build linux\n// +build customtag\n\npackage main\n\n'
                'import "example.com/demo/helper"\n',
            )
            self.write(directory, "helper/helper.go", "package helper\n")

            data = go_extractor.extract(directory, target=self.TARGET)
            self.assertEqual(
                [item["reason"] for item in data["unparsed"]],
                ["indeterminate build constraint"],
            )
            self.assertEqual(len(data["dependencies"]), 1)

    def test_unparseable_import_stays_unparsed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "go.mod", "module example.com/demo\n")
            self.write(directory, "main.go", "package main\n\nimport (\n")
            data = go_extractor.extract(directory, target=self.TARGET)
            self.assertEqual(
                [item["reason"] for item in data["unparsed"]],
                ["unterminated import block"],
            )

if __name__ == "__main__":
    unittest.main()
