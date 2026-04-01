---
description: Render a Mermaid dependency graph of specs, concrete specs, and managed files
argument-hint: "[--scope <spec-path>...] [--no-code] [--stale-only]"
---

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

**2. Parse flags**

**Check for `--scope` flag:** If `$ARGUMENTS` contains `--scope`, collect the following spec paths. These limit the graph to just the specified specs and their transitive dependents/dependencies. Without `--scope`, the full project graph is rendered.

**Check for `--no-code` flag:** If `$ARGUMENTS` contains `--no-code`, omit the managed code file layer from the graph. Useful for focusing on the spec architecture without the output noise.

**Check for `--stale-only` flag:** If `$ARGUMENTS` contains `--stale-only`, render only the "ghost staleness" subgraph — nodes and edges on paths leading to stale, ghost-stale, modified, or conflict managed files. Fresh files and their upstream-only specs are excluded. Useful for prioritizing which files to sync first.

**3. Generate the graph**

Call the MCP tools:

1. Call `prunejuice_build_order` with `{ cwd: "." }` to get topological spec ordering.
2. Call `prunejuice_ripple_check` with `{ specPaths: [...], cwd: "." }` (use all discovered spec paths, or the `--scope` subset if provided) for dependency analysis.

The tools return data with:
- Topological ordering of specs (from `prunejuice_build_order`)
- Dependency relationships and ripple paths (from `prunejuice_ripple_check`)
- Per-node metadata for programmatic use

**4. Display the graph**

Display the Mermaid source in a fenced code block so the user can copy it to any Mermaid renderer:

````
```mermaid
<mermaid source from orchestrator>
```
````

Below the graph, display a summary:

```
Graph: N abstract specs, M concrete specs, K managed files

Legend:
  [spec]    Abstract spec (.spec.md)         blue
  [/impl/]  Concrete spec (.impl.md)         purple
  {base}    Base concrete spec (no source)   teal
  ([code])  Managed code file                colored by state:
            fresh=green, stale=brown, ghost-stale=violet,
            modified=gold, conflict=red, new=blue
```

**5. Edge types**

The graph uses different edge styles to distinguish relationship types:

- `-->` solid: abstract `depends-on` (spec A depends on spec B)
- `-.->` dashed: `lowers to` (abstract spec → concrete spec)
- `==>` thick: `extends` (concrete spec inheritance)
- `-->` with label: `concrete dep` (concrete-dependencies link)
- `-->` with label: `generates` (spec → managed code file)

This command is read-only. Do not modify any files, generate any code, or run any tests.
