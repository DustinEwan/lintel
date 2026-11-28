#!/usr/bin/env python3
"""Installed-version metadata and GitHub Release lookup."""

import json
import os
import tomllib
from importlib.metadata import PackageNotFoundError, distribution
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RELEASES_URL = "https://api.github.com/repos/DustinEwan/lintel/releases/latest"
DISTRIBUTION_NAMES = ("lintel-architecture", "lintel")


class ReleaseError(RuntimeError):
    """Raised when a release advisory cannot be produced."""


def installed_version(root):
    """Read the installed version, falling back to a source checkout."""
    for name in DISTRIBUTION_NAMES:
        try:
            return distribution(name).version
        except PackageNotFoundError:
            continue

    pyproject = os.path.join(root, "pyproject.toml")
    if os.path.isfile(pyproject):
        with open(pyproject, "rb") as handle:
            data = tomllib.load(handle)
        return data.get("project", {}).get("version") or "unknown"
    return "unknown"


def install_info(root):
    """Describe how the running CLI was installed."""
    version = installed_version(root)
    package_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_path = os.path.realpath(root)
    has_source_manifest = os.path.isfile(os.path.join(root_path, "pyproject.toml"))
    if has_source_manifest and (
        package_path == root_path or package_path.startswith(root_path + os.sep)
    ):
        return {"version": version, "channel": "editable", "source": root_path}
    for name in DISTRIBUTION_NAMES:
        try:
            metadata = distribution(name)
        except PackageNotFoundError:
            continue
        raw = metadata.read_text("direct_url.json")
        if not raw:
            continue
        details = json.loads(raw)
        if details.get("dir_info", {}).get("editable"):
            return {
                "version": version,
                "channel": "editable",
                "source": details.get("url", ""),
            }
    return {"version": version, "channel": "package", "source": None}


def latest_release(timeout=3.0):
    """Fetch the latest published GitHub Release."""
    request = Request(
        RELEASES_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "lintel-version-check",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            raise ReleaseError("no published release") from error
        raise ReleaseError(f"GitHub returned HTTP {error.code}") from error
    except (URLError, TimeoutError) as error:
        raise ReleaseError(f"could not reach GitHub: {error}") from error

    tag = payload.get("tag_name")
    if not tag:
        raise ReleaseError("latest release has no tag")
    return {
        "version": tag.lstrip("v"),
        "url": payload.get("html_url"),
        "published_at": payload.get("published_at"),
    }
