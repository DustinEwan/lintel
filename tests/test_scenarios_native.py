import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lintel.adapters.language import GoSourceAnalyzer, RustSourceAnalyzer
from lintel.adapters.language import native_analyzer


def of_concern(analysis, concern):
    return [item for item in analysis.concerns if item.concern == concern]


class RustMacroScenarioTests(unittest.TestCase):
    def test_known_terminal_macros_emit_deterministic_concerns(self):
        source = (
            "fn main() {\n"
            "    println!(\"out\");\n"
            "    print!(\"out\");\n"
            "    eprintln!(\"err\");\n"
            "    eprint!(\"err\");\n"
            "}\n"
        )
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "terminal_io")],
            [2, 3, 4, 5],
        )
        self.assertEqual(
            {item.category for item in of_concern(analysis, "terminal_io")},
            {"mechanism"},
        )
        self.assertEqual(analysis.reviews, ())

    def test_known_logging_macros_emit_deterministic_concerns(self):
        source = (
            "log::info!(\"started\");\n"
            "info!(\"started\");\n"
            "warn!(\"slow\");\n"
            "error!(\"failed\");\n"
            "let values = vec![1, 2];\n"
        )
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "logging")],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            {item.category for item in of_concern(analysis, "logging")},
            {"mechanism"},
        )
        self.assertEqual(analysis.reviews, ())

    def test_unknown_macro_fails_closed_with_a_review(self):
        source = "fn run() {\n    custom_log!(\"x\");\n}\n"
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertEqual(analysis.concerns, ())
        self.assertEqual(len(analysis.reviews), 1)
        review = analysis.reviews[0]
        self.assertEqual(review.line, 2)
        self.assertIn("unknown macro", review.reason)
        self.assertIn("custom_log", review.reason)

    def test_macro_rules_definition_is_not_double_reported(self):
        source = (
            "macro_rules! forward { () => { println!(\"x\"); }; }\n"
            "fn main() { println!(\"ok\"); }\n"
        )
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        # The Rust dependency extractor already emits unparsed_source for
        # macro_rules!; the native analyzer must not duplicate it or read an
        # unexpanded body as executable code.
        self.assertEqual(analysis.unparsed, ())
        self.assertEqual(analysis.reviews, ())
        self.assertEqual(
            [item.line for item in of_concern(analysis, "terminal_io")], [2]
        )

    def test_comments_and_strings_do_not_create_concerns_or_reviews(self):
        source = (
            '// println!("comment");\n'
            'let text = "info!(\\"inside\\")";\n'
            'fn main() { println!("code"); }\n'
        )
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "terminal_io")], [3]
        )
        self.assertEqual(analysis.reviews, ())

    def test_native_boundary_operations_are_exposed_as_concerns(self):
        source = (
            "let args = std::env::args();\n"
            "let mut out = std::io::stdout();\n"
            "let mut err = std::io::stderr();\n"
        )
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "argv_parse")], [1]
        )
        self.assertEqual(
            [item.line for item in of_concern(analysis, "terminal_io")], [2, 3]
        )


class RustCfgScenarioTests(unittest.TestCase):
    @patch.object(native_analyzer.os, "name", "posix")
    def test_unix_host_excludes_windows_only_code(self):
        source = (
            "#[cfg(windows)]\n"
            "fn main() {\n"
            '    println!("inactive");\n'
            "}\n"
            "#[cfg(unix)]\n"
            "fn active() {\n"
            '    println!("active");\n'
            "}\n"
        )
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertIsNone(analysis.entrypoint)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "terminal_io")], [7]
        )
        self.assertEqual(analysis.reviews, ())

    @patch.object(native_analyzer.os, "name", "nt")
    def test_windows_host_excludes_unix_only_code(self):
        source = (
            "#[cfg(windows)]\n"
            "fn main() {\n"
            '    println!("inactive");\n'
            "}\n"
            "#[cfg(unix)]\n"
            "fn active() {\n"
            '    println!("active");\n'
            "}\n"
        )
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertIsNotNone(analysis.entrypoint)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "terminal_io")], [3]
        )
        self.assertEqual(analysis.reviews, ())

    @patch.object(native_analyzer.os, "name", "posix")
    def test_same_line_cfg_attribute_and_scope_reset(self):
        source = (
            '#[cfg(windows)] fn main() { println!("inactive"); }\n'
            'fn run() { println!("active"); }\n'
        )
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertIsNone(analysis.entrypoint)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "terminal_io")], [2]
        )

    @patch.object(native_analyzer.os, "name", "posix")
    def test_unresolved_feature_cfg_produces_bounded_review(self):
        source = (
            '#[cfg(feature = "native")]\n'
            "fn run() {\n"
            "    std::env::args();\n"
            "}\n"
        )
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "argv_parse")], [3]
        )
        self.assertEqual(len(analysis.reviews), 1)
        review = analysis.reviews[0]
        self.assertEqual(review.line, 3)
        self.assertIn("cfg", review.reason.lower())
        self.assertLessEqual(len(review.reason), 160)

    @patch.object(native_analyzer.os, "name", "posix")
    def test_test_cfg_is_unresolved_and_reviewed(self):
        source = '#[cfg(test)]\nfn run() {\n    eprintln!("x");\n}\n'
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "terminal_io")], [3]
        )
        self.assertEqual(len(analysis.reviews), 1)
        self.assertIn("cfg", analysis.reviews[0].reason.lower())

    @patch.object(native_analyzer.os, "name", "posix")
    def test_unresolved_cfg_without_boundary_operation_is_silent(self):
        source = '#[cfg(feature = "native")]\nfn helper() {}\n'
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertEqual(analysis.concerns, ())
        self.assertEqual(analysis.reviews, ())

    @patch.object(native_analyzer.os, "name", "posix")
    def test_contradictory_cfg_is_inactive_without_review(self):
        source = '#[cfg(all(unix, windows))]\nfn run() { println!("x"); }\n'
        analysis = RustSourceAnalyzer().analyze("src/main.rs", source)
        self.assertEqual(analysis.concerns, ())
        self.assertEqual(analysis.reviews, ())


class GoBuildTagScenarioTests(unittest.TestCase):
    def test_build_tag_comment_does_not_change_concern_detection(self):
        source = (
            "//go:build windows\n"
            "\n"
            "package main\n"
            'func main() { fmt.Print("x") }\n'
        )
        analysis = GoSourceAnalyzer().analyze("cmd/tool/main.go", source)
        self.assertEqual(
            [item.line for item in of_concern(analysis, "terminal_io")], [4]
        )
        self.assertEqual(analysis.reviews, ())


if __name__ == "__main__":
    unittest.main()
