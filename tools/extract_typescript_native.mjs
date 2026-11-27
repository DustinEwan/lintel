#!/usr/bin/env node
// Extract TypeScript dependencies using the TypeScript compiler API.

import fs from "node:fs";
import path from "node:path";
import tsModule from "typescript";

const ts = tsModule.default ?? tsModule;

const SKIP_DIRS = new Set([
  ".git",
  ".idea",
  ".next",
  "build",
  "coverage",
  "dist",
  "node_modules",
  "target",
  "vendor",
]);
const SUFFIXES = [".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"];
const DECLARATION_RE = /\.d\.[cm]?ts$/;

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--root") {
      args.root = argv[++i];
    } else if (argv[i] === "--out") {
      args.out = argv[++i];
    } else {
      throw new Error(`unknown argument: ${argv[i]}`);
    }
  }
  if (!args.out) {
    throw new Error("--out is required");
  }
  return { root: path.resolve(args.root ?? "."), out: args.out };
}

function relativePath(root, file) {
  return path.relative(root, file).split(path.sep).join("/");
}

function isUnderRoot(root, file) {
  const relative = path.relative(root, file);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function isDeclaration(file) {
  return DECLARATION_RE.test(file);
}

function isSourceFile(file) {
  return SUFFIXES.some((suffix) => file.endsWith(suffix)) && !isDeclaration(file);
}

function moduleName(relative) {
  return relative
    .replace(/\.d\.[cm]?ts$/, "")
    .replace(/\.(ts|tsx|js|jsx|mts|cts)$/, "");
}

function gatherFiles(root) {
  const files = [];
  const walk = (directory) => {
    const entries = fs.readdirSync(directory, { withFileTypes: true });
    entries.sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of entries) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        if (!SKIP_DIRS.has(entry.name) && !entry.name.startsWith(".")) {
          walk(full);
        }
      } else if (entry.isFile() && isSourceFile(entry.name)) {
        files.push(full);
      }
    }
  };
  walk(root);
  return files;
}

function diagnosticText(diagnostic) {
  return ts.flattenDiagnosticMessageText(diagnostic.messageText, " ");
}

function loadProject(root, unparsed) {
  const defaultOptions = {
    allowJs: true,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
  };
  const configPath = ts.findConfigFile(root, ts.sys.fileExists, "tsconfig.json");
  if (!configPath) {
    return { options: defaultOptions, files: gatherFiles(root) };
  }

  const read = ts.readConfigFile(configPath, ts.sys.readFile);
  if (read.error) {
    unparsed.push({
      source: relativePath(root, configPath),
      line: 1,
      reason: `tsconfig error: ${diagnosticText(read.error)}`,
    });
    return { options: defaultOptions, files: gatherFiles(root) };
  }

  const parsed = ts.parseJsonConfigFileContent(
    read.config,
    ts.sys,
    path.dirname(configPath),
    defaultOptions,
    configPath,
  );
  for (const error of parsed.errors) {
    unparsed.push({
      source: relativePath(root, configPath),
      line: 1,
      reason: `tsconfig error: ${diagnosticText(error)}`,
    });
  }
  const files = parsed.fileNames.filter(
    (file) => isUnderRoot(root, file) && isSourceFile(file),
  );
  return { options: parsed.options, files: files.length ? files : gatherFiles(root) };
}

function lineAt(sourceFile, node) {
  return sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
}

function isImportAttributesArgument(node) {
  if (!ts.isObjectLiteralExpression(node)) {
    return false;
  }
  return node.properties.some((property) => {
    if (
      !ts.isPropertyAssignment(property) &&
      !ts.isShorthandPropertyAssignment(property)
    ) {
      return false;
    }
    const name = property.name;
    return (ts.isIdentifier(name) || ts.isStringLiteralLike(name)) && name.text === "with";
  });
}

function extract(root) {
  const unparsed = [];
  const project = loadProject(root, unparsed);
  const dependencies = [];
  const seen = new Set();

  const record = (sourceFile, relativeSource, node, specifier, kind) => {
    const line = lineAt(sourceFile, node);
    let target = null;

    if (specifier.startsWith(".")) {
      const resolved = ts.resolveModuleName(
        specifier,
        path.resolve(root, relativeSource),
        project.options,
        ts.sys,
      ).resolvedModule;
      if (!resolved || !isUnderRoot(root, resolved.resolvedFileName)) {
        unparsed.push({
          source: relativeSource,
          line,
          reason: `unresolved relative specifier: ${specifier}`,
        });
        return;
      }
      target = moduleName(relativePath(root, resolved.resolvedFileName));
    } else if (specifier.startsWith("@")) {
      target = specifier.split("/").slice(0, 2).join("/");
    } else {
      target = specifier.split("/")[0];
    }

    const key = `${relativeSource}:${target}:${line}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    dependencies.push({
      from: moduleName(relativeSource),
      to: target,
      kind,
      source: relativeSource,
      line,
    });
  };

  for (const file of project.files.sort()) {
    const relativeSource = relativePath(root, file);
    const text = ts.sys.readFile(file);
    if (text === undefined) {
      unparsed.push({ source: relativeSource, line: 1, reason: "unreadable source file" });
      continue;
    }
    const sourceFile = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
    for (const diagnostic of sourceFile.parseDiagnostics ?? []) {
      const position = diagnostic.start ?? 0;
      const line = sourceFile.getLineAndCharacterOfPosition(position).line + 1;
      unparsed.push({
        source: relativeSource,
        line,
        reason: `parse error: ${diagnosticText(diagnostic)}`,
      });
    }

    const visit = (node) => {
      if (
        (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
        node.moduleSpecifier
      ) {
        if (ts.isStringLiteralLike(node.moduleSpecifier)) {
          record(sourceFile, relativeSource, node.moduleSpecifier, node.moduleSpecifier.text, "import");
        } else {
          unparsed.push({
            source: relativeSource,
            line: lineAt(sourceFile, node),
            reason: "non-literal import or export specifier",
          });
        }
      } else if (
        ts.isImportEqualsDeclaration(node) &&
        ts.isExternalModuleReference(node.moduleReference) &&
        node.moduleReference.expression
      ) {
        const expression = node.moduleReference.expression;
        if (ts.isStringLiteralLike(expression)) {
          record(sourceFile, relativeSource, expression, expression.text, "import_equals");
        } else {
          unparsed.push({
            source: relativeSource,
            line: lineAt(sourceFile, node),
            reason: "non-literal import equals specifier",
          });
        }
      } else if (ts.isImportTypeNode(node)) {
        const argument = node.argument;
        if (ts.isLiteralTypeNode(argument) && ts.isStringLiteralLike(argument.literal)) {
          record(sourceFile, relativeSource, argument.literal, argument.literal.text, "import_type");
        } else {
          unparsed.push({
            source: relativeSource,
            line: lineAt(sourceFile, node),
            reason: "non-literal import type specifier",
          });
        }
      } else if (ts.isCallExpression(node) && node.arguments.length >= 1) {
        const isImport = node.expression.kind === ts.SyntaxKind.ImportKeyword;
        const isDynamic =
          isImport ||
          (ts.isIdentifier(node.expression) && node.expression.text === "require");
        if (isDynamic) {
          const argument = node.arguments[0];
          if (ts.isStringLiteralLike(argument)) {
            const kind = isImport ? "import" : "require";
            record(sourceFile, relativeSource, argument, argument.text, kind);
            const supportedExtraArgs =
              node.arguments.length === 2 &&
              isImport &&
              isImportAttributesArgument(node.arguments[1]);
            if (node.arguments.length > 1 && !supportedExtraArgs) {
              unparsed.push({
                source: relativeSource,
                line: lineAt(sourceFile, node),
                reason: "unsupported extra dynamic dependency arguments",
              });
            }
          } else {
            unparsed.push({
              source: relativeSource,
              line: lineAt(sourceFile, node),
              reason: "non-literal dynamic dependency",
            });
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sourceFile);
  }

  return {
    version: 1,
    language: "typescript",
    modules: project.files.map((file) => ({
      name: moduleName(relativePath(root, file)),
      path: relativePath(root, file),
    })),
    dependencies,
    unparsed,
  };
}

try {
  const args = parseArgs(process.argv.slice(2));
  const facts = extract(args.root);
  fs.writeFileSync(args.out, `${JSON.stringify(facts, null, 2)}\n`, "utf8");
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
