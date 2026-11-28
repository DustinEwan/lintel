import hashlib
import os
import pathlib
import platform
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def asset_name():
    system = platform.system()
    machine = platform.machine()
    operating = {"Linux": "linux", "Darwin": "macos"}.get(system)
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(machine)
    if not operating or not arch:
        raise unittest.SkipTest(f"unsupported installer platform: {system}/{machine}")
    return f"lintel-{operating}-{arch}"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.asset = asset_name()
        self.content = b"#!/bin/sh\necho '{\"version\":\"0.1.0\"}'\n"
        self.binary = self.root / self.asset
        self.binary.write_bytes(self.content)
        self.bin_dir = self.root / "bin"

    def run_installer(self, digest):
        (self.root / "SHA256SUMS").write_text(
            f"{digest}  {self.asset}\n", encoding="utf-8"
        )
        env = {
            **os.environ,
            "LINTEL_VERSION": "v0.1.0",
            "LINTEL_BASE_URL": self.root.as_uri(),
            "LINTEL_BIN_DIR": str(self.bin_dir),
        }
        return subprocess.run(
            ["sh", str(ROOT / "lintel-install.sh")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_installs_checksum_verified_binary(self):
        digest = hashlib.sha256(self.content).hexdigest()
        result = self.run_installer(digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.bin_dir / "lintel"
        self.assertEqual(installed.read_bytes(), self.content)
        self.assertTrue(os.access(installed, os.X_OK))

    def test_rejects_checksum_mismatch(self):
        result = self.run_installer("0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.bin_dir / "lintel").exists())


if __name__ == "__main__":
    unittest.main()
