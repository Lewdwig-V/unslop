---
description: Create or edit a spec for a source file
argument-hint: <file-path>
---

The argument `$ARGUMENTS` is the path to the source file (e.g., `src/retry.py`).

Use the `unslop/spec-language` skill for guidance on spec writing voice throughout this command.

**Check initialization:** Check that `.unslop/` exists. If not, warn the user that unslop is not initialized and suggest running `/unslop:init` first. You may still proceed with creating the spec file (spec creation works without init), but note that `/unslop:generate` will require initialization.

**Derive the spec path:** append `.spec.md` to the filename (e.g., `src/retry.py` → `src/retry.py.spec.md`).

---

**If the spec file already exists:**

Read it and present its contents to the user for editing. Stop here — no further steps are needed.

---

**If the source file exists but no spec exists yet:**

1. Read the source file.
2. Draft a spec that captures intent, not implementation — describe what the file does, what constraints it satisfies, and what behavior it exhibits. Do not describe data structures, algorithms, or internal control flow. When creating a spec for a file that imports from other managed files, suggest `depends-on` frontmatter. Analyze the source file's imports — if any imported module has a corresponding `*.spec.md` file in the project, include it in the `depends-on` list. Present the suggested dependencies to the user for confirmation before writing the spec.
3. Write the draft to the spec path.
4. Present the draft to the user for review and editing.

---

**If neither the source file nor the spec exists:**

1. Create a skeleton spec using the template from the `unslop/spec-language` skill.
2. Write it to the spec path.
3. Present it to the user for editing.

---

**After the user is satisfied with the spec:**

Inform them to run `/unslop:generate` to produce the managed file from the spec.

Do NOT archive, regenerate, or run tests. Those are handled by `/unslop:takeover` and `/unslop:generate`.
