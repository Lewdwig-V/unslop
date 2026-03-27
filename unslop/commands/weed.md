---
description: Detect intent drift between specs and code. Surfaces meaningful discrepancies and offers per-finding remediation.
argument-hint: "[file-path] [--all]"
---

**Parse arguments:** `$ARGUMENTS` may contain a file path and optional flags.

- If a file path is provided: target that single file
- If `--all` is provided: target all managed files regardless of classification
- If no arguments: target files classified as `modified` (code edited directly, spec unchanged)

**0. Verify prerequisites**

Check that `.unslop/` exists. If not:

> "unslop is not initialized. Run `/unslop:init` first."

**1. Target Selection**

If a file path argument is provided, validate it is a managed file (has `@unslop-managed` header and a corresponding `*.spec.md`). If not:

> "This file is not under spec management. Use `/unslop:takeover` first."

If no argument:
- Scan for all managed files using the same mechanism as `/unslop:status`.
- Default: select files classified as `modified` (code edited directly, spec unchanged).
- With `--all`: select all managed files regardless of classification.

If no targets found:

> "No files to weed."

**2. Analysis**

For each target file:

1. Read the spec file (abstract spec `*.spec.md`).
2. Read the concrete spec (`*.impl.md`) if it exists.
3. Read the managed file (the generated/edited code).
4. Compare spec intent against code behavior and identify **concerns**.

A concern is a meaningful discrepancy between what the spec says and what the code does. Not a style issue. Not a naming preference. A place where behavior has drifted from intent.

Each concern has:

| Field | Description |
|-------|-------------|
| **title** | Short description, e.g., "Unbounded retry loop" |
| **direction** | `spec-behind` (code is right, spec incomplete) or `code-drifted` (spec is right, code diverged) |
| **spec-reference** | Which section(s) of the spec are relevant |
| **code-reference** | File path + line range |
| **rationale** | Why this is a meaningful discrepancy |

**Direction heuristic:** If the file is `modified` (code edited directly), lean toward `spec-behind` -- the human edit was probably intentional. If the file is `fresh` (generated), lean toward `code-drifted` -- the generator probably missed something. Override with your own judgment if the heuristic doesn't fit.

**3. Report**

Display all findings grouped by file, all at once, before any remediation:

```
Weed report: 2 files, 4 concerns

  src/auth/handler.py  (modified)
    1. [spec-behind] Unbounded retry loop
       Spec ## Retry Policy says "retry with backoff" but doesn't cap retries.
       Code caps at 5 (handler.py:42-58). Spec should document the cap.

    2. [code-drifted] Silent exception swallowing
       Spec ## Error Handling says "propagate all errors to caller."
       Code catches ConnectionError and returns None (handler.py:61-65).

  src/auth/tokens.py  (modified)
    3. [spec-behind] Token refresh adds jitter
       Spec ## Refresh says "refresh token before expiry."
       Code adds 0-5s jitter to avoid thundering herd (tokens.py:88-94).
       Spec should document the jitter strategy.

    4. [code-drifted] Missing token revocation
       Spec ## Lifecycle says "tokens can be revoked."
       Code has no revocation path (tokens.py).
```

If no concerns: "No drift detected across N files."

**4. Remediation**

Walk through each finding one at a time.

**If `spec-behind`:**
> Concern N: "<title>" -- spec should document <what>.
> (u) Update spec to match code  |  (s) Skip  |  (q) Quit remediation

If the user chooses "update spec": edit the spec file directly. Add or modify the relevant section to reflect what the code actually does. The file will show as `stale` in `/unslop:status` (spec changed, code unchanged) -- but since the spec now matches the code, the next sync will be a no-op or trivially confirmed.

**If `code-drifted`:**
> Concern N: "<title>" -- code should <what> per spec.
> (r) Regenerate to match spec  |  (s) Skip  |  (q) Quit remediation

If the user chooses "regenerate": mark the file for sync. Do NOT regenerate inline. Display a reminder at the end: "N files queued for sync -- run `/unslop:sync` to regenerate."

**Quit** stops remediation but keeps the report visible. Unanswered findings are simply skipped.

**5. Post-Remediation Summary**

```
Remediation complete:
  2 specs updated (src/auth/handler.py.spec.md, src/auth/tokens.py.spec.md)
  1 file queued for sync (src/auth/tokens.py)
  1 skipped

Run /unslop:sync to regenerate queued files.
```
