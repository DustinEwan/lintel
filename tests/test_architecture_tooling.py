import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "adapters"))

from adapters import architecture_config, contract_facts, contract_lock, incremental_cache, lean_generator
from adapters.language import PythonSourceAnalyzer, analyzer_for_suffix
from adapters.runtime import ArchitectureRuntime
from architecture_core.checker import (
    check_boundary_concerns,
    check_executables,
    check_wrapper_operations,
    check,
    module_name_from_path,
    region_for,
    check_semantic_review,
)
from architecture_core.model import (
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
    Violation,
    WrapperOperation,
)
from architecture_core.ratchet import compare_baseline, violation_fingerprint

CONFIG_PATH = os.path.join(ROOT, "architecture.toml")


def real_policy():
    config = architecture_config.load_config(CONFIG_PATH)
    return policy_from_dict(architecture_config.policy_from_config(config))


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
        violations = architecture_config.validate_config(config)
        self.assertIn("config_unknown_key", rules(violations))
        self.assertIn("config_bad_reference", rules(violations))

    def test_missing_source_suffixes_is_rejected(self):
        config = architecture_config.load_config(CONFIG_PATH)
        del config["analysis"]["source_suffixes"]
        violations = architecture_config.validate_config(config, ROOT)
        self.assertIn("config_invalid", rules(violations))

    def test_invalid_source_suffixes_are_rejected(self):
        config = architecture_config.load_config(CONFIG_PATH)
        config["analysis"]["source_suffixes"] = ".py"
        violations = architecture_config.validate_config(config, ROOT)
        self.assertIn("config_invalid", rules(violations))

    def test_new_adapters_subpackages_use_adapters_layer(self):
        self.assertEqual(
            region_for("adapters.language.future_analyzer", real_policy()).name,
            "adapters",
        )

    def test_boundary_patterns_key_is_rejected(self):
        config = architecture_config.load_config(CONFIG_PATH)
        config["boundary_concerns"]["mechanism"]["patterns"] = ["print"]
        violations = architecture_config.validate_config(config, ROOT)
        self.assertIn("config_unknown_key", rules(violations))


class ExecutableRuleTests(unittest.TestCase):
    def test_undeclared_entrypoint_is_reported(self):
        policy = real_policy()
        facts = FactSet(
            modules=declared_modules(policy),
            entrypoints=(Entrypoint("unknown_cli", "external/cli/unknown.py"),),
        )
        self.assertIn("undeclared_executable", rules(check_executables(facts, policy)))

    def test_declared_entrypoint_is_allowed(self):
        policy = real_policy()
        facts = FactSet(
            modules=declared_modules(policy),
            entrypoints=(Entrypoint("external.cli.check_self", "external/cli/check_self.py"),),
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
                    "external.cli.check_self", "argv_parse", "entrypoint_only",
                    "external/cli/check_self.py", 10,
                ),
            ),
            scopes=(
                ScopeAssignment(
                    "adapters/go-extractor/main.go", "build_artifact", "adapters/go-extractor/main.go", 30
                ),
            ),
        )
        facts = FactSet(
            concerns=facts.concerns + (
                BoundaryConcernUse(
                    "main", "argv_parse", "entrypoint_only",
                    "adapters/go-extractor/main.go", 5,
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
                    "external.cli.extract_python", "import",
                    "adapters.python_extractor.extract", "external/cli/extract_python.py", 13,
                ),
                WrapperOperation(
                    "external.cli.extract_rust_native", "subprocess",
                    "cargo", "external/cli/extract_rust_native.py", 22,
                ),
            )
        )
        self.assertEqual(check_wrapper_operations(facts, policy), ())

    def test_checker_import_is_fat(self):
        policy = real_policy()
        facts = FactSet(
            wrapper_operations=(
                WrapperOperation(
                    "external.cli.bad", "import", "architecture_core.checker",
                    "external/cli/bad.py", 3,
                ),
            )
        )
        self.assertIn("fat_entrypoint", rules(check_wrapper_operations(facts, policy)))

    def test_analyzer_detects_run_with_cwd(self):
        analysis = PythonSourceAnalyzer().analyze(
            "external/cli/sample.py",
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

    def test_non_baselineable_violations_pass_through(self):
        violation = Violation("unparsed_source", "bad", {"location": "a.py:1"})
        key = violation_fingerprint(violation)
        result = compare_baseline(
            (violation,), [{"fingerprint": key, "rule": "unparsed_source"}]
        )
        self.assertEqual(result, (violation,))

    def test_accept_baseline_rejects_contract_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ArchitectureRuntime(directory)
            with self.assertRaises(SystemExit):
                runtime.accept_baseline(
                    "architecture.toml", (Violation("config_invalid", "bad"),)
                )


class LockTests(unittest.TestCase):
    def test_config_digest_changes_with_semantic_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, "architecture.toml")
            with open(config, "w", encoding="utf-8") as handle:
                handle.write('version = 1\n[paths]\nentrypoints_root = "cli"\n')
            first = contract_lock.config_digest(config)
            with open(config, "w", encoding="utf-8") as handle:
                handle.write('version = 1\n[paths]\nentrypoints_root = "external/cli"\n')
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
            runtime = ArchitectureRuntime(directory)
            runtime.scaffold("clean", directory)
            config = os.path.join(directory, "architecture.toml")
            data = architecture_config.load_config(config)
            self.assertEqual(architecture_config.validate_config(data, directory), ())
            with open(os.path.join(directory, "architecture.baseline.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["violations"], [])





class IncrementalCacheTests(unittest.TestCase):
    def test_fact_cache_hit_avoids_reextraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "adapters"))
            source = os.path.join(tmp, "adapters", "demo.py")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("value = 1\n")
            runtime = ArchitectureRuntime(tmp)
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
            runtime = ArchitectureRuntime(tmp)
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
from adapters import architecture_config, lean_generator
from architecture_core.model import Dependency, FactSet, Module, policy_from_dict
config = architecture_config.load_config(root + "/architecture.toml")
policy = policy_from_dict(architecture_config.policy_from_config(config))
facts = FactSet(
    modules=(
        Module("adapters.one", "adapters/one.py"),
        Module("architecture_core.two", "architecture_core/two.py"),
        Module("external.cli.three", "external/cli/three.py"),
    ),
    dependencies=(
        Dependency("adapters.one", "architecture_core.two"),
        Dependency("external.cli.three", "adapters.one"),
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
                Module("adapters.contract_facts"),
                Module("architecture_core.checker"),
            ),
            dependencies=(
                Dependency("adapters.contract_facts", "architecture_core.checker"),
            ),
        )
        source = lean_generator.generate(facts, policy)
        self.assertIn("import Architecture", source)
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
                Module("external.cli.caller", "external/cli/caller.py"),
                Module("adapters.other", "adapters/other.py"),
            ),
            wrapper_operations=(
                WrapperOperation(
                    "external.cli.caller",
                    "subprocess",
                    "tools/cargo",
                    "external/cli/caller.py",
                    1,
                ),
            ),
        )
        source = lean_generator.generate(facts, policy)
        caller = module_ctor(source, "external.cli.caller")
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
            runtime = ArchitectureRuntime(tmp)
            runtime.accept_baseline(CONFIG_PATH, violations)
            path = os.path.join(tmp, "architecture.baseline.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["violations"][0].get("location"), "")
            self.assertEqual(
                runtime.accepted_review_sources(path, facts, policy),
                ("adapters/impl.py",),
            )


    def test_generated_rank_decreases_along_dependencies(self):
        policy = real_policy()
        facts = FactSet(
            modules=(
                Module("adapters.contract_facts"),
                Module("architecture_core.model"),
            ),
            dependencies=(
                Dependency("adapters.contract_facts", "architecture_core.model"),
            ),
        )
        source = lean_generator.generate(facts, policy)
        source_ctor = module_ctor(source, "adapters.contract_facts")
        target_ctor = module_ctor(source, "architecture_core.model")
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
                Module("architecture_core.use_cases.bad"),
                Module("adapters.impl"),
            ),
            dependencies=(
                Dependency(
                    "architecture_core.use_cases.bad",
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
            runtime = ArchitectureRuntime(directory)
            runtime.scaffold("clean", directory)
            path = os.path.join(directory, "adapters", "review_me.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("import os\nvalue = getattr(os, \"environ\")\n")
            config = runtime.load_self_config("architecture.toml", True)
            facts = runtime.collect_self_facts(config, PathOverrides())
            violations = check(facts, config.policy)
        self.assertTrue(
            any(item.rule == "semantic_review" for item in violations)
        )

class EscapeHatchTests(unittest.TestCase):
    def test_declared_unsupported_suffix_fails_closed(self):
        config = architecture_config.load_config(os.path.join(ROOT, "architecture.toml"))
        config["analysis"]["source_suffixes"] = [
            *config["analysis"]["source_suffixes"],
            ".zig",
        ]
        policy = policy_from_dict(architecture_config.policy_from_config(config))
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
        config = architecture_config.load_config(os.path.join(ROOT, "architecture.toml"))
        policy = policy_from_dict(architecture_config.policy_from_config(config))
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
        config = architecture_config.load_config(os.path.join(ROOT, "architecture.toml"))
        config["analysis"]["source_suffixes"] = [
            suffix
            for suffix in config["analysis"]["source_suffixes"]
            if suffix != ".py"
        ]
        policy = policy_from_dict(architecture_config.policy_from_config(config))
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
        self.assertEqual(check_semantic_review(excluded, policy), [])
        included = FactSet(reviews=analysis.reviews)
        self.assertTrue(
            any(item.rule == "semantic_review" for item in check_semantic_review(included, policy))
        )

if __name__ == "__main__":
    unittest.main()
