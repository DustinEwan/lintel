import os
import tempfile
import unittest

from lintel.adapters import source_graph_python
from lintel.adapters.language.python_analyzer import (
    PythonSourceAnalyzer,
    configure_env_call_patterns,
)


def concern_lines(analysis, concern):
    return [item.line for item in analysis.concerns if item.concern == concern]


class PythonScenarioTests(unittest.TestCase):
    def setUp(self):
        configure_env_call_patterns(())

    def tearDown(self):
        configure_env_call_patterns(())

    def test_sem02_reexport_chain_resolves_to_boundary_concern(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py",
            "from os import environ as env\nother = env\nvalue = other\n",
        )
        self.assertEqual(concern_lines(analysis, "env"), [1, 2, 3])
        self.assertEqual(analysis.reviews, ())


    def test_sem01_rebound_module_alias_is_reviewed_not_deterministic(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py",
            "import os as s\ns = factory()\nvalue = s.environ\n",
        )
        self.assertEqual(concern_lines(analysis, "env"), [])
        self.assertEqual(len(analysis.reviews), 1)
        self.assertEqual(analysis.reviews[0].line, 3)
        self.assertIn("unresolved alias 's'", analysis.reviews[0].reason)

    def test_sem02_rebound_from_import_subscript_is_reviewed(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py",
            "from os import environ as env\nenv = factory()\nhome = env[\"HOME\"]\n",
        )
        self.assertEqual(concern_lines(analysis, "env"), [1])
        self.assertEqual(len(analysis.reviews), 1)
        self.assertEqual(analysis.reviews[0].line, 3)
        self.assertIn("unresolved alias 'env'", analysis.reviews[0].reason)

    def test_sem02_wildcard_boundary_import_is_reviewed(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py", "from os import *\nvalue = environ\n"
        )
        self.assertTrue(
            any("wildcard import from os" in item.reason for item in analysis.reviews)
        )

    def test_sem03_literal_reflection_is_deterministic(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py",
            "import os\nimport importlib\nx = getattr(os, \"environ\")\n"
            "y = importlib.import_module(\"sys\").argv\n",
        )
        self.assertEqual(concern_lines(analysis, "env"), [3])
        self.assertEqual(concern_lines(analysis, "argv"), [4])

    def test_sem05_unknown_cli_framework_decorator_is_reviewed(self):
        source = (
            "from acme_cli import app\n"
            "@app.command()\n"
            "def run():\n"
            "    return 1\n"
        )
        adapter = PythonSourceAnalyzer().analyze("adapters/sample.py", source)
        self.assertTrue(
            any("unresolved CLI framework" in item.reason for item in adapter.reviews)
        )
        entrypoint = PythonSourceAnalyzer().analyze("lintel/cli/sample.py", source)
        self.assertEqual(entrypoint.reviews, ())

    def test_sem05_unknown_group_decorator_is_reviewed(self):
        source = (
            "from acme_cli import app\n"
            "@app.group()\n"
            "def run():\n"
            "    return 1\n"
        )
        adapter = PythonSourceAnalyzer().analyze("adapters/sample.py", source)
        self.assertEqual(len(adapter.reviews), 1)
        self.assertIn("unresolved CLI framework", adapter.reviews[0].reason)
        entrypoint = PythonSourceAnalyzer().analyze("lintel/cli/sample.py", source)
        self.assertEqual(entrypoint.reviews, ())

    def test_sem05_known_import_does_not_hide_unrelated_framework(self):
        source = (
            "import click\n"
            "from acme_cli import app\n"
            "@click.command()\n"
            "def known():\n"
            "    return 1\n"
            "@app.group()\n"
            "def run():\n"
            "    return 2\n"
        )
        analysis = PythonSourceAnalyzer().analyze("adapters/sample.py", source)
        self.assertIn(4, concern_lines(analysis, "argv_parse"))
        self.assertEqual(len(analysis.reviews), 1)
        self.assertEqual(analysis.reviews[0].line, 7)
        self.assertIn("unresolved CLI framework", analysis.reviews[0].reason)

    def test_sem05_plain_decorator_without_framework_is_silent(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py", "@command\ndef run():\n    return 1\n"
        )
        self.assertEqual(analysis.concerns, ())
        self.assertEqual(analysis.reviews, ())

    def test_sem05_known_click_import_has_no_unresolved_review(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py",
            "import click\n@click.command()\ndef run():\n    return 1\n",
        )
        self.assertEqual(analysis.reviews, ())
        self.assertIn(3, concern_lines(analysis, "argv_parse"))

    def test_sem03_unresolved_reflection_stays_a_review(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py",
            "import os\nname = \"environ\"\nvalue = getattr(os, name)\n",
        )
        self.assertEqual(concern_lines(analysis, "env"), [])
        self.assertTrue(any("dynamic" in item.reason for item in analysis.reviews))

    def test_sem06_configured_env_call_pattern_is_honored(self):
        source = "from config import Config\nsettings = Config.from_env()\n"
        self.assertEqual(
            concern_lines(PythonSourceAnalyzer().analyze("adapters/sample.py", source), "env"),
            [],
        )
        configure_env_call_patterns(("Config.from_env",))
        analysis = PythonSourceAnalyzer().analyze("adapters/sample.py", source)
        self.assertEqual(concern_lines(analysis, "env"), [2])

    def test_sem09_injected_live_boundary_is_detected_only_in_core(self):
        source = (
            "from argparse import ArgumentParser\n"
            "def run(args: ArgumentParser):\n"
            "    return args\n"
        )
        core = PythonSourceAnalyzer().analyze("lintel/core/sample.py", source)
        adapter = PythonSourceAnalyzer().analyze("lintel/adapters/sample.py", source)
        self.assertIn(2, concern_lines(core, "argv_parse"))
        self.assertEqual(concern_lines(adapter, "argv_parse"), [1])

    def test_sem09_plain_annotation_is_not_a_boundary(self):
        analysis = PythonSourceAnalyzer().analyze(
            "lintel/core/sample.py",
            "def run(env: dict):\n    return env\n",
        )
        self.assertEqual(analysis.concerns, ())
        self.assertEqual(analysis.reviews, ())

    def test_sem09_ambiguous_injection_with_live_use_is_reviewed(self):
        analysis = PythonSourceAnalyzer().analyze(
            "lintel/core/sample.py",
            "from unknown import Parser\ndef run(args: Parser):\n    return args.parse_args()\n",
        )
        self.assertEqual(analysis.concerns, ())
        self.assertTrue(
            any("unresolved injected boundary value args" in item.reason for item in analysis.reviews)
        )

    def test_sem09_name_only_boundary_parameter_is_silent(self):
        analysis = PythonSourceAnalyzer().analyze(
            "lintel/core/sample.py", "def run(args):\n    return args\n"
        )
        self.assertEqual(analysis.concerns, ())
        self.assertEqual(analysis.reviews, ())

    def test_sem13_review_exempt_paths_are_silent(self):
        source = (
            "from os import *\n"
            "from acme_cli import app\n"
            "@app.command()\n"
            "def run():\n"
            "    return 1\n"
        )
        for path in ("tests/sample.py", "fixtures/sample.py", "examples/sample.py"):
            analysis = PythonSourceAnalyzer().analyze(path, source)
            self.assertEqual(analysis.reviews, ())

    def test_sem12_logging_stream_mechanisms_are_terminal_io(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py",
            "import logging\nhandler = logging.StreamHandler()\n"
            "logging.basicConfig(stream=handler)\nlogging.info(\"ready\")\n",
        )
        self.assertEqual(concern_lines(analysis, "terminal_io"), [2, 3])
        self.assertEqual(concern_lines(analysis, "logging"), [1])


class PythonGraphContributorTests(unittest.TestCase):
    def test_external_from_import_resolves_to_its_module(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(
                os.path.join(directory, "sample.py"), "w", encoding="utf-8"
            ) as handle:
                handle.write("from datetime import datetime\nvalue = datetime.now()\n")
            data = source_graph_python.extract(directory)
            self.assertEqual(
                [
                    (item["from"], item["to"])
                    for item in data["dependencies"]
                ],
                [("sample", "datetime")],
            )


if __name__ == "__main__":
    unittest.main()
