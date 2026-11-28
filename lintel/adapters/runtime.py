#!/usr/bin/env python3
"""Concrete adapters for architecture workflows."""

from dataclasses import asdict

import glob
import json
import os
import shutil
import subprocess
import tempfile

from lintel.adapters import (
    agent_files,
    config as config_adapter,
    contract_facts,
    decision_model,
    contract_lock,
    incremental_cache,
)
from lintel.core import presets, review, rules
from lintel.core.callgraph import relevant_unresolved_reviews
from lintel.core.checker import check, check_semantic_review
from lintel.core.model import (
    FactSet,
    Policy,
    SelfConfig,
    facts_from_dict,
    facts_to_dict,
    PathOverrides,
    policy_from_dict,
    replace,
    violation_to_dict,
)

from lintel.core.ratchet import compare_baseline, is_baselineable, violation_fingerprint

DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CORE_ROOT = "core"
DEFAULT_ADAPTERS_ROOT = "adapters"
DEFAULT_ENTRYPOINTS_ROOT = "cli"
DEFAULT_CONFIG = "lintel.toml"

TOOL_ROOT = DEFAULT_ROOT


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def merge_facts(paths, contract_data=None, excluded_scopes=()):
    contract_data = contract_data or {}
    excluded = {
        item.get("path")
        for item in contract_data.get("scopes", [])
        if item.get("scope") in excluded_scopes
    }
    modules = {}
    dependencies = {}
    unparsed = {}
    reviews = {}
    decisions = {}
    symbols = {}
    import_bindings = {}
    call_sites = {}

    def keep(source):
        return source not in excluded

    for path, include_prefix in paths:
        facts = load_json(path)

        def included(source):
            return keep(source) and (
                include_prefix is None or source.startswith(include_prefix)
            )

        for module in facts.get("modules", []):
            if not included(module["path"]):
                continue
            modules[(module["name"], module["path"])] = module

        for dependency in facts.get("dependencies", []):
            if not included(dependency["source"]):
                continue
            key = (
                dependency["from"],
                dependency["to"],
                dependency["kind"],
                dependency["source"],
                dependency["line"],
            )
            dependencies[key] = dependency

        for item in facts.get("unparsed", []):
            if not included(item["source"]):
                continue
            key = (item["source"], item["line"], item["reason"])
            unparsed[key] = item

    for item in contract_data.get("unparsed", []):
        if not keep(item["source"]):
            continue
        key = (item["source"], item["line"], item["reason"])
        unparsed[key] = item

    for item in contract_data.get("reviews", []):
        if not keep(item["source"]):
            continue
        key = (item.get("module", ""), item["source"], item["line"], item["reason"])
        reviews[key] = item
    for item in contract_data.get("decisions", []):
        fingerprint = item.get("fingerprint")
        if fingerprint:
            decisions[fingerprint] = item
    for item in contract_data.get("symbols", []):
        if not keep(item["source"]):
            continue
        symbols[(item["key"], item["source"])] = item
    for item in contract_data.get("import_bindings", []):
        if not keep(item["source"]):
            continue
        key = (item["module"], item["local_name"], item["source"], item["line"])
        import_bindings[key] = item
    for item in contract_data.get("call_sites", []):
        if not keep(item["source"]):
            continue
        key = (item["caller"], item["callee"], item["source"], item["line"])
        call_sites[key] = item
    return {
        "version": 1,
        "language": "self",
        "modules": sorted(modules.values(), key=lambda item: item["name"]),
        "dependencies": sorted(
            dependencies.values(),
            key=lambda item: (item["source"], item["line"], item["to"]),
        ),
        "unparsed": sorted(
            unparsed.values(), key=lambda item: (item["source"], item["line"])
        ),
        "reviews": sorted(
            reviews.values(), key=lambda item: (item["source"], item["line"], item["reason"])
        ),
        "decisions": sorted(
            decisions.values(), key=lambda item: item.get("fingerprint", "")
        ),
        "entrypoints": sorted(
            contract_data.get("entrypoints", []), key=lambda item: item["path"]
        ),
        "concerns": sorted(
            contract_data.get("concerns", []),
            key=lambda item: (item["source"], item["line"], item["concern"]),
        ),
        "scopes": sorted(
            contract_data.get("scopes", []),
            key=lambda item: (item["path"], item["scope"], item["priority"]),
        ),
        "wrapper_operations": sorted(
            contract_data.get("wrapper_operations", []),
            key=lambda item: (item["source"], item["line"], item["operation"]),
        ),
        "symbols": sorted(
            symbols.values(),
            key=lambda item: (item["module"], item["name"], item["line"]),
        ),
        "import_bindings": sorted(
            import_bindings.values(),
            key=lambda item: (item["module"], item["local_name"], item["line"]),
        ),
        "call_sites": sorted(
            call_sites.values(),
            key=lambda item: (item["source"], item["line"], item["callee"]),
        ),
    }


class LintelRuntime:
    """Implements workflow ports with files, processes, and TOML config."""

    def __init__(self, root=DEFAULT_ROOT):
        self.root = os.path.abspath(root)
        self.tool_root = DEFAULT_ROOT
        self.use_cache = True
        self.entrypoints_root = os.path.join(self.root, DEFAULT_ENTRYPOINTS_ROOT)

    def resolve(self, path):
        return path if os.path.isabs(path) else os.path.join(self.root, path)

    def run(self, command, cwd=None):
        env = os.environ.copy()
        if command and command[0] in {"lake", "elan"}:
            elan_bin = os.path.expanduser("~/.elan/bin")
            if os.path.isdir(elan_bin) and not shutil.which(command[0], path=env.get("PATH", "")):
                env["PATH"] = elan_bin + os.pathsep + env.get("PATH", "")
        result = subprocess.run(
            command, cwd=cwd or self.root, capture_output=True, text=True, env=env
        )
        if result.returncode != 0:
            raise SystemExit(result.stderr.strip() or result.stdout.strip())
        return result

    def load_self_config(self, path, required):
        full = self.resolve(path or DEFAULT_CONFIG)
        if not os.path.isfile(full):
            if required:
                raise SystemExit(f"config not found: {full}")
            return SelfConfig(
                core_root=self.resolve(DEFAULT_CORE_ROOT),
                adapters_root=self.resolve(DEFAULT_ADAPTERS_ROOT),
                policy=Policy("external", (), {}, {}),
            )
        config = config_adapter.load_config(full)
        path_config = config.get("paths", {})
        if not isinstance(path_config, dict):
            raise SystemExit("config: paths must be a table")
        policy = policy_from_dict(config_adapter.policy_from_config(config))
        entrypoints_root = path_config.get("entrypoints_root", DEFAULT_ENTRYPOINTS_ROOT)
        return SelfConfig(
            core_root=self.resolve(
                path_config.get("core_root", DEFAULT_CORE_ROOT)
            ),
            adapters_root=self.resolve(
                path_config.get("adapters_root", DEFAULT_ADAPTERS_ROOT)
            ),
            policy=policy,
            entrypoints_root=entrypoints_root,
            excluded_scopes=policy.excluded_scopes,
            scope_conventions=policy.scope_conventions,
        )

    def collect_self_facts(self, config, overrides):
        key = None
        if self.use_cache:
            key = incremental_cache.fact_key(
                self.root, config, overrides, self.tool_root
            )
            cached = incremental_cache.load_facts(self.root, key)
            if cached is not None:
                return facts_from_dict(cached)
        core_root = self.resolve(overrides.core_root or config.core_root)
        adapters_root = self.resolve(
            overrides.adapters_root or config.adapters_root
        )
        tool_cli = os.path.join(self.tool_root, DEFAULT_ENTRYPOINTS_ROOT)
        rust_tool_dir = os.path.join(
            self.tool_root, DEFAULT_ADAPTERS_ROOT, "rust-extractor"
        )
        go_tool_dir = os.path.join(
            self.tool_root, DEFAULT_ADAPTERS_ROOT, "go-extractor"
        )
        entrypoints_root = config.entrypoints_root
        rust_project = bool(
            glob.glob(os.path.join(self.root, "**", "Cargo.toml"), recursive=True)
        )
        go_project = bool(
            glob.glob(os.path.join(self.root, "**", "*.go"), recursive=True)
        )
        rust_scan_root = os.path.join(adapters_root, "rust-extractor")
        if not os.path.isdir(rust_scan_root):
            rust_scan_root = adapters_root
        go_scan_root = os.path.join(adapters_root, "go-extractor")
        if not os.path.isdir(go_scan_root):
            go_scan_root = adapters_root

        with tempfile.TemporaryDirectory() as directory:
            paths = []

            def output_path(name, include_prefix=None):
                path = os.path.join(directory, name + ".json")
                paths.append((path, include_prefix))
                return path

            self.run(
                [
                    "python3",
                    os.path.join(tool_cli, "extract_python.py"),
                    "--root",
                    self.root,
                    "--out",
                    output_path("python"),
                ]
            )
            self.run(
                [
                    "python3",
                    os.path.join(tool_cli, "extract_typescript.py"),
                    "--root",
                    adapters_root,
                    "--out",
                    output_path("typescript"),
                ]
            )
            if rust_project and os.path.isfile(os.path.join(rust_tool_dir, "Cargo.toml")):
                self.run(
                    [
                        "cargo",
                        "build",
                        "--quiet",
                        "--manifest-path",
                        os.path.join(rust_tool_dir, "Cargo.toml"),
                    ]
                )
                self.run(
                    [
                        os.path.join(
                            rust_tool_dir, "target", "debug", "rust-extractor"
                        ),
                        "--root",
                        rust_scan_root,
                        "--out",
                        output_path("rust"),
                    ]
                )

            if go_project and os.path.isfile(os.path.join(go_tool_dir, "main.go")):
                go_binary = os.path.join(directory, "go-extractor")
                self.run(
                    [
                        "go",
                        "build",
                        "-o",
                        go_binary,
                        os.path.join(go_tool_dir, "main.go"),
                    ]
                )
                self.run(
                    [
                        go_binary,
                        "--root",
                        go_scan_root,
                        "--out",
                        output_path("go"),
                    ]
                )

            contract_data = contract_facts.discover(
                self.root, config.policy, entrypoints_root
            )
            data = merge_facts(paths, contract_data, config.excluded_scopes)
            data["decisions"] = self._baseline_decision_data()
            if self.use_cache:
                incremental_cache.save_facts(self.root, key, data)
            return facts_from_dict(data)

    def write_facts(self, path, facts):
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(facts_to_dict(facts), handle, indent=2)
            handle.write("\n")

    def load_facts(self, path):
        return facts_from_dict(load_json(self.resolve(path)))

    def load_policy(self, config_path, policy_path):
        if config_path:
            config = config_adapter.load_config(self.resolve(config_path))
            return policy_from_dict(config_adapter.policy_from_config(config))
        return policy_from_dict(load_json(self.resolve(policy_path)))

    def check(self, facts, policy, decisions=()):
        return tuple(check(facts, policy, decisions))

    def validate_config(self, path):
        full = self.resolve(path or DEFAULT_CONFIG)
        if not os.path.isfile(full):
            return ()
        config = config_adapter.load_config(full)
        return config_adapter.validate_config(config, os.path.dirname(full))

    def verify_lock(self, path, locked):
        full = self.resolve(path or DEFAULT_CONFIG)
        return contract_lock.verify_lock(
            self.root, full, locked, checker_root=self.tool_root
        )

    def apply_baseline(self, violations, live_fingerprints=()):
        path = contract_lock.baseline_path(self.root)
        if not os.path.isfile(path):
            return compare_baseline(violations, (), live_fingerprints)
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return compare_baseline(
            violations, data.get("violations", []), live_fingerprints
        )

    def update_lock(self, path):
        contract_lock.write_lock(
            self.root, self.resolve(path or DEFAULT_CONFIG), checker_root=self.tool_root
        )

    def accept_baseline(self, path, violations):
        config_path = self.resolve(path or DEFAULT_CONFIG)
        baseline = contract_lock.baseline_path(self.root)
        rejected = sorted(
            {item.rule for item in violations if not is_baselineable(item.rule)}
        )
        if rejected:
            raise SystemExit(
                "cannot baseline non-baselineable rules: " + ", ".join(rejected)
            )
        accepted = []
        seen = set()
        for item in violations:
            data = violation_to_dict(item)
            key = violation_fingerprint(item)
            if key in seen:
                continue
            seen.add(key)
            accepted.append(
                {
                    "fingerprint": key,
                    "rule": item.rule,
                    "location": data.get("location", ""),
                }
            )
        with open(baseline, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "violations": accepted}, handle, indent=2)
            handle.write("\n")
        self.update_lock(config_path)

    def accepted_review_sources(self, path, facts=None, policy=None):
        resolved = self.resolve(path)
        if not os.path.isfile(resolved):
            return ()
        with open(resolved, encoding="utf-8") as handle:
            data = json.load(handle)
        entries = [
            item
            for item in data.get("violations", ())
            if item.get("rule") == "semantic_review"
        ]
        sources = [
            source
            for item in entries
            for source in (item.get("source"),)
            if source
        ]
        fingerprints = {
            item["fingerprint"] for item in entries if item.get("fingerprint")
        }
        if facts is not None and policy is not None and fingerprints:
            sources.extend(
                item.fields["source"]
                for item in self.semantic_review_findings(facts, policy)
                if violation_fingerprint(item) in fingerprints
                and item.fields.get("source")
            )
        return tuple(dict.fromkeys(sources))

    def _baseline_data(self):
        path = contract_lock.baseline_path(self.root)
        if not os.path.isfile(path):
            return {"version": 1}
        return load_json(path)

    def _baseline_decision_data(self):
        return list(self._baseline_data().get("decisions", ()))

    def semantic_review_findings(self, facts, policy):
        reviews = facts.reviews + relevant_unresolved_reviews(facts)
        return check_semantic_review(replace(facts, reviews=reviews), policy, ())

    def live_decision_fingerprints(self, findings, decisions):
        accepting = {
            item.fingerprint for item in decisions if review.is_accepting(item.decision)
        }
        return frozenset(
            key
            for item in findings
            for key in (violation_fingerprint(item),)
            if key in accepting
        )

    def decision_model_decisions(self, findings, policy):
        return decision_model.evaluate(findings, policy, self.root)

    def record_model_decisions(self, decisions, findings=()):
        fields = {
            violation_fingerprint(item): item.fields for item in findings
        }
        records = []
        for item in decisions:
            record = asdict(item)
            source = fields.get(item.fingerprint, {})
            record.setdefault("source", source.get("source", ""))
            record.setdefault("location", source.get("location", ""))
            record.setdefault("rule", source.get("rule", "semantic_review"))
            records.append(record)
        return self._write_decision_records(records)

    def _write_decision_records(self, records):
        config_path = self.resolve(DEFAULT_CONFIG)
        baseline = contract_lock.baseline_path(self.root)
        data = load_json(baseline) if os.path.isfile(baseline) else {"version": 1}
        entries = list(data.get("violations", ()))
        merged = {
            item["fingerprint"]: item
            for item in data.get("decisions", ())
            if item.get("fingerprint")
        }
        for item in records:
            item.setdefault("confidence", 1.0)
            item.setdefault("model", "human")
            item.setdefault("schema_version", "1")
            if item.get("fingerprint"):
                merged[item["fingerprint"]] = item
        for item in merged.values():
            item.setdefault("confidence", 1.0)
            item.setdefault("model", "human")
            item.setdefault("schema_version", "1")
        decisions = sorted(merged.values(), key=lambda entry: entry["fingerprint"])
        decision_fingerprints = set(merged)
        entries = [
            entry
            for entry in entries
            if entry.get("fingerprint") not in decision_fingerprints
        ]
        for record in decisions:
            if review.is_accepting(record.get("decision", "")):
                entries.append(
                    {
                        "fingerprint": record["fingerprint"],
                        "rule": record.get("rule", "semantic_review"),
                        "source": record.get("source", ""),
                        "location": record.get("location", ""),
                    }
                )
        entries.sort(key=lambda entry: entry.get("fingerprint", ""))
        with open(baseline, "w", encoding="utf-8") as handle:
            json.dump(
                {"version": 1, "violations": entries, "decisions": decisions},
                handle,
                indent=2,
            )
            handle.write("\n")
        self.update_lock(config_path)
        return tuple(records)


    def record_review(self, fingerprint, decision, reason):
        config = self.load_self_config(DEFAULT_CONFIG, True)
        facts = self.collect_self_facts(config, PathOverrides())
        matches = [
            item
            for item in check_semantic_review(facts, config.policy, ())
            if violation_fingerprint(item) == fingerprint
        ]
        if not matches:
            raise SystemExit(f"unknown semantic-review fingerprint: {fingerprint}")
        item = matches[0]
        record = {
            "fingerprint": fingerprint,
            "decision": decision,
            "reason": reason,
            "rule": item.rule,
            "source": item.fields.get("source", ""),
            "location": item.fields.get("location", ""),
        }
        records = self._write_decision_records((record,))
        return records[0]

    def lean_check_key(self, output):
        return incremental_cache.lean_key(self.root, output, self.tool_root)

    def lean_check_is_cached(self, key):
        return self.use_cache and incremental_cache.lean_ok(self.root, key)

    def mark_lean_check(self, key):
        incremental_cache.mark_lean_ok(self.root, key)
    def list_rules(self):
        return tuple(rules.catalog_data())

    def explain_rule(self, rule_id):
        spec = rules.rule_spec(rule_id)
        return asdict(spec) if spec else None

    def scaffold(self, preset, output):
        data = presets.get_preset(preset)
        root = os.path.abspath(output)
        os.makedirs(root, exist_ok=True)
        for directory in data["directories"]:
            os.makedirs(os.path.join(root, directory), exist_ok=True)

        lines = [
            "version = 1",
            'default_layer = "external"',
            'default_scope = "external"',
            "",
            "[paths]",
            'core_root = "core"',
            'adapters_root = "adapters"',
            'entrypoints_root = "entrypoints"',
            "",
            "[analysis]",
            'source_suffixes = [".py", ".go", ".rs", ".mjs", ".js", ".ts", ".tsx"]',
            "",
            "[semantic_decision]",
            'model = "liquid/d1.2"',
            'endpoint = "https://openrouter.ai/api/alpha/decisions"',
            'api_key_env = "OPENROUTER_API_KEY"',
            'answer_key = "decision"',
            "min_confidence = 0.85",
            "timeout = 20",
            "max_findings = 64",
            "",
            "[scopes.external]",
            'patterns = ["*"]',
            "priority = 0",
            "",
            "[scopes.test]",
            'patterns = ["tests/**", "**/*_test.py"]',
            "priority = 10",
            "",
            "[scopes.fixture]",
            'patterns = ["tests/fixtures/**"]',
            "priority = 20",
            "",
            "[scope_rules]",
            'excluded_scopes = ["fixture", "test", "example", "generated", "vendor"]',
            "",
            "[scope_rules.conventions]",
            '"tests/fixtures/" = "fixture"',
            '"tests/" = "test"',
        ]
        for index, layer in enumerate(data["layers"]):
            lines.extend(
                [
                    "",
                    f"[layers.{layer}]",
                    f"priority = {(index + 1) * 10}",
                    f"core = {str(layer in {'ports', 'core', 'domain', 'application'}).lower()}",
                    f'patterns = ["{layer}.*"]',
                ]
            )
        lines.extend(
            [
                "",
                "[layers.external]",
                "priority = 1000",
                'patterns = ["*"]',
                'allowed = ["external"]',
                "",
            ]
        )
        config_path = os.path.join(root, DEFAULT_CONFIG)
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

        baseline_path = contract_lock.baseline_path(root)
        with open(baseline_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "violations": []}, handle, indent=2)
        for name, content in agent_files.FILES.items():
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)
        contract_lock.write_lock(
            root, config_path, checker_root=self.tool_root
        )

        ignore_path = os.path.join(root, ".gitignore")
        existing = ""
        if os.path.isfile(ignore_path):
            with open(ignore_path, "r", encoding="utf-8") as handle:
                existing = handle.read()
        entries = {line.strip() for line in existing.splitlines()}
        if incremental_cache.CACHE_FILE not in entries:
            with open(ignore_path, "a", encoding="utf-8") as handle:
                if existing and not existing.endswith("\n"):
                    handle.write("\n")
                handle.write(incremental_cache.CACHE_FILE + "\n")
