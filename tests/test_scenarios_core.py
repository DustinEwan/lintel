"""Core scenario coverage."""

from dataclasses import replace
import os
import subprocess
import tempfile
import unittest

from lintel.adapters import policy_diff
from lintel.core.checker import (
    check_boundary_concerns,
    transitive_boundary_concerns,
    wrapper_boundary_reviews,
    wrapper_concern_attributions,
)
from lintel.core.model import (
    BoundaryConcernUse,
    BuildArtifact,
    Dependency,
    FactSet,
    Module,
    Policy,
    Region,
    ScopeAssignment,
    WrapperOperation,
)


def scenario_policy():
    return Policy(
        default_region="external",
        regions=(
            Region("core", True, ("core.*",)),
            Region("entrypoints", False, ("extract_native",)),
            Region("adapters", False, ("adapters.*",)),
        ),
        allowed={
            "core": ("core", "platform"),
            "adapters": ("core", "adapters", "platform"),
        },
        forbidden={},
        boundary_allowed_regions={"mechanism": ("adapters",)},
        build_artifacts=(BuildArtifact("native/main.rs", "extract_native"),),
    )


class WrapperScenarioTests(unittest.TestCase):
    def test_sem10_native_concern_is_attributed_to_declared_wrapper(self):
        facts = FactSet(
            modules=(
                Module("extract_native", "cli/extract_native.py"),
                Module("native_main", "native/main.rs"),
            ),
            concerns=(
                BoundaryConcernUse(
                    "native_main", "argv_parse", "entrypoint_only", "native/main.rs", 1
                ),
            ),
            scopes=(ScopeAssignment("native/main.rs", "build_artifact"),),
            wrapper_operations=(
                WrapperOperation(
                    "extract_native", "subprocess", "native/main", "cli/extract_native.py", 3
                ),
            ),
        )
        attributed = wrapper_concern_attributions(facts, scenario_policy())
        self.assertEqual(
            [(item.module, item.source, item.line) for item in attributed],
            [("extract_native", "cli/extract_native.py", 3)],
        )
        self.assertEqual(wrapper_boundary_reviews(facts, scenario_policy()), ())

    def test_sem10_missing_invocation_is_a_bounded_review(self):
        facts = FactSet(
            modules=(Module("extract_native", "cli/extract_native.py"),),
            concerns=(
                BoundaryConcernUse(
                    "native_main", "argv_parse", "entrypoint_only", "native/main.rs", 1
                ),
            ),
            scopes=(ScopeAssignment("native/main.rs", "build_artifact"),),
        )
        reviews = wrapper_boundary_reviews(facts, scenario_policy())
        self.assertEqual(len(reviews), 1)
        self.assertIn("SEM-10", reviews[0].reason)
        self.assertLessEqual(len(reviews[0].reason), 200)

    def test_sem10_wrapper_exit_concern_is_expected(self):
        facts = FactSet(
            modules=(Module("extract_native", "cli/extract_native.py"),),
            concerns=(
                BoundaryConcernUse("native_main", "argv_parse", "entrypoint_only", "native/main.rs", 1),
                BoundaryConcernUse("extract_native", "exit", "mechanism", "cli/extract_native.py", 33),
            ),
            scopes=(ScopeAssignment("native/main.rs", "build_artifact"),),
            wrapper_operations=(
                WrapperOperation("extract_native", "subprocess", "native/main", "cli/extract_native.py", 3),
            ),
        )
        self.assertEqual(wrapper_boundary_reviews(facts, scenario_policy()), ())


class TransitiveScenarioTests(unittest.TestCase):
    def test_sem15_mechanism_concern_propagates_to_core_importer(self):
        facts = FactSet(
            modules=(
                Module("core.service", "core/service.py"),
                Module("adapters.io", "adapters/io.py"),
            ),
            dependencies=(
                Dependency("core.service", "adapters.io", source="core/service.py", line=2),
            ),
            concerns=(
                BoundaryConcernUse("adapters.io", "env", "mechanism", "adapters/io.py", 1),
            ),
        )
        synthetic, reviews = transitive_boundary_concerns(facts, scenario_policy())
        self.assertEqual(
            [(item.module, item.source, item.line) for item in synthetic],
            [("core.service", "core/service.py", 2)],
        )
        self.assertEqual(reviews, ())

    def test_sem15_non_mechanism_concern_is_ignored(self):
        facts = FactSet(
            modules=(
                Module("adapters.first", "adapters/first.py"),
                Module("adapters.second", "adapters/second.py"),
            ),
            dependencies=(
                Dependency("adapters.first", "adapters.second", source="adapters/first.py", line=2),
            ),
            concerns=(
                BoundaryConcernUse("adapters.second", "argv_parse", "entrypoint_only", "adapters/second.py", 1),
            ),
        )
        synthetic, reviews = transitive_boundary_concerns(facts, scenario_policy())
        self.assertEqual(synthetic, ())
        self.assertEqual(reviews, ())

    def test_sem15_declared_wrapper_bridge_propagates_to_core_importer(self):
        policy = replace(
            scenario_policy(),
            build_artifacts=(BuildArtifact("native/main.rs", "adapters.wrapper"),),
        )
        facts = FactSet(
            modules=(
                Module("core.service", "core/service.py"),
                Module("adapters.wrapper", "adapters/wrapper.py"),
                Module("adapters.artifact", "native/main.rs"),
            ),
            dependencies=(
                Dependency("core.service", "adapters.wrapper", source="core/service.py", line=2),
            ),
            concerns=(
                BoundaryConcernUse("adapters.artifact", "env", "mechanism", "native/main.rs", 1),
            ),
            wrapper_operations=(
                WrapperOperation("adapters.wrapper", "subprocess", "native/main.rs", "adapters/wrapper.py", 3),
            ),
        )
        synthetic, reviews = transitive_boundary_concerns(facts, policy)
        self.assertIn(
            ("core.service", "core/service.py", 2),
            [(item.module, item.source, item.line) for item in synthetic],
        )
        self.assertEqual(reviews, ())

    def test_sem15_unresolved_core_wrapper_target_is_reviewed(self):
        policy = replace(
            scenario_policy(),
            build_artifacts=(BuildArtifact("native/missing.rs", "core.runner"),),
        )
        facts = FactSet(
            modules=(Module("core.runner", "core/runner.py"),),
            wrapper_operations=(
                WrapperOperation("core.runner", "subprocess", "native/missing.rs", "core/runner.py", 4),
            ),
        )
        synthetic, reviews = transitive_boundary_concerns(facts, policy)
        self.assertEqual(synthetic, ())
        self.assertEqual(len(reviews), 1)
        self.assertIn(
            "SEM-15 wrapper target 'native/missing.rs' cannot be resolved",
            reviews[0].reason,
        )


class GeneratedScopeScenarioTests(unittest.TestCase):
    def test_sem08_declared_generated_and_vendor_concerns_are_skipped(self):
        policy = replace(scenario_policy(), excluded_scopes=("generated", "vendor"))
        facts = FactSet(
            concerns=(
                BoundaryConcernUse("generated_client", "terminal_io", "mechanism", "generated/client.rs", 1),
                BoundaryConcernUse("vendor_client", "logging", "mechanism", "vendor/client.rs", 1),
            ),
            scopes=(
                ScopeAssignment("generated/client.rs", "generated"),
                ScopeAssignment("vendor/client.rs", "vendor"),
            ),
        )
        self.assertEqual(check_boundary_concerns(facts, policy), ())
        synthetic, reviews = transitive_boundary_concerns(facts, policy)
        self.assertEqual((synthetic, reviews), ((), ()))

        unscoped = FactSet(
            concerns=(
                BoundaryConcernUse("sample", "terminal_io", "mechanism", "sample.rs", 1),
            )
        )
        self.assertTrue(check_boundary_concerns(unscoped, policy))

class PolicyDiffScenarioTests(unittest.TestCase):
    def _repository(self, directory):
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.com",
            }
        )

        def git(*arguments):
            subprocess.run(["git", *arguments], cwd=directory, check=True, env=env, capture_output=True)

        git("init", "-q")
        with open(os.path.join(directory, "lintel.toml"), "w", encoding="utf-8") as handle:
            handle.write(
                "[boundary_concerns.entrypoint_only]\n"
                "allowed_regions = [\"entrypoints\"]\n"
            )
        os.makedirs(os.path.join(directory, "adapters"), exist_ok=True)
        with open(os.path.join(directory, "adapters", "sample.py"), "w", encoding="utf-8") as handle:
            handle.write("value = 1\n")
        git("add", "-A")
        git("commit", "-q", "-m", "baseline")
        return git

    def test_sem16_policy_weakening_with_new_concern_is_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            self._repository(directory)
            with open(os.path.join(directory, "lintel.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    "[boundary_concerns.entrypoint_only]\n"
                    "allowed_regions = [\"entrypoints\", \"adapters\"]\n"
                )
            with open(os.path.join(directory, "adapters", "sample.py"), "w", encoding="utf-8") as handle:
                handle.write("import argparse\nparser = argparse.ArgumentParser()\n")
            facts = FactSet(
                concerns=(
                    BoundaryConcernUse("sample", "argv_parse", "entrypoint_only", "adapters/sample.py", 2),
                )
            )
            reviews = policy_diff.detect(directory, facts)
            self.assertEqual(len(reviews), 1)
            self.assertIn("SEM-16", reviews[0].reason)

    def test_sem16_policy_weakening_without_new_concern_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            self._repository(directory)
            with open(os.path.join(directory, "lintel.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    "[boundary_concerns.entrypoint_only]\n"
                    "allowed_regions = [\"entrypoints\", \"adapters\"]\n"
                )
            reviews = policy_diff.detect(directory, FactSet())
            self.assertEqual(reviews, ())

    def test_sem16_source_change_without_policy_change_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            self._repository(directory)
            with open(os.path.join(directory, "adapters", "sample.py"), "w", encoding="utf-8") as handle:
                handle.write("import argparse\nparser = argparse.ArgumentParser()\n")
            facts = FactSet(
                concerns=(
                    BoundaryConcernUse("sample", "argv_parse", "entrypoint_only", "adapters/sample.py", 2),
                )
            )
            self.assertEqual(policy_diff.detect(directory, facts), ())

    def test_sem16_staged_policy_weakening_and_staged_concern_are_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            git = self._repository(directory)
            with open(os.path.join(directory, "lintel.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    "[boundary_concerns.entrypoint_only]\n"
                    "allowed_regions = [\"entrypoints\", \"adapters\"]\n"
                )
            with open(os.path.join(directory, "adapters", "sample.py"), "w", encoding="utf-8") as handle:
                handle.write("import argparse\nparser = argparse.ArgumentParser()\n")
            git("add", "lintel.toml", "adapters/sample.py")
            facts = FactSet(
                concerns=(
                    BoundaryConcernUse("sample", "argv_parse", "entrypoint_only", "adapters/sample.py", 2),
                )
            )
            reviews = policy_diff.detect(directory, facts)
            self.assertEqual(len(reviews), 1)
            self.assertIn("argv_parse", reviews[0].reason)

    def test_sem16_untracked_source_with_tracked_policy_weakening_is_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            git = self._repository(directory)
            with open(os.path.join(directory, "lintel.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    "[boundary_concerns.entrypoint_only]\n"
                    "allowed_regions = [\"entrypoints\", \"adapters\"]\n"
                )
            git("add", "lintel.toml")
            untracked_path = os.path.join(directory, "adapters", "untracked.py")
            with open(untracked_path, "w", encoding="utf-8") as handle:
                handle.write("import argparse\nparser = argparse.ArgumentParser()\n")
            facts = FactSet(
                concerns=(
                    BoundaryConcernUse("untracked", "argv_parse", "entrypoint_only", "adapters/untracked.py", 2),
                )
            )
            reviews = policy_diff.detect(directory, facts)
            self.assertEqual(len(reviews), 1)
            self.assertIn("adapters/untracked.py:2", reviews[0].reason)

    def test_sem16_replaced_forbidden_entry_is_weakening(self):
        before = {"layers": {"core": {"core": True, "forbidden": ["one", "two"]}}}
        after = {"layers": {"core": {"core": True, "forbidden": ["one", "three"]}}}
        self.assertTrue(policy_diff._policy_weakened(before, after))

    def test_sem16_build_artifact_weakening_is_detected(self):
        before = {
            "build_artifacts": [
                {"source": "a", "wrapper": "one"},
                {"source": "b", "wrapper": "two"},
            ]
        }
        after = {"build_artifacts": [{"source": "a", "wrapper": "one"}]}
        self.assertTrue(policy_diff._policy_weakened(before, after))


if __name__ == "__main__":
    unittest.main()
