"""Built-in architecture presets for project scaffolding."""

PRESETS = {
    "clean": {
        "layers": ("ports", "core", "platform", "entrypoints", "infrastructure", "adapters"),
        "directories": ("ports", "core", "adapters", "infrastructure", "entrypoints"),
    },
    "hexagonal": {
        "layers": ("ports", "core", "platform", "adapters", "infrastructure", "entrypoints"),
        "directories": ("domain", "application", "ports", "adapters", "entrypoints"),
    },
    "onion": {
        "layers": ("domain", "application", "infrastructure", "entrypoints"),
        "directories": ("domain", "application", "infrastructure", "entrypoints"),
    },
}


def preset_names():
    return tuple(sorted(PRESETS))


def get_preset(name):
    if name not in PRESETS:
        raise ValueError(f"unknown preset: {name}")
    return PRESETS[name]
