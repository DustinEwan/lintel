import unittest

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

    def test_sem03_literal_reflection_is_deterministic(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py",
            "import os\nimport importlib\nx = getattr(os, \"environ\")\n"
            "y = importlib.import_module(\"sys\").argv\n",
        )
        self.assertEqual(concern_lines(analysis, "env"), [3])
        self.assertEqual(concern_lines(analysis, "argv"), [4])
        self.assertEqual(analysis.reviews, ())

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

    def test_sem12_logging_stream_mechanisms_are_terminal_io(self):
        analysis = PythonSourceAnalyzer().analyze(
            "adapters/sample.py",
            "import logging\nhandler = logging.StreamHandler()\n"
            "logging.basicConfig(stream=handler)\nlogging.info(\"ready\")\n",
        )
        self.assertEqual(concern_lines(analysis, "terminal_io"), [2, 3])
        self.assertEqual(concern_lines(analysis, "logging"), [1])


if __name__ == "__main__":
    unittest.main()
