use serde::{Deserialize, Serialize};
use std::collections::{BTreeSet, HashMap};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{exit, Command};
use syn::spanned::Spanned;
use syn::visit::Visit;
use syn::{ItemExternCrate, ItemMod, ItemUse, Macro, UseTree};

#[derive(Serialize)]
struct Fact {
    version: u32,
    language: &'static str,
    modules: Vec<ModuleFact>,
    dependencies: Vec<DependencyFact>,
    unparsed: Vec<UnparsedFact>,
}

#[derive(Serialize)]
struct ModuleFact {
    name: String,
    path: String,
}

#[derive(Serialize)]
struct DependencyFact {
    from: String,
    to: String,
    kind: &'static str,
    source: String,
    line: usize,
}

#[derive(Serialize)]
struct UnparsedFact {
    source: String,
    line: usize,
    reason: String,
}

#[derive(Deserialize)]
struct CargoMetadata {
    packages: Vec<CargoPackage>,
}

#[derive(Deserialize)]
struct CargoPackage {
    name: String,
    manifest_path: String,
}

fn relative_path(root: &Path, file: &Path) -> String {
    let relative = file.strip_prefix(root).unwrap_or(file);
    relative.to_string_lossy().replace('\\', "/")
}

fn line_of<T: Spanned>(node: &T) -> usize {
    node.span().start().line
}

fn gather_files(root: &Path) -> Result<Vec<PathBuf>, String> {
    const SKIP_DIRS: [&str; 8] = [
        ".git", ".idea", ".next", "build", "coverage", "dist", "node_modules", "target",
    ];

    fn walk(directory: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
        let mut entries: Vec<PathBuf> = fs::read_dir(directory)
            .map_err(|error| format!("cannot read {}: {error}", directory.display()))?
            .filter_map(|entry| entry.ok().map(|entry| entry.path()))
            .collect();
        entries.sort();

        for path in entries {
            let name = path
                .file_name()
                .map(|name| name.to_string_lossy().to_string())
                .unwrap_or_default();
            if path.is_dir() {
                if !SKIP_DIRS.contains(&name.as_str()) && !name.starts_with('.') {
                    walk(&path, files)?;
                }
            } else if path.extension().and_then(|ext| ext.to_str()) == Some("rs") {
                files.push(path);
            }
        }
        Ok(())
    }

    let mut files = Vec::new();
    walk(root, &mut files)?;
    files.sort();
    Ok(files)
}

fn crate_name(root: &Path, unparsed: &mut Vec<UnparsedFact>) -> String {
    let fallback = root
        .file_name()
        .map(|name| name.to_string_lossy().replace('-', "_"))
        .unwrap_or_else(|| "crate".to_string());
    let manifest = root.join("Cargo.toml");
    if !manifest.exists() {
        return fallback;
    }

    let output = Command::new("cargo")
        .arg("metadata")
        .arg("--no-deps")
        .arg("--format-version")
        .arg("1")
        .arg("--manifest-path")
        .arg(&manifest)
        .output();

    let metadata = match output {
        Ok(output) if output.status.success() => {
            match serde_json::from_slice::<CargoMetadata>(&output.stdout) {
                Ok(metadata) => metadata,
                Err(error) => {
                    unparsed.push(UnparsedFact {
                        source: "Cargo.toml".to_string(),
                        line: 1,
                        reason: format!("cargo metadata parse error: {error}"),
                    });
                    return fallback;
                }
            }
        }
        Ok(output) => {
            let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
            unparsed.push(UnparsedFact {
                source: "Cargo.toml".to_string(),
                line: 1,
                reason: format!("cargo metadata failed: {stderr}"),
            });
            return fallback;
        }
        Err(error) => {
            unparsed.push(UnparsedFact {
                source: "Cargo.toml".to_string(),
                line: 1,
                reason: format!("cargo metadata unavailable: {error}"),
            });
            return fallback;
        }
    };

    let canonical_manifest = fs::canonicalize(&manifest).ok();
    let package = metadata
        .packages
        .iter()
        .find(|package| {
            fs::canonicalize(&package.manifest_path).ok() == canonical_manifest
        })
        .or_else(|| metadata.packages.first());

    package
        .map(|package| package.name.replace('-', "_"))
        .unwrap_or(fallback)
}

fn module_name(relative: &str, krate: &str) -> String {
    let mut value = relative.strip_prefix("src/").unwrap_or(relative).to_string();
    if value == "lib.rs" || value == "main.rs" {
        return krate.to_string();
    }
    if let Some(rest) = value.strip_suffix("/mod.rs") {
        value = rest.to_string();
    } else if let Some(rest) = value.strip_suffix(".rs") {
        value = rest.to_string();
    }

    let parts: Vec<&str> = value.split('/').filter(|part| !part.is_empty()).collect();
    if parts.is_empty() {
        krate.to_string()
    } else {
        format!("{}::{}", krate, parts.join("::"))
    }
}

fn append_path(prefix: &str, ident: &syn::Ident) -> String {
    if prefix.is_empty() {
        ident.to_string()
    } else {
        format!("{}::{}", prefix, ident)
    }
}

fn flatten_use(tree: &UseTree, prefix: &str, paths: &mut Vec<String>) {
    match tree {
        UseTree::Path(path) => {
            let next = append_path(prefix, &path.ident);
            flatten_use(&path.tree, &next, paths);
        }
        UseTree::Name(name) => paths.push(append_path(prefix, &name.ident)),
        UseTree::Rename(rename) => paths.push(append_path(prefix, &rename.ident)),
        UseTree::Glob(_) => {
            let value = prefix.trim_end_matches(':').to_string();
            if !value.is_empty() {
                paths.push(value);
            }
        }
        UseTree::Group(group) => {
            for tree in &group.items {
                flatten_use(tree, prefix, paths);
            }
        }
    }
}

fn join_components(prefix: &str, parts: &[&str]) -> String {
    if parts.is_empty() {
        prefix.to_string()
    } else {
        format!("{}::{}", prefix, parts.join("::"))
    }
}

fn resolve_path(
    path: &str,
    current: &str,
    krate: &str,
    modules: &BTreeSet<String>,
    local_top: &BTreeSet<String>,
) -> Option<String> {
    let path = path.trim_start_matches(':');
    let parts: Vec<&str> = path.split("::").filter(|part| !part.is_empty()).collect();
    if parts.is_empty() {
        return None;
    }

    let candidate = match parts[0] {
        "crate" => join_components(krate, &parts[1..]),
        "self" => join_components(current, &parts[1..]),
        "super" => {
            let mut base: Vec<&str> = current.split("::").collect();
            let mut index = 0;
            while index < parts.len() && parts[index] == "super" {
                if !base.is_empty() {
                    base.pop();
                }
                index += 1;
            }
            base.extend_from_slice(&parts[index..]);
            base.join("::")
        }
        first if local_top.contains(first) => join_components(krate, &parts),
        first => return Some(first.to_string()),
    };

    if candidate.is_empty() {
        return Some(krate.to_string());
    }

    let mut target = candidate;
    while !modules.contains(&target) && target.contains("::") {
        target = target.rsplitn(2, "::").nth(1).unwrap().to_string();
    }
    Some(target)
}

struct Visitor<'a> {
    krate: &'a str,
    current: &'a str,
    source: &'a str,
    modules: &'a BTreeSet<String>,
    local_top: &'a BTreeSet<String>,
    dependencies: &'a mut Vec<DependencyFact>,
    unparsed: &'a mut Vec<UnparsedFact>,
}

impl<'ast, 'a> Visit<'ast> for Visitor<'a> {
    fn visit_item_use(&mut self, node: &'ast ItemUse) {
        let mut paths = Vec::new();
        flatten_use(&node.tree, "", &mut paths);
        for path in paths {
            if let Some(to) = resolve_path(&path, self.current, self.krate, self.modules, self.local_top) {
                if to != self.current {
                    self.dependencies.push(DependencyFact {
                        from: self.current.to_string(),
                        to,
                        kind: "use",
                        source: self.source.to_string(),
                        line: line_of(node),
                    });
                }
            }
        }
    }

    fn visit_item_extern_crate(&mut self, node: &'ast ItemExternCrate) {
        self.dependencies.push(DependencyFact {
            from: self.current.to_string(),
            to: node.ident.to_string(),
            kind: "extern_crate",
            source: self.source.to_string(),
            line: line_of(node),
        });
    }

    fn visit_macro(&mut self, node: &'ast Macro) {
        let last = node
            .path
            .segments
            .last()
            .map(|segment| segment.ident.to_string())
            .unwrap_or_default();
        let reason = match last.as_str() {
            "include" => Some("include! can inject dependencies"),
            "macro_rules" => Some("macro_rules! can generate imports"),
            _ => None,
        };
        if let Some(reason) = reason {
            self.unparsed.push(UnparsedFact {
                source: self.source.to_string(),
                line: line_of(node),
                reason: reason.to_string(),
            });
        }
        syn::visit::visit_macro(self, node);
    }

    fn visit_item_mod(&mut self, node: &'ast ItemMod) {
        if node.attrs.iter().any(|attr| attr.path().is_ident("path")) {
            self.unparsed.push(UnparsedFact {
                source: self.source.to_string(),
                line: line_of(node),
                reason: "#[path] changes module paths".to_string(),
            });
        }
        syn::visit::visit_item_mod(self, node);
    }
}

fn extract(root: &Path) -> Result<Fact, String> {
    let mut unparsed = Vec::new();
    let krate = crate_name(root, &mut unparsed);
    let files = gather_files(root)?;
    let module_by_file: HashMap<PathBuf, String> = files
        .iter()
        .map(|file| (file.clone(), module_name(&relative_path(root, file), &krate)))
        .collect();
    let modules: BTreeSet<String> = module_by_file.values().cloned().collect();
    let prefix = format!("{}::", krate);
    let local_top: BTreeSet<String> = modules
        .iter()
        .filter_map(|module| {
            module
                .strip_prefix(&prefix)
                .and_then(|rest| rest.split("::").next())
                .map(str::to_string)
        })
        .collect();

    let mut dependencies = Vec::new();
    for file in &files {
        let source = relative_path(root, file);
        let text = fs::read_to_string(file)
            .map_err(|error| format!("cannot read {}: {error}", file.display()))?;
        let syntax = match syn::parse_file(&text) {
            Ok(syntax) => syntax,
            Err(error) => {
                unparsed.push(UnparsedFact {
                    source: source.clone(),
                    line: 1,
                    reason: format!("parse error: {error}"),
                });
                continue;
            }
        };
        let current = module_by_file.get(file).unwrap();
        let mut visitor = Visitor {
            krate: &krate,
            current,
            source: &source,
            modules: &modules,
            local_top: &local_top,
            dependencies: &mut dependencies,
            unparsed: &mut unparsed,
        };
        visitor.visit_file(&syntax);
    }

    let mut module_facts: Vec<ModuleFact> = module_by_file
        .iter()
        .map(|(file, name)| ModuleFact {
            name: name.clone(),
            path: relative_path(root, file),
        })
        .collect();
    module_facts.sort_by(|left, right| left.name.cmp(&right.name));

    Ok(Fact {
        version: 1,
        language: "rust",
        modules: module_facts,
        dependencies,
        unparsed,
    })
}

fn main() {
    let mut root = None;
    let mut out = None;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--root" => root = args.next(),
            "--out" => out = args.next(),
            _ => {
                eprintln!("unknown argument: {arg}");
                exit(1);
            }
        }
    }
    let out = match out {
        Some(out) => out,
        None => {
            eprintln!("--out is required");
            exit(1);
        }
    };
    let root = PathBuf::from(root.unwrap_or_else(|| ".".to_string()));

    match extract(&root) {
        Ok(facts) => {
            let json = match serde_json::to_string_pretty(&facts) {
                Ok(json) => json,
                Err(error) => {
                    eprintln!("cannot serialize facts: {error}");
                    exit(1);
                }
            };
            let path = Path::new(&out);
            if let Some(parent) = path.parent() {
                if !parent.as_os_str().is_empty() {
                    if let Err(error) = fs::create_dir_all(parent) {
                        eprintln!("cannot create {}: {error}", parent.display());
                        exit(1);
                    }
                }
            }
            if let Err(error) = fs::write(path, format!("{json}\n")) {
                eprintln!("cannot write {}: {error}", path.display());
                exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            exit(1);
        }
    }
}
