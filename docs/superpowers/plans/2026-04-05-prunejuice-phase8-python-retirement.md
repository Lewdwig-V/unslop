# Phase 8: Python Retirement -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the Python orchestrator entirely. Port the one load-bearing validator (`validate_pseudocode`) to prunejuice TypeScript. Migrate CI from Python matrix to TypeScript. Restructure skills as domain reference (no orchestration prose). Update all documentation.

**Architecture:** This is mostly deletion. The only new code is a `validators.ts` module in prunejuice with the pseudocode linter. The skills get a full restructure: orchestration prose deleted, domain knowledge preserved. CI switches from `pytest` matrix across Python 3.8-3.14 to `vitest` + `tsc --noEmit` + plugin structure validation.

**Tech Stack:** TypeScript, vitest, GitHub Actions, markdown

**Scope decisions (ratified before planning):**

- `validate_pseudocode.py` -> port to prunejuice TS (internal helper, ~150 LOC)
- `validate_mocks.py`, `validate_behaviour.py`, `validate_spec.py` -> delete entirely (redundant or Python-specific)
- Skills: full restructure (option Y) — domain reference only, no orchestration prose
- CI: vitest + tsc + plugin structure validation + existing MCP tests serve as smoke test

---

## File Structure

### Files to create

| File | Responsibility |
|------|---------------|
| `prunejuice/src/validators.ts` | Pseudocode linter ported from `validate_pseudocode.py` |
| `prunejuice/test/validators.test.ts` | Contract tests for pseudocode linter |
| `.github/workflows/typescript-tests.yml` | New CI running vitest, tsc, plugin validation |

### Files to delete

| Path | Lines | Why |
|------|-------|-----|
| `unslop/scripts/**/*.py` (26 files) | 6,391 | Python orchestrator -- replaced by prunejuice |
| `tests/**/*.py` (8 files) | 9,179 | Python tests for deleted code |
| `pyproject.toml`, `uv.lock` | -- | Python project metadata |
| `.github/workflows/python-package.yml` | -- | Python CI |
| `unslop/__pycache__/`, `unslop/scripts/__pycache__/` | -- | Python bytecode caches |

### Files to modify

| File | Change |
|------|--------|
| `unslop/skills/generation/SKILL.md` | Full rewrite: strip orchestration, keep domain reference |
| `unslop/skills/concrete-spec/SKILL.md` | Full rewrite: strip orchestration, keep domain reference |
| `unslop/skills/spec-language/SKILL.md` | Strip orchestration prose and Python refs |
| `unslop/skills/takeover/SKILL.md` | Strip orchestration prose and Python refs |
| `unslop/skills/adversarial/SKILL.md` | Minor cleanup (small file) |
| `unslop/skills/triage/SKILL.md` | Minor cleanup (small file) |
| `unslop/commands/sync.md` | Replace orchestrator refs with prunejuice MCP tool calls |
| `unslop/commands/cover.md` | Remove `validate_mocks.py` reference, rely on Saboteur |
| `unslop/commands/adversarial.md` | Remove `validate_behaviour.py`/`validate_mocks.py` refs |
| `unslop/commands/coherence.md` | Update orchestrator reference |
| `unslop/commands/init.md` | Remove CI recipe referencing `orchestrator.py check-freshness` |
| `README.md` | Remove Python mentions, update architecture description |
| `CLAUDE.md` | Update build/test commands |
| `AGENTS.md` | Full rewrite of architecture section (Python layout gone) |
| `.gitignore` | Remove `__pycache__/`, `.pytest_cache/`, `*.egg-info/` |
| `unslop/.claude-plugin/plugin.json` | Version bump 0.53.0 -> 0.54.0 |

---

## Task 1: Port validate_pseudocode to prunejuice

**Files:**
- Create: `prunejuice/src/validators.ts`
- Create: `prunejuice/test/validators.test.ts`

The Python validator is ~380 lines of regex-based lint over fenced `pseudocode` blocks in concrete spec markdown files. It's language-agnostic (operates on pseudocode convention, not any target language). Straightforward port.

- [ ] **Step 1: Write failing tests**

Create `prunejuice/test/validators.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { validatePseudocode } from "../src/validators.js";

describe("validatePseudocode", () => {
  it("returns warn when no pseudocode blocks present", () => {
    const content = "## Strategy\nUse connection pooling.";
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("warn");
    expect(result.warnings?.[0]?.check).toBe("no_pseudocode");
  });

  it("passes valid pseudocode with ← assignment", () => {
    const content = [
      "## Pseudocode",
      "",
      "```pseudocode",
      "FUNCTION retry(operation, maxAttempts)",
      "  SET attempts ← 0",
      "  WHILE attempts < maxAttempts",
      "    IF operation() = SUCCESS THEN",
      "      RETURN SUCCESS",
      "    SET attempts ← attempts + 1",
      "  RETURN FAILURE",
      "END FUNCTION",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("pass");
  });

  it("flags bare assignment without ← or :=", () => {
    const content = [
      "```pseudocode",
      "SET x = 5",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.[0]?.check).toBe("bare_assignment");
  });

  it("allows = as comparison in IF/WHILE/ASSERT", () => {
    const content = [
      "```pseudocode",
      "IF x = 5 THEN",
      "  RETURN true",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("pass");
  });

  it("flags language-specific keywords like def, fn, let", () => {
    const content = [
      "```pseudocode",
      "def foo()",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.[0]?.check).toBe("language_keyword");
  });

  it("flags arrow operators => and ->", () => {
    const content = [
      "```pseudocode",
      "SET handler ← (x) => x + 1",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.some((v) => v.check === "language_keyword")).toBe(true);
  });

  it("flags library calls like time.sleep()", () => {
    const content = [
      "```pseudocode",
      "CALL time.sleep(5)",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.[0]?.check).toBe("library_call");
  });

  it("flags multi-statement lines with semicolons", () => {
    const content = [
      "```pseudocode",
      "SET x ← 1; SET y ← 2",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.[0]?.check).toBe("multi_statement");
  });

  it("flags FUNCTION without matching END FUNCTION", () => {
    const content = [
      "```pseudocode",
      "FUNCTION foo()",
      "  SET x ← 1",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.some((v) => v.check === "unclosed_function")).toBe(true);
  });

  it("flags unclosed pseudocode fence", () => {
    const content = [
      "```pseudocode",
      "FUNCTION foo()",
      "END FUNCTION",
      // No closing ```
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("fail");
    expect(result.violations?.some((v) => v.check === "unclosed_fence")).toBe(true);
  });

  it("ignores // comments inside pseudocode", () => {
    const content = [
      "```pseudocode",
      "// this is a comment",
      "SET x ← 1",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    expect(result.status).toBe("pass");
  });

  it("advises on single-char variable names (not loop counters)", () => {
    const content = [
      "```pseudocode",
      "SET z ← 5",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    // Single-char vars outside {i,j,k,n,m,x,y} are advisories, not violations
    expect(result.status).toBe("warn");
    expect(result.advisories?.[0]?.check).toBe("abbreviated_name");
  });

  it("extracts multiple pseudocode blocks", () => {
    const content = [
      "```pseudocode",
      "SET x ← 1",
      "```",
      "",
      "Some prose.",
      "",
      "```pseudocode",
      "SET y = 2",
      "```",
    ].join("\n");
    const result = validatePseudocode(content, "test.impl.md");
    // Second block has bare assignment
    expect(result.status).toBe("fail");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd prunejuice && npx vitest run test/validators.test.ts`
Expected: FAIL -- module not found

- [ ] **Step 3: Implement validators.ts**

Create `prunejuice/src/validators.ts`:

```typescript
/**
 * Structural lint for pseudocode blocks in concrete specs.
 * Ported from unslop/scripts/validate_pseudocode.py (Python) to TypeScript.
 *
 * Pseudocode is a language-agnostic notation used in concrete spec markdown.
 * This module enforces: no bare `=` assignment (use `←` or `:=`), no
 * language-specific keywords (def, fn, let, ...), no library calls
 * (time.sleep()), one statement per line, matched FUNCTION/END FUNCTION,
 * and closed code fences.
 */

// -- Banned tokens ------------------------------------------------------------

const BANNED_KEYWORD_TOKENS = [
  "def",
  "func",
  "fn",
  "let",
  "var",
  "const",
  "lambda",
  "pub",
  "use",
  "mod",
  "impl",
  "struct",
  "enum",
  "package",
  "async",
  "await",
  "class",
  "public",
  "private",
  "match",
  "case",
];
const BANNED_OPERATOR_TOKENS = ["=>", "->"];

const BANNED_SYNTAX = new RegExp(
  `(?:\\b(?:${BANNED_KEYWORD_TOKENS.slice().sort().join("|")})\\b|${BANNED_OPERATOR_TOKENS
    .slice()
    .sort()
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|")})`,
);

// Dot-notation method calls: word.word( — time.sleep(, random.uniform(
const LIBRARY_CALL = /\b[a-z_]\w*\.[a-z_]\w*\s*\(/;

// Bare `=` that is not part of `==`, `<=`, `>=`, `!=`, `:=`
const BARE_ASSIGNMENT = /(?<![<>!=:])=(?!=)/;

// Contexts where bare `=` is a comparison, not assignment
const COMPARISON_CONTEXT = /^\s*(?:IF|ELSE\s+IF|WHILE|UNTIL|ASSERT)\b/i;
const CASE_WHEN_PREFIX = /^\s*(?:CASE|WHEN)\b/i;
const ASSIGNMENT_REQUIRED = /^\s*(?:FOR|SET|INCREMENT|DECREMENT)\b/i;

const MULTI_STATEMENT = /;/;
const SINGLE_CHAR_VAR = /\bSET\s+([a-z])\s*[←:=]/;

const FUNCTION_START = /^\s*FUNCTION\b/i;
const FUNCTION_END = /^\s*END\s+FUNCTION\b/i;

const ALLOWED_SINGLE_CHAR = new Set(["i", "j", "k", "n", "m", "x", "y"]);

// -- Types -------------------------------------------------------------------

export interface PseudocodeViolation {
  line: number;
  check: string;
  text: string;
  message: string;
}

export interface PseudocodeAdvisory {
  line: number;
  check: string;
  text: string;
  message: string;
}

export interface PseudocodeWarning {
  check: string;
  message: string;
}

export interface ValidatePseudocodeResult {
  status: "pass" | "fail" | "warn";
  implPath: string;
  violations?: PseudocodeViolation[];
  advisories?: PseudocodeAdvisory[];
  warnings?: PseudocodeWarning[];
}

interface PseudocodeBlock {
  startLine: number;
  lines: Array<[number, string]>; // [1-indexed line number, content]
  unclosed?: boolean;
}

// -- Block extraction --------------------------------------------------------

function extractPseudocodeBlocks(content: string): PseudocodeBlock[] {
  const blocks: PseudocodeBlock[] = [];
  const lines = content.split("\n");
  let inBlock = false;
  let blockStart = -1;
  let blockLines: Array<[number, string]> = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const stripped = line.trim();
    if (stripped.startsWith("```pseudocode")) {
      inBlock = true;
      blockStart = i + 1;
      blockLines = [];
    } else if (inBlock && stripped.startsWith("```")) {
      blocks.push({ startLine: blockStart, lines: blockLines });
      inBlock = false;
      blockLines = [];
    } else if (inBlock) {
      blockLines.push([i + 1, line]);
    }
  }

  if (inBlock) {
    blocks.push({ startLine: blockStart, lines: blockLines, unclosed: true });
  }

  return blocks;
}

// -- Lint logic --------------------------------------------------------------

function maskStrings(input: string): string {
  return input.replace(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g, '"_STR_"');
}

function lintBlocks(
  blocks: PseudocodeBlock[],
): { violations: PseudocodeViolation[]; advisories: PseudocodeAdvisory[] } {
  const violations: PseudocodeViolation[] = [];
  const advisories: PseudocodeAdvisory[] = [];

  for (const block of blocks) {
    const functionStack: number[] = [];

    for (const [lineNum, line] of block.lines) {
      const stripped = line.trim();

      if (!stripped || stripped.startsWith("//")) continue;

      // Mask strings first so // inside strings isn't a comment delimiter
      const maskedForComment = maskStrings(stripped);
      const commentMatch = maskedForComment.match(/\/\/.*$/);
      const cleanLine = commentMatch
        ? stripped.slice(0, commentMatch.index).trim()
        : stripped;
      if (!cleanLine) continue;

      const scanLine = maskStrings(cleanLine);
      const codePart = scanLine.replace(/"[^"]*"/g, "");

      // Check 1: bare assignment
      if (!scanLine.includes("←") && !scanLine.includes(":=")) {
        if (BARE_ASSIGNMENT.test(codePart)) {
          if (ASSIGNMENT_REQUIRED.test(scanLine)) {
            violations.push({
              line: lineNum,
              check: "bare_assignment",
              text: stripped,
              message:
                "Assignment context requires `←` or `:=`, not bare `=` -- FOR/SET/INCREMENT headers initialize or mutate state",
            });
          } else if (COMPARISON_CONTEXT.test(scanLine)) {
            // = is comparison here, no violation
          } else if (CASE_WHEN_PREFIX.test(scanLine)) {
            const colonIdx = codePart.indexOf(":");
            if (colonIdx >= 0) {
              const actionPart = codePart.slice(colonIdx + 1);
              if (BARE_ASSIGNMENT.test(actionPart) && !/[<>!]=/.test(actionPart)) {
                violations.push({
                  line: lineNum,
                  check: "bare_assignment",
                  text: stripped,
                  message:
                    "Bare assignment `=` in CASE/WHEN action -- use `SET ... ←` or `... := ...`",
                });
              }
            }
          } else if (!/[<>!]=/.test(codePart)) {
            violations.push({
              line: lineNum,
              check: "bare_assignment",
              text: stripped,
              message: "Bare assignment `=` -- use `SET ... ←` or `... := ...`",
            });
          }
        }
      }

      // Check 2: language-specific keywords/operators
      const bannedMatch = scanLine.match(BANNED_SYNTAX);
      if (bannedMatch) {
        const token = bannedMatch[0];
        const isOperator = BANNED_OPERATOR_TOKENS.includes(token);
        const msg = isOperator
          ? `Language-specific operator \`${token}\` -- use pseudocode notation (← for assignment, FUNCTION for definitions)`
          : `Language-specific keyword \`${token}\` -- use capitalized pseudocode keywords (FUNCTION, SET, IF, SWITCH/CASE, CALL ASYNC, WAIT FOR, etc.)`;
        violations.push({
          line: lineNum,
          check: "language_keyword",
          text: stripped,
          message: msg,
        });
      }

      // Check 3: multi-statement lines
      if (MULTI_STATEMENT.test(codePart)) {
        violations.push({
          line: lineNum,
          check: "multi_statement",
          text: stripped,
          message:
            "Multiple statements on one line (`;` separator) -- use one statement per line",
        });
      }

      // Check 4: library calls
      const libMatch = scanLine.match(LIBRARY_CALL);
      if (libMatch) {
        violations.push({
          line: lineNum,
          check: "library_call",
          text: stripped,
          message: `Potential library call \`${libMatch[0].trim()}\` -- use a generic operation name instead (e.g., \`WAIT\` not \`time.sleep()\`)`,
        });
      }

      // Check 5: single-character variable names (advisory, not violation)
      const charMatch = scanLine.match(SINGLE_CHAR_VAR);
      if (charMatch && !ALLOWED_SINGLE_CHAR.has(charMatch[1]!)) {
        advisories.push({
          line: lineNum,
          check: "abbreviated_name",
          text: stripped,
          message: `Single-character variable \`${charMatch[1]}\` -- use a descriptive name`,
        });
      }

      // Track FUNCTION / END FUNCTION balance
      if (FUNCTION_START.test(scanLine)) {
        functionStack.push(lineNum);
      }
      if (FUNCTION_END.test(scanLine)) {
        if (functionStack.length > 0) {
          functionStack.pop();
        } else {
          violations.push({
            line: lineNum,
            check: "unmatched_end_function",
            text: stripped,
            message: "END FUNCTION without matching FUNCTION",
          });
        }
      }
    }

    // Unclosed FUNCTION blocks
    for (const fnLine of functionStack) {
      violations.push({
        line: fnLine,
        check: "unclosed_function",
        text: `(FUNCTION opened at line ${fnLine})`,
        message: "FUNCTION without matching END FUNCTION",
      });
    }

    if (block.unclosed) {
      violations.push({
        line: block.startLine,
        check: "unclosed_fence",
        text: "(pseudocode block)",
        message: "Pseudocode fence opened but never closed",
      });
    }
  }

  return { violations, advisories };
}

// -- Public API --------------------------------------------------------------

/**
 * Validate pseudocode blocks in a concrete spec markdown file.
 * Returns pass/fail/warn status with violations and advisories.
 */
export function validatePseudocode(
  content: string,
  implPath: string,
): ValidatePseudocodeResult {
  const blocks = extractPseudocodeBlocks(content);

  if (blocks.length === 0) {
    return {
      status: "warn",
      implPath,
      warnings: [
        {
          check: "no_pseudocode",
          message: "No ```pseudocode blocks found in concrete spec",
        },
      ],
    };
  }

  const { violations, advisories } = lintBlocks(blocks);

  const result: ValidatePseudocodeResult = { implPath, status: "pass" };
  if (violations.length > 0) {
    result.status = "fail";
    result.violations = violations;
  } else if (advisories.length > 0) {
    result.status = "warn";
  }
  if (advisories.length > 0) {
    result.advisories = advisories;
  }
  return result;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd prunejuice && npx vitest run test/validators.test.ts`
Expected: all 13 tests PASS

- [ ] **Step 5: Full suite check**

Run: `cd prunejuice && npx vitest run`
Expected: all tests PASS (existing + 13 new)

- [ ] **Step 6: Commit**

```bash
cd prunejuice && git add src/validators.ts test/validators.test.ts && git commit -m "feat(prunejuice): port validate_pseudocode from Python to TypeScript"
```

---

## Task 2: Delete Python source code

**Files:**
- Delete: `unslop/scripts/` (26 .py files)
- Delete: `unslop/__pycache__/`, `unslop/scripts/__pycache__/`
- Delete: `pyproject.toml`, `uv.lock`

- [ ] **Step 1: Verify no remaining references from prunejuice**

Run: `grep -rn "orchestrator\.py\|validate_\|mcp_server\.py" prunejuice/src/ prunejuice/test/ 2>&1`
Expected: no matches (prunejuice should be independent of Python)

- [ ] **Step 2: Delete the directories**

Run:
```bash
cd /home/lewdwig/git/unslop
rm -rf unslop/scripts/
rm -rf unslop/__pycache__/
rm -f pyproject.toml
rm -f uv.lock
```

- [ ] **Step 3: Verify no broken references**

Run: `grep -rn "unslop/scripts\|orchestrator\.py" unslop/ docs/ 2>&1 | grep -v "^docs/superpowers/plans/" | grep -v "^docs/superpowers/specs/"`

Expected: matches only in skill/command files that will be cleaned up in later tasks. If there are any other matches (outside plans/specs), note them.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: delete Python orchestrator source (unslop/scripts/, pyproject.toml, uv.lock)"
```

---

## Task 3: Delete Python tests

**Files:**
- Delete: `tests/` (8 test files, ~9,179 lines)

- [ ] **Step 1: Delete the tests directory**

Run:
```bash
cd /home/lewdwig/git/unslop && rm -rf tests/
```

- [ ] **Step 2: Verify no references to Python tests**

Run: `grep -rn "tests/test_\|pytest" unslop/ docs/ .github/ 2>&1 | grep -v "plans/\|specs/"`
Expected: matches in `.github/workflows/python-package.yml` (will be deleted in Task 4) and potentially a few skill/command files (cleaned in later tasks).

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: delete Python test suite"
```

---

## Task 4: Delete Python CI workflow, create TypeScript workflow

**Files:**
- Delete: `.github/workflows/python-package.yml`
- Create: `.github/workflows/typescript-tests.yml`

- [ ] **Step 1: Delete the Python workflow**

Run: `rm .github/workflows/python-package.yml`

- [ ] **Step 2: Create the TypeScript workflow**

Create `.github/workflows/typescript-tests.yml`:

```yaml
name: TypeScript tests

permissions:
  contents: read

on:
  push:
    branches: ["main"]
  pull_request:
    branches: ["main"]

jobs:
  prunejuice:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: prunejuice
    steps:
      - uses: actions/checkout@v4

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install dependencies
        run: npm ci

      - name: Type check
        run: npx tsc --noEmit

      - name: Run tests
        run: npx vitest run

  plugin-structure:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Validate plugin.json exists
        run: test -f unslop/.claude-plugin/plugin.json

      - name: Validate plugin.json is valid JSON
        run: |
          python3 -c "import json; json.load(open('unslop/.claude-plugin/plugin.json'))" || \
          node -e "JSON.parse(require('fs').readFileSync('unslop/.claude-plugin/plugin.json','utf8'))"

      - name: Validate .mcp.json exists and references prunejuice
        run: |
          test -f unslop/.claude-plugin/.mcp.json
          grep -q "prunejuice" unslop/.claude-plugin/.mcp.json

      - name: Validate no stale Python references
        run: |
          if grep -rn "orchestrator\.py\|validate_behaviour\.py\|validate_mocks\.py\|validate_spec\.py" unslop/commands/ unslop/skills/ 2>&1; then
            echo "Stale Python references found in unslop plugin files"
            exit 1
          fi

      - name: Validate command files exist
        run: |
          for cmd in generate status change elicit sync graph coherence init takeover cover weed adversarial distill harden promote crystallize absorb exude verify spec; do
            test -f "unslop/commands/${cmd}.md" || (echo "Missing command: ${cmd}.md" && exit 1)
          done

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install root dependencies
        run: npm ci || echo "no root lockfile, skipping"

      - name: Lint prunejuice
        working-directory: prunejuice
        run: |
          npm ci
          npx eslint src/ --max-warnings 0 || echo "eslint config may not be set for prunejuice, skipping"
```

Note: the lint job uses `|| echo` fallbacks because ESLint config may not be set in prunejuice yet. If lint config is missing, the job logs and continues. When ESLint is configured, remove the fallbacks.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ && git commit -m "ci: migrate from Python pytest matrix to TypeScript vitest + plugin validation"
```

---

## Task 5: Rewrite unslop/skills/generation/SKILL.md

**Files:**
- Modify: `unslop/skills/generation/SKILL.md`

This is the largest skill (1337 lines) and contains the most orchestration prose. Target: reduce to ~400 lines of pure domain reference.

**Rewrite rules (apply to all skill rewrites):**

1. DELETE: Any explicit shell command invoking Python (`python ${CLAUDE_PLUGIN_ROOT}/scripts/orchestrator.py ...`, `python .../validate_*.py ...`)
2. DELETE: Step-by-step orchestration logic ("dispatch this agent, parse output, then dispatch that agent")
3. DELETE: References to `orchestrator.py`, `validate_*.py`, `mcp_server.py`, Python scripts generally
4. DELETE: Sections describing *how* to run the pipeline (prunejuice handles that via MCP)
5. KEEP: Domain knowledge (what specs are, what behaviour contracts are, adversarial framework concepts, concrete spec semantics, inheritance rules)
6. KEEP: Reference material (frontmatter schemas, section names, merge rules, agent role descriptions)
7. KEEP: The "why" of design decisions (Chinese Wall, boundary manifest, mutation testing)
8. REPLACE: Orchestration prose with single-sentence "prunejuice handles this via `prunejuice_<tool>` MCP tool" pointers
9. REPLACE: Validator invocations with "prunejuice Saboteur reports compliance violations" references

- [ ] **Step 1: Read the current skill file**

Read `unslop/skills/generation/SKILL.md` fully to identify orchestration vs reference content.

- [ ] **Step 2: Rewrite as domain reference**

The rewritten skill should cover:

- **What generation is** (intent -> spec -> tests -> code via convergence loop)
- **The five-phase pipeline** (distill, elicit, generate, cover, weed) — conceptually, not procedurally
- **Agent roles and information boundaries** (Architect, Archaeologist, Mason, Builder, Saboteur) — what each sees, not how they're dispatched
- **Chinese Wall** design rationale (Mason never sees implementation)
- **Spec frontmatter schemas** (depends-on, intent, non-goals, etc.) as reference tables
- **Managed file header format** (specification of the `@prunejuice-managed` comment format)
- **Hash chain states** (fresh, stale, modified, conflict, pending, structural, ghost-stale, test-drifted) — meanings, not how they're computed
- **Concrete spec concepts** (strategy projection, behaviour contract, fileTargets) — brief, with pointer to concrete-spec skill for depth
- **Discovery items and amendment flow** — conceptually (prunejuice's discovery handler is where this lives now)

The rewritten skill should NOT contain:
- Any shell commands
- Step-by-step pipeline execution instructions
- References to orchestrator.py, validate_*.py, or any Python file
- Implementation details of ripple check, build ordering, manifest computation (those live in prunejuice)

Target length: ~400 lines.

- [ ] **Step 3: Verify no Python refs remain**

Run: `grep -n "orchestrator\|validate_\|\.py\b\|python " unslop/skills/generation/SKILL.md`
Expected: no matches (or only in prose discussing the conceptual "orchestrator" role, not invoking scripts)

- [ ] **Step 4: Commit**

```bash
git add unslop/skills/generation/SKILL.md && git commit -m "refactor(skills): rewrite generation/SKILL.md as domain reference (drop orchestration prose)"
```

---

## Task 6: Rewrite unslop/skills/concrete-spec/SKILL.md

**Files:**
- Modify: `unslop/skills/concrete-spec/SKILL.md`

Current: 908 lines. Target: ~350 lines.

- [ ] **Step 1: Read the current skill file**

Read `unslop/skills/concrete-spec/SKILL.md`.

- [ ] **Step 2: Rewrite**

Apply the same rewrite rules as Task 5. This skill covers concrete spec semantics — what to KEEP:

- **Purpose of concrete specs** (bridge between abstract spec and code, strategy-projection layer)
- **Frontmatter fields** (source-spec, concrete-dependencies, extends, targets, ephemeral, complexity)
- **Pseudocode convention** (← assignment, capitalized keywords, no language-specific tokens) — this is the content that justifies validate_pseudocode
- **Inheritance rules** (STRICT_CHILD_ONLY, Pattern overridable, Lowering Notes additive, MAX_EXTENDS_DEPTH=3)
- **Ghost staleness semantics** — what it means conceptually, not how it's computed
- **Multi-target configuration** — the schema, not the collision detection algorithm
- **Promotion from ephemeral to permanent** — conceptually

What to DELETE:
- References to `orchestrator.py check_freshness`, `orchestrator.py concrete-deps`
- Descriptions of how `_identify_changed_deps()` or `diagnose_ghost_staleness()` work internally
- Step-by-step manifest computation procedures
- References to `validate_pseudocode.py` (replace with "prunejuice's pseudocode validator in src/validators.ts")

- [ ] **Step 3: Verify**

Run: `grep -n "orchestrator\|validate_\|\.py\b" unslop/skills/concrete-spec/SKILL.md`
Expected: no matches

- [ ] **Step 4: Commit**

```bash
git add unslop/skills/concrete-spec/SKILL.md && git commit -m "refactor(skills): rewrite concrete-spec/SKILL.md as domain reference"
```

---

## Task 7: Rewrite unslop/skills/spec-language/SKILL.md

**Files:**
- Modify: `unslop/skills/spec-language/SKILL.md`

Current: 660 lines. Target: ~450 lines (this one is mostly domain reference already, lighter touch).

- [ ] **Step 1: Read the file**

Read `unslop/skills/spec-language/SKILL.md`.

- [ ] **Step 2: Strip orchestration prose**

Keep: spec writing conventions, frontmatter schemas, section name guidance, voice/tone rules, anti-patterns, dependency declaration syntax.

Delete: any orchestration/pipeline references, references to `orchestrator.py`, mentions of how "the orchestrator resolves transitive dependencies" (replace with "prunejuice resolves transitive dependencies automatically").

- [ ] **Step 3: Verify**

Run: `grep -n "orchestrator\|validate_\|\.py\b" unslop/skills/spec-language/SKILL.md`
Expected: no matches

- [ ] **Step 4: Commit**

```bash
git add unslop/skills/spec-language/SKILL.md && git commit -m "refactor(skills): strip orchestration prose from spec-language/SKILL.md"
```

---

## Task 8: Rewrite unslop/skills/takeover/SKILL.md

**Files:**
- Modify: `unslop/skills/takeover/SKILL.md`

Current: 531 lines. Target: ~300 lines.

- [ ] **Step 1: Read the file**

Read `unslop/skills/takeover/SKILL.md`.

- [ ] **Step 2: Strip orchestration prose**

Keep: takeover concept (distill -> elicit -> generate), when to use, per-file vs unit granularity, discovery flow, user confirmation points.

Delete: explicit shell invocations of orchestrator.py, validate_behaviour.py, validate_mocks.py. Replace with references to prunejuice's `takeover()` orchestrator function and Saboteur compliance checks.

- [ ] **Step 3: Verify**

Run: `grep -n "orchestrator\|validate_\|\.py\b" unslop/skills/takeover/SKILL.md`
Expected: no matches

- [ ] **Step 4: Commit**

```bash
git add unslop/skills/takeover/SKILL.md && git commit -m "refactor(skills): strip orchestration prose from takeover/SKILL.md"
```

---

## Task 9: Clean up remaining small skills

**Files:**
- Modify: `unslop/skills/adversarial/SKILL.md` (335 lines)
- Modify: `unslop/skills/triage/SKILL.md` (278 lines)

These are smaller and cleaner. Likely only need to remove a few Python references and verify no orchestration prose.

- [ ] **Step 1: Scan adversarial/SKILL.md**

Run: `grep -n "orchestrator\|validate_\|\.py\b\|python " unslop/skills/adversarial/SKILL.md`

- [ ] **Step 2: Remove any hits found**

Replace Python references with prunejuice equivalents:
- `validate_behaviour.py` validation -> "prunejuice's BehaviourContract TS type enforces the schema structurally"
- `validate_mocks.py` boundary checks -> "Saboteur reports compliance violations for internal mocks"

- [ ] **Step 3: Scan triage/SKILL.md**

Run: `grep -n "orchestrator\|validate_\|\.py\b\|python " unslop/skills/triage/SKILL.md`

- [ ] **Step 4: Remove any hits found**

- [ ] **Step 5: Commit**

```bash
git add unslop/skills/ && git commit -m "refactor(skills): remove Python references from adversarial and triage skills"
```

---

## Task 10: Update command files with remaining Python references

**Files:**
- Modify: `unslop/commands/sync.md`
- Modify: `unslop/commands/cover.md`
- Modify: `unslop/commands/adversarial.md`
- Modify: `unslop/commands/coherence.md`
- Modify: `unslop/commands/init.md`

- [ ] **Step 1: sync.md — remove orchestrator references**

Run: `grep -n "orchestrator" unslop/commands/sync.md`
Expected hits at lines 100, 154, 326.

Replace:
- "in the order returned by the orchestrator" -> "in the order returned by `prunejuice_bulk_sync_plan` / `prunejuice_deep_sync_plan`"
- The hash computation reference (line 326) — replace "the same canonical method as `compute_hash()` in the orchestrator" with "prunejuice computes `specHash` and `outputHash` via SHA-256 truncated to 12 hex chars; see `prunejuice/src/hashchain.ts`"

- [ ] **Step 2: cover.md — remove validate_mocks.py invocation**

Run: `grep -n "validate_mocks" unslop/commands/cover.md`
Expected hit at line 215.

Replace the `python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_mocks.py` command with: "Rely on Saboteur's compliance checks in the SaboteurReport to catch internal mocking violations. Boundary manifest enforcement as a dedicated linter was removed in Phase 8; Saboteur reports mocking issues as `complianceViolations[]` entries."

- [ ] **Step 3: adversarial.md — remove validate_behaviour and validate_mocks**

Run: `grep -n "validate_" unslop/commands/adversarial.md`
Expected hits at lines 67 and 95.

Replace:
- Line 67 (validate_behaviour): "prunejuice's BehaviourContract TS interface enforces the schema at construction time; no separate validator needed"
- Line 95 (validate_mocks): same replacement as cover.md

- [ ] **Step 4: coherence.md — update orchestrator reference**

Run: `grep -n "orchestrator" unslop/commands/coherence.md`
Expected hit at line 20.

Replace "If the orchestrator reports a cycle during dependency resolution" with "If `prunejuice_ripple_check` or `prunejuice_build_order` reports a cycle during dependency resolution".

- [ ] **Step 5: init.md — update CI recipe**

Run: `grep -n "orchestrator\|python " unslop/commands/init.md`
Expected hit at line 201.

The CI recipe uses `uv run python -m unslop.scripts.orchestrator check-freshness .` which no longer exists. Replace the CI block to either:
(a) Call prunejuice's freshness MCP tool (requires MCP client in CI — complex)
(b) Remove the freshness check from the suggested CI recipe and note: "For CI freshness gates, shell into a Node environment and invoke `prunejuice/src/index.ts check-freshness` directly, or run `prunejuice_check_freshness` via an MCP client."

Go with (b) — it's honest about the current state.

- [ ] **Step 6: Verify no remaining Python references in commands**

Run: `grep -rn "orchestrator\|validate_\|\.py\b" unslop/commands/`
Expected: no matches (or only in prose that doesn't invoke Python, e.g., the "orchestrator" concept as a design term)

- [ ] **Step 7: Commit**

```bash
git add unslop/commands/ && git commit -m "refactor(commands): remove Python script invocations, point to prunejuice MCP tools"
```

---

## Task 11: Update root documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `.gitignore`

- [ ] **Step 1: Update README.md**

Remove any sections discussing Python orchestrator, `pyproject.toml`, `pytest`, or the Python tests. Add a brief architecture section:

```markdown
## Architecture

unslop is a Claude Code plugin that ships two coordinated pieces:

- **unslop/** — the plugin: markdown commands and skills, agent prompts, hooks
- **prunejuice/** — the TypeScript orchestrator (MCP server): freshness classification, dependency graph, ripple check, sync planning, agent dispatch, convergence loop

The plugin is the user-facing command layer. Prunejuice is the coordination mechanism -- commands invoke prunejuice via MCP tools to avoid reimplementing orchestration logic in markdown prompts.
```

- [ ] **Step 2: Update CLAUDE.md**

Read current content. Replace:

```bash
python -m pytest tests/test_orchestrator.py -q    # 405 tests, Python 3.8-3.14
```

with:

```bash
cd prunejuice && npx vitest run    # prunejuice test suite
cd prunejuice && npx tsc --noEmit  # type check
```

Remove the sentence "No build step. Plugin is pure markdown commands/skills + Python orchestrator scripts." Replace with: "The plugin is markdown commands/skills; prunejuice is the TypeScript MCP server that handles orchestration."

- [ ] **Step 3: Rewrite AGENTS.md architecture section**

AGENTS.md currently has a large Python architecture layout (`unslop/scripts/core/frontmatter.py`, etc). This needs to become a prunejuice architecture layout.

Replace the Python layout block with a prunejuice layout block:

```
prunejuice/
  src/
    api.ts                  # Library API: five phases + three orchestrators
    types.ts                # Shared types, branded hashes, discriminated unions
    pipeline.ts             # queryAgent(), convergence logic, survivor routing
    hashchain.ts            # SHA-256/12 hashing, managed file headers, freshness
    store.ts                # Artifact persistence to .prunejuice/
    dag.ts                  # Dependency graph cache, topological sort, build order
    ripple.ts               # Three-layer ripple check (abstract/concrete/code)
    sync.ts                 # deepSync/bulkSync/resumeSync planning + batching
    manifest.ts             # Concrete deps hashing + ghost staleness diagnostics
    inheritance.ts          # Extends chain + flattening (STRICT_CHILD_ONLY rules)
    freshness.ts            # Eight-state freshness classifier
    discover.ts             # Source file discovery
    spec-diff.ts            # Spec section diff
    validators.ts           # Pseudocode lint (ported from Python)
    mcp.ts                  # MCP server with 15+ tools
    agents/                 # Architect, Archaeologist, Mason, Builder, Saboteur
  test/
    *.test.ts               # vitest unit tests (300+ tests)

unslop/
  commands/                 # Markdown slash commands
  skills/                   # Domain reference skills
  hooks/                    # Shell hook scripts (load-context, regenerate-summary)
  .claude-plugin/
    plugin.json             # Plugin manifest
    .mcp.json               # MCP server config pointing to prunejuice
```

Remove the Python-specific sections like "All nested-list frontmatter parsers use `_parse_nested_list_field()` in frontmatter.py" — those describe internals of code that no longer exists.

Remove "Tests are in tests/test_orchestrator.py" — replace with "Tests are in prunejuice/test/*.test.ts using vitest."

- [ ] **Step 4: Update .gitignore**

Remove Python-specific entries:

```
__pycache__/
.pytest_cache/
*.egg-info/
```

Keep: `.worktrees/`, `.claude/*.local.md`

- [ ] **Step 5: Verify**

Run: `grep -rn "orchestrator\|pytest\|pyproject\|python " README.md CLAUDE.md AGENTS.md .gitignore 2>&1`
Expected: no hits in the problematic sense. "Orchestrator" as a design concept is fine; "orchestrator.py" or "pytest" are not.

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md AGENTS.md .gitignore && git commit -m "docs: update root documentation for Python retirement"
```

---

## Task 12: Version bump and final verification

**Files:**
- Modify: `unslop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump plugin version**

Read `unslop/.claude-plugin/plugin.json`, change `"version": "0.53.0"` to `"version": "0.54.0"`.

Also update the description. Current: "Spec-driven development harness for Claude Code -- 20 commands, five-phase model, five agents, three-tier domain skills, crystallize, constitutional principles, 405 tests"

Replace with: "Spec-driven development harness for Claude Code -- 20 commands, five-phase model, five agents, three-tier domain skills, crystallize, constitutional principles. TypeScript orchestration via prunejuice MCP server."

- [ ] **Step 2: Final verification grep**

Run:
```bash
cd /home/lewdwig/git/unslop
echo "=== Python source references ==="
grep -rn "unslop/scripts\|orchestrator\.py\|validate_behaviour\.py\|validate_mocks\.py\|validate_spec\.py\|validate_pseudocode\.py\|mcp_server\.py" unslop/ README.md CLAUDE.md AGENTS.md 2>&1 | grep -v "^docs/superpowers/plans/" || echo "clean"
echo ""
echo "=== pytest/pyproject references ==="
grep -rn "pytest\|pyproject\.toml\|uv\.lock" unslop/ README.md CLAUDE.md AGENTS.md 2>&1 | grep -v "^docs/superpowers/plans/" || echo "clean"
echo ""
echo "=== Python file extensions ==="
find . -name "*.py" -not -path "./node_modules/*" -not -path "./prunejuice/node_modules/*" 2>&1 || echo "none"
```

Expected: "clean", "clean", "none"

- [ ] **Step 3: Prunejuice test suite passes**

Run: `cd prunejuice && npx vitest run`
Expected: all tests pass (previous 297 + 13 new from Task 1 = ~310 tests)

- [ ] **Step 4: TypeScript compiles clean**

Run: `cd prunejuice && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 5: Commit final verification**

```bash
git add unslop/.claude-plugin/plugin.json && git commit -m "chore: bump plugin version to 0.54.0 for Phase 8 -- Python retirement complete"
```

---

## Known Gaps (documented, not blockers)

1. **Boundary manifest enforcement** — `validate_mocks.py` was deleted; Saboteur's LLM-based compliance checks replace it. If precise AST-level boundary checks are needed in practice, add them as a Saboteur enhancement with per-language rules (follow-up work).

2. **CI freshness gate** — the old Python workflow ran `orchestrator.py check-freshness` as a CI gate. The new TypeScript workflow doesn't. To re-add, the CI needs a way to invoke `prunejuice_check_freshness` via either a CLI entry in prunejuice/src/index.ts or an MCP client. This is a follow-up.

3. **Plugin distribution** — prunejuice currently lives as a sibling directory to the unslop plugin. The `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}/../prunejuice/src/mcp.ts` which works in the dev repo but not for users installing via the plugin marketplace. Packaging prunejuice alongside the plugin (as an npm dep, bundled dist, or subdirectory) is a separate concern from Python retirement and should be handled as a distinct follow-up.
