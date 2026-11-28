#!/usr/bin/env python3
"""Build-time metadata embedded in release binaries.

Source runs leave these values unset. Release builds rewrite this module before
freezing the CLI so binaries do not depend on installed distribution metadata.
"""

VERSION = None
CHANNEL = None
COMMIT = None
CONTRACT_REVISION = None
CONFIG_SHA256 = None
RULE_CATALOG_SHA256 = None
CHECKER_ARTIFACT_SHA256 = None
BASELINE_SHA256 = None
