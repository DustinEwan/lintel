package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"go/parser"
	"go/token"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type fact struct {
	Version      int            `json:"version"`
	Language     string         `json:"language"`
	Modules      []moduleFact   `json:"modules"`
	Dependencies []dependency   `json:"dependencies"`
	Unparsed     []unparsedFact `json:"unparsed"`
}

type moduleFact struct {
	Name string `json:"name"`
	Path string `json:"path"`
}

type dependency struct {
	From   string `json:"from"`
	To     string `json:"to"`
	Kind   string `json:"kind"`
	Source string `json:"source"`
	Line   int    `json:"line"`
}

type unparsedFact struct {
	Source string `json:"source"`
	Line   int    `json:"line"`
	Reason string `json:"reason"`
}

type listError struct {
	Err string `json:"Err"`
}

type listPackage struct {
	Dir             string     `json:"Dir"`
	ImportPath      string     `json:"ImportPath"`
	GoFiles         []string   `json:"GoFiles"`
	CgoFiles        []string   `json:"CgoFiles"`
	TestGoFiles     []string   `json:"TestGoFiles"`
	XTestGoFiles    []string   `json:"XTestGoFiles"`
	IgnoredGoFiles  []string   `json:"IgnoredGoFiles"`
	Error           *listError `json:"Error"`
}

func relativePath(root, full string) string {
	relative, err := filepath.Rel(root, full)
	if err != nil {
		return filepath.ToSlash(full)
	}
	return filepath.ToSlash(relative)
}

func listPackages(root string) ([]listPackage, error) {
	cmd := exec.Command("go", "list", "-json", "-e", "./...")
	cmd.Dir = root
	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("go list failed: %v: %s", err, strings.TrimSpace(string(output)))
	}

	var packages []listPackage
	decoder := json.NewDecoder(bytes.NewReader(output))
	for decoder.More() {
		var pkg listPackage
		if err := decoder.Decode(&pkg); err != nil {
			return nil, fmt.Errorf("cannot decode go list output: %w", err)
		}
		packages = append(packages, pkg)
	}
	return packages, nil
}

func extract(root string) (fact, error) {
	result := fact{
		Version:      1,
		Language:     "go",
		Modules:      []moduleFact{},
		Dependencies: []dependency{},
		Unparsed:     []unparsedFact{},
	}

	packages, err := listPackages(root)
	if err != nil {
		return result, err
	}

	seen := map[string]bool{}
	for _, pkg := range packages {
		if pkg.Error != nil {
			result.Unparsed = append(result.Unparsed, unparsedFact{
				Source: relativePath(root, pkg.Dir),
				Line:   1,
				Reason: fmt.Sprintf("go list error: %s", pkg.Error.Err),
			})
		}

		result.Modules = append(result.Modules, moduleFact{
			Name: pkg.ImportPath,
			Path: relativePath(root, pkg.Dir),
		})

		for _, ignored := range pkg.IgnoredGoFiles {
			result.Unparsed = append(result.Unparsed, unparsedFact{
				Source: relativePath(root, filepath.Join(pkg.Dir, ignored)),
				Line:   1,
				Reason: "build-constrained file requires explicit policy",
			})
		}

		files := append([]string{}, pkg.GoFiles...)
		files = append(files, pkg.CgoFiles...)
		files = append(files, pkg.TestGoFiles...)
		files = append(files, pkg.XTestGoFiles...)
		sort.Strings(files)

		for _, name := range files {
			full := filepath.Join(pkg.Dir, name)
			source := relativePath(root, full)
			fset := token.NewFileSet()
			file, err := parser.ParseFile(fset, full, nil, parser.ParseComments)
			if err != nil {
				result.Unparsed = append(result.Unparsed, unparsedFact{
					Source: source,
					Line:   1,
					Reason: fmt.Sprintf("parse error: %v", err),
				})
				continue
			}

			for _, spec := range file.Imports {
				path, err := strconv.Unquote(spec.Path.Value)
				if err != nil {
					result.Unparsed = append(result.Unparsed, unparsedFact{
						Source: source,
						Line:   fset.Position(spec.Path.ValuePos).Line,
						Reason: "unsupported import path literal",
					})
					continue
				}
				if path == pkg.ImportPath {
					continue
				}
				line := fset.Position(spec.Path.ValuePos).Line
				key := fmt.Sprintf("%s:%d:%s", source, line, path)
				if seen[key] {
					continue
				}
				seen[key] = true
				result.Dependencies = append(result.Dependencies, dependency{
					From:   pkg.ImportPath,
					To:     path,
					Kind:   "import",
					Source: source,
					Line:   line,
				})
			}
		}
	}

	sort.Slice(result.Modules, func(i, j int) bool {
		return result.Modules[i].Name < result.Modules[j].Name
	})
	sort.Slice(result.Dependencies, func(i, j int) bool {
		if result.Dependencies[i].Source != result.Dependencies[j].Source {
			return result.Dependencies[i].Source < result.Dependencies[j].Source
		}
		return result.Dependencies[i].Line < result.Dependencies[j].Line
	})
	sort.Slice(result.Unparsed, func(i, j int) bool {
		if result.Unparsed[i].Source != result.Unparsed[j].Source {
			return result.Unparsed[i].Source < result.Unparsed[j].Source
		}
		return result.Unparsed[i].Line < result.Unparsed[j].Line
	})

	return result, nil
}

func main() {
	root := flag.String("root", ".", "project root to scan")
	out := flag.String("out", "", "output JSON facts path")
	flag.Parse()
	if *out == "" {
		fmt.Fprintln(os.Stderr, "--out is required")
		os.Exit(1)
	}

	absoluteRoot, err := filepath.Abs(*root)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	result, err := extract(absoluteRoot)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	data = append(data, '\n')

	if parent := filepath.Dir(*out); parent != "." {
		if err := os.MkdirAll(parent, 0o755); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
	if err := os.WriteFile(*out, data, 0o644); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

