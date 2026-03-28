---
description: Bring existing code under spec-driven management
argument-hint: <file-or-directory-path> [--spec-only] [--skip-adversarial] [--full-adversarial]
---

**Parse arguments:** `$ARGUMENTS` contains the target path (file or directory) and optional flags. Extract:
- The target path: first token that does not start with `--`. May be a file (produces a file spec) or a directory (produces a unit spec).
- The `--spec-only` flag, if present (stops after distill + elicit, skips generate).
- The `--skip-adversarial` flag, if present (bypasses adversarial validation even for testless files -- user accepts risk of unvalidated takeover).
- The `--full-adversarial` flag, if present (forces adversarial validation even when tests exist -- runs adversarial pipeline in addition to existing test validation).

If both `--skip-adversarial` and `--full-adversarial` are present, stop:
> "Cannot use both --skip-adversarial and --full-adversarial. Choose one."

**1. Verify prerequisites**

Check that `.unslop/` exists. If not, stop:
> "unslop is not initialized. Run `/unslop:init` first."

Check that the target path exists (file or directory). If not, stop:
> "Target not found: `<target-path>`."

Check that the target is NOT already managed:
- For files: check for `@unslop-managed` header in the first 5 lines.
- For directories: check whether `<dirname>.unit.spec.md` already exists.

If already managed:
> "Target is already managed by unslop. Use `/unslop:change` to modify it, or `/unslop:sync` to regenerate."

**1b. Testless routing decision**

Check whether tests exist for the target:
- For files: search for test files following common language conventions -- `tests/test_<name>.*`, `<name>_test.*`, `<name>.test.*`, `*.spec.ts`, `*.spec.js`, `spec/*_spec.rb`, or test files that import the target module. **HARD RULE:** Do not match `*.spec.md` files -- those are unslop specs, not test files.
- For directories: search for a parallel `tests/`, `test/`, `__tests__/`, or `spec/` directory, or test files within the directory matching the patterns above.

Route based on test presence and flags:
- **Tests exist, no flags:** Normal path -- existing tests serve as quality gate during generation.
- **No tests exist, no flags:** Adversarial path auto-activates -- Archaeologist extracts behaviour.yaml, Mason generates tests under Chinese Wall, Saboteur validates via mutation testing (kill rate >= 80% required).
- **`--skip-adversarial`:** Bypass adversarial validation even for testless files. The takeover proceeds without a quality gate. Use when you trust the distilled spec and want to skip the compute cost.
- **`--full-adversarial`:** Force adversarial validation even when tests exist. Runs the adversarial pipeline (behaviour extraction, Mason test generation, mutation testing) in addition to existing test validation. Use for belt-and-suspenders validation on critical code.

**2. Phase 1: Distill**

Run `/unslop:distill <target-path>`.

Distill reads the existing code and produces a candidate spec as `<spec-path>.proposed`. For files this produces a file spec; for directories this produces a unit spec. The user reviews and approves the distilled spec. If rejected, stop.

After approval, the spec exists as `<spec-path>` with `distilled-from:` provenance, `uncertain:` entries, and `intent-approved: false`.

**3. Phase 2: Elicit (distillation review)**

Run `/unslop:elicit <target-path>`.

Elicit detects `distilled-from:` in the spec frontmatter and enters distillation review mode. The user resolves uncertainties, ratifies non-goals, and validates the intent statement.

After elicit completes:
- `uncertain:` entries are cleared.
- `distilled-from:` persists as provenance.
- Non-goals are ratified (no more "(inferred)" suffixes).
- The spec is ready for generation.

**4. Phase 3: Generate (unless `--spec-only`)**

If `--spec-only` was passed, stop and report:
> "Spec written and reviewed: `<spec-path>`. Run `/unslop:generate <file-path>` when ready to generate code."

Otherwise, run the generate pipeline for `<target-path>`. The takeover command orchestrates the pipeline directly (it does not delegate to `/unslop:generate` for the testless path, since the adversarial pipeline has distinct steps not present in the standard generate flow).

The adversarial routing decision from Step 1b controls which pipeline steps execute:
- **Normal path (tests exist, no `--full-adversarial`):** Archaeologist Stage 0 (concrete spec + behaviour.yaml), Builder Stage 2 (implementation in worktree validated against existing tests), Saboteur Stage 3 (async verification).
- **Adversarial path (no tests, or `--full-adversarial`):** Archaeologist Stage 0 (concrete spec + behaviour.yaml), Mason Stage 1 (test derivation from behaviour.yaml under Chinese Wall), Builder Stage 2 (implementation validated against Mason's tests), Saboteur Stage 3 (async mutation testing, kill rate >= 80% required).
- **Skip path (`--skip-adversarial`):** Same as normal path but Mason Stage 1 is skipped even for testless files. The takeover proceeds without a test quality gate.

**5. Post-takeover summary**

```
Takeover complete:
  Spec: <spec-path>
  Tests: <test-path> (generated by Mason)
  Code: <file-path> (regenerated by Builder)
  Verification: pending (Saboteur running in background)

The spec is the source of truth. Edit the spec, not the code.
```
