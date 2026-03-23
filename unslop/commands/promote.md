---
description: Promote a concrete spec (.impl.md) from ephemeral to permanent
argument-hint: <spec-path>
---

**Parse arguments:** `$ARGUMENTS` is the path to the abstract spec file (e.g., `src/retry.py.spec.md`).

This is a shorthand for `/unslop:harden <spec-path> --promote`. It runs the same Concrete Spec Promotion flow (Step 6 of harden).

**1. Verify prerequisites**

Check that `.unslop/` exists in the current working directory. If it does not exist, stop and tell the user:

> "unslop is not initialized. Run `/unslop:init` first."

Check that the abstract spec file at the given path exists. If it does not exist, stop and tell the user:

> "Spec not found at `<path>`."

**2. Derive paths**

Derive the concrete spec path from the abstract spec path:
- `src/retry.py.spec.md` → `src/retry.py.impl.md`
- `src/auth/auth.unit.spec.md` → `src/auth/auth.unit.impl.md`

Derive managed file paths:
- For per-file specs: strip `.spec.md` (e.g., `src/retry.py.spec.md` → `src/retry.py`)
- For unit specs: read `## Files` section

Check that at least one managed file exists. If none exist, stop:

> "No generated files found for this spec. Run `/unslop:generate` first."

**3. Generate the Concrete Spec**

Read the abstract spec, all managed files, and `.unslop/principles.md` if it exists.

Use the **unslop/concrete-spec** skill to draft a Concrete Spec that captures the **current implementation's strategy** — what the generated code actually does today.

Required sections:
- `## Strategy` — pseudocode of the core algorithm, extracted from the generated code
- `## Pattern` — design patterns identified in the current implementation
- `## Type Sketch` — structural types from the current implementation
- `## Lowering Notes` — language-specific considerations

Set frontmatter:
```yaml
---
source-spec: <abstract-spec-path>
target-language: <detected-language>
ephemeral: false
complexity: <assessed-complexity>
---
```

Assess complexity based on the implementation:
- `low` — single algorithm, linear control flow, few types
- `medium` — multiple interacting algorithms, branching control flow, moderate type structure
- `high` — complex state machines, concurrent logic, intricate type hierarchies, non-obvious invariants

**4. Present for review**

> "Concrete spec generated at `<impl-path>`:
>
> **Strategy:** [one-line summary of core algorithm]
> **Pattern:** [named patterns]
> **Complexity:** [low/medium/high]
>
> This captures the current implementation strategy as a permanent artifact. Review?"

**5. On approval**

Write the concrete spec to disk. Tell the user:

> "Promoted `<impl-path>`. The Builder will use this as strategic guidance on future generations. The abstract spec remains the source of truth for constraints."

**6. On rejection**

Acknowledge and exit without writing any file.

---

This command is advisory — it never generates application code and never runs tests. It only creates or updates the `.impl.md` sidecar.
