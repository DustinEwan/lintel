import pathlib
import tempfile
import unittest
from unittest.mock import patch

from lintel.adapters import release
from lintel.core.version import is_newer, parse_version, version_status


class VersionStatusTests(unittest.TestCase):
    def test_parse_version_accepts_release_tags(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("0.1.0+build.7"), (0, 1, 0))
        self.assertIsNone(parse_version("not-a-version"))

    def test_version_status_is_advisory_only(self):
        status = version_status("0.1.0", "1.0.0")
        self.assertTrue(status["update_available"])
        self.assertTrue(status["advisory"])
        self.assertIsNone(status["error"])

    def test_unknown_versions_do_not_report_updates(self):
        status = version_status("0.1.0", "unknown")
        self.assertFalse(status["update_available"])
        self.assertFalse(is_newer("0.1.0", "not-a-version"))

    def test_equal_or_older_release_does_not_report_update(self):
        self.assertFalse(version_status("1.0.0", "1.0.0")["update_available"])
        self.assertFalse(version_status("1.0.0", "0.9.0")["update_available"])


    def test_installed_version_falls_back_to_source_pyproject(self):
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root, "pyproject.toml")
            path.write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
            with patch.object(release, "DISTRIBUTION_NAMES", ()):
                self.assertEqual(release.installed_version(root), "9.9.9")

    def test_install_info_requires_source_manifest_for_editable(self):
        with tempfile.TemporaryDirectory() as root:
            fake = pathlib.Path(root, "lintel", "adapters", "release.py")
            fake.parent.mkdir(parents=True)
            fake.write_text("", encoding="utf-8")
            with (
                patch.object(release, "__file__", str(fake)),
                patch.object(release, "installed_version", return_value="1.0.0"),
            ):
                self.assertEqual(release.install_info(root)["channel"], "package")

            pathlib.Path(root, "pyproject.toml").write_text(
                '[project]\nversion = "1.0.0"\n', encoding="utf-8"
            )
            with (
                patch.object(release, "__file__", str(fake)),
                patch.object(release, "installed_version", return_value="1.0.0"),
            ):
                self.assertEqual(release.install_info(root)["channel"], "editable")

if __name__ == "__main__":
    unittest.main()
