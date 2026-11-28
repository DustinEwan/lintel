import json
import os
import subprocess
import sys
import tempfile
import unittest

from lintel.adapters.graph_queries import (
    concern_context,
    module_impact,
    review_drift,
    symbol_impact,
)
from lintel.core import checker
from lintel.core.model import (
    Dependency,
    Entrypoint,
    FactSet,
    Module,
    SemanticDecision,
    SemanticReview,
    facts_to_dict,
)
from lintel.core.ratchet import violation_fingerprint

from test_lintel_tooling import ROOT, CallGraphTests, real_policy


def _accepting_decision(review):
    finding = checker.violation(
        "semantic_review",
        f"semantic review: {review.reason} ({review.source}:{review.line})",
        module=review.module,
        source=review.source,
        line=review.line,
        location=f"{review.source}:{review.line}",
        reason=review.reason,
        graph_state_hash="",
    )
    return SemanticDecision(
        violation_fingerprint(finding),
        "compliant",
        "reviewed",
        0.99,
        "test",
    )


class GraphQueryTests(unittest.TestCase):
    def test_module_impact_returns_reverse_dependencies_and_paths(self):
        facts = FactSet(
            modules=(
                Module("core.target", "core/target.py"),
                Module("adapters.a", "adapters/a.py"),
                Module("cli.b", "cli/b.py"),
            ),
            dependencies=(
                Dependency("adapters.a", "core.target", "adapters/a.py", 2),
                Dependency("cli.b", "adapters.a", "cli/b.py", 3),
            ),
            entrypoints=(Entrypoint("cli.b", "cli/b.py"),),
        )

        result = module_impact(facts, real_policy(), "core.target")

        self.assertEqual(result["affected_modules"], ("adapters.a", "cli.b"))
        self.assertEqual(result["direct_importers"], ("adapters.a",))
        self.assertEqual(result["paths"], (("adapters.a", "core.target"),))
        self.assertEqual(
            result["entrypoints"],
            ({"module": "cli.b", "path": "cli/b.py", "kind": "python"},),
        )

    def test_symbol_impact_follows_direct_callers(self):
        facts, helper, adapter = CallGraphTests()._helper_facts()

        result = symbol_impact(facts, real_policy(), helper.key)

        self.assertEqual(result["target"]["module"], helper.module)
        self.assertEqual(result["callers"], (adapter.key,))
        self.assertEqual(result["paths"], ((adapter.key, helper.key),))
        self.assertEqual(result["modules"], (adapter.module,))

    def test_concern_context_reports_origins(self):
        facts, helper, _ = CallGraphTests()._helper_facts()

        result = concern_context(facts, "lintel.helpers")

        self.assertEqual(
            result["declared"][0]["concern"],
            "argv",
        )
        self.assertIn(helper.key, [item["symbol"] for item in result["origins"]])

    def test_review_drift_detects_changed_graph_context(self):
        review = SemanticReview(
            "lintel.helpers", "lintel/helpers.py", 2, "argv parsing"
        )
        decision = _accepting_decision(review)
        modules = (
            Module("lintel.helpers", "lintel/helpers.py"),
            Module("lintel.adapters.use", "lintel/adapters/use.py"),
        )
        before = FactSet(
            modules=modules, reviews=(review,), decisions=(decision,)
        )
        after = FactSet(
            modules=modules,
            dependencies=(
                Dependency(
                    "lintel.adapters.use",
                    "lintel.helpers",
                    "lintel/adapters/use.py",
                    3,
                ),
            ),
            reviews=(review,),
            decisions=(decision,),
        )

        drifted = review_drift(before, after)
        unchanged = review_drift(before, before)

        self.assertEqual(len(drifted), 1)
        self.assertEqual(drifted[0]["fingerprint"], decision.fingerprint)
        self.assertTrue(drifted[0]["added_edges"])
        self.assertEqual(unchanged, ())

    def test_cli_query_commands_dispatch(self):
        review = SemanticReview(
            "lintel.helpers", "lintel/helpers.py", 2, "argv parsing"
        )
        decision = _accepting_decision(review)
        before = FactSet(
            modules=(Module("lintel.helpers", "lintel/helpers.py"),),
            reviews=(review,),
            decisions=(decision,),
        )
        after = FactSet(
            modules=(
                Module("lintel.helpers", "lintel/helpers.py"),
                Module("lintel.adapters.use", "lintel/adapters/use.py"),
            ),
            dependencies=(
                Dependency(
                    "lintel.adapters.use",
                    "lintel.helpers",
                    "lintel/adapters/use.py",
                    3,
                ),
            ),
            reviews=(review,),
            decisions=(decision,),
        )
        cli = os.path.join(ROOT, "lintel", "cli", "main.py")

        with tempfile.TemporaryDirectory() as tmp:
            before_path = os.path.join(tmp, "before.json")
            after_path = os.path.join(tmp, "after.json")
            for path, facts in ((before_path, before), (after_path, after)):
                with open(path, "w", encoding="utf-8") as stream:
                    json.dump(facts_to_dict(facts), stream)

            drift = subprocess.run(
                [
                    sys.executable,
                    cli,
                    "review-drift",
                    "--before",
                    before_path,
                    "--facts",
                    after_path,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            impact = subprocess.run(
                [
                    sys.executable,
                    cli,
                    "impact",
                    "--module",
                    "lintel.helpers",
                    "--facts",
                    after_path,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

        self.assertEqual(len(json.loads(drift.stdout)), 1)
        self.assertEqual(
            json.loads(impact.stdout)["target"],
            {"kind": "module", "name": "lintel.helpers"},
        )


if __name__ == "__main__":
    unittest.main()
