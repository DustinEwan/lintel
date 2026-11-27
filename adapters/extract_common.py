import json
import os

SKIP_DIRS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "site-packages",
    "target",
    "vendor",
    "venv",
}


def iter_files(root, suffixes):
    suffixes = tuple(suffixes)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".") and not d.endswith(".egg-info")
        )
        for name in sorted(filenames):
            if name.endswith(suffixes):
                yield os.path.join(dirpath, name)


def rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def write_json(path, facts):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2)
        f.write("\n")
