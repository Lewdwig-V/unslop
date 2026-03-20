# unslop

> You vibed your way to a working prototype. Now make it software.

`unslop` is a Claude Code plugin that rescues vibe-coded prototypes into disciplined software engineering practice. It treats generated code as the raw material, not the product — and spec files as the durable artefact that actually belongs in version control.

It delegates planning and execution to the [superpowers](https://github.com/obra/superpowers-marketplace) plugin, which enforces TDD red-green-refactor discipline and code review checkpoints. `unslop` adds the layer above that: the spec-as-source-of-truth model, the takeover pipeline, and the conventions that make the whole thing repeatable.

## The problem

Vibe coding gets you to a working prototype fast. The problem is what you have afterwards: no tests, no clear separation between intent and implementation, generated code you're afraid to touch because you don't fully understand it, and a codebase that resists every attempt at disciplined iteration.

The usual response is to rewrite. `unslop` proposes a different path: extract what the code *means*, validate it against tests, and let that specification drive all future changes. The original code becomes a validated first draft. The spec becomes the thing you maintain.

## Prerequisites

- [Claude Code](https://claude.ai/code)
- [superpowers](https://github.com/obra/superpowers-marketplace) plugin installed

```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

## Installation

```
/plugin marketplace add yourusername/unslop-marketplace
/plugin install unslop@unslop-marketplace
```

## Workflow

### Starting fresh

If you're building something new and want to stay out of vibe-coding territory from the start:

```
/unslop:spec src/retry.py
/unslop:generate
```

Write your spec. `unslop` hands it to `superpowers` for structured plan-then-execute generation with TDD enforcement. The generated file is marked managed. You maintain the spec; `unslop` maintains the code.

### Rescuing existing code

This is the core use case. You have a working prototype. You want to bring it under harness.

```
/unslop:takeover src/retry.py
```

The takeover pipeline:

1. Reads the existing file *and its tests*
2. Drafts a spec that captures intent, not implementation — what the code does, not how it does it
3. Archives the original to `.unslop/archive/`
4. Generates fresh code from the spec alone, with no anchoring on the original
5. Runs the test suite
6. If tests fail: surfaces the missing semantic constraint, enriches the spec, regenerates
7. Iterates until green
8. Commits the spec; the generated file becomes managed

The validation loop is the point. If the spec is sufficient to regenerate passing tests from scratch, it's a real spec. If it isn't, the failing tests tell you exactly what's missing.

### Checking status

```
/unslop:status
```

Lists all managed files, flags those whose specs have changed since last generation, and identifies files that have been directly edited (which is not supposed to happen).

### Regenerating stale files

```
/unslop:generate          # all stale managed files
/unslop:sync src/retry.py # one specific file
```

Edit the spec. Run `generate`. The managed file is overwritten. Your edit surface is the spec, not the code.

## Conventions

### Managed files

Managed files carry a header comment that marks them as unslop-owned:

```python
# @unslop-managed — do not edit directly. Edit src/retry.spec.md instead.
# Generated from spec at 2026-03-20T14:32:00Z
```

A pre-commit hook (installed by `/unslop:init`) warns if you attempt to commit a managed file with modifications that post-date the spec. The spec is the edit surface. The generated file is always disposable.

### Spec files

Specs live alongside their source files by convention:

```
src/
  retry.py          # managed — do not edit
  retry.spec.md     # edit this
  retry_test.py     # human-owned — ground truth
```

Specs describe intent, not implementation. The discipline:

| Write this | Not this |
|---|---|
| `Messages are stored in SQLite with a monotonic sequence ID` | `Use INSERT OR REPLACE with a rowid alias column` |
| `Retries use exponential backoff with jitter, max 5 attempts` | `sleep(2**attempt + random.uniform(0,1))` |
| `Validation rejects inputs over 1MB` | `if len(data) > 1_048_576: raise ValueError` |

If your spec reads like commented-out code, it's over-specified. The LLM fills the implementation gap. The tests constrain what filling is acceptable.

### What belongs under unslop management

`unslop` works best for code where the *what* is completely separable from the *how*: adapters, parsers, boilerplate, glue code, serialisation logic, CLI wrappers. Code where the implementation *is* the semantics — performance-critical algorithms, type-level invariants, anything with subtle concurrency behaviour — belongs in human-owned files. `unslop` does not try to manage everything; it manages the things where managing them is sound.

## Skills

`unslop` ships a skills directory that superpowers can load on demand:

- `unslop/spec-language.md` — vocabulary guide with positive and negative examples; the register that makes specs reliably interpretable
- `unslop/generation.md` — generation discipline; managed file conventions, test-first enforcement, boundary markers
- `unslop/takeover.md` — takeover pipeline orchestration; the validation loop, enrichment protocol, archive conventions
- `unslop/domain/` — domain-specific priors; add your own here

Domain skills are the primary tunability lever. If your codebase has consistent patterns — Helm templates, Ansible tasks, REST adapters, a specific framework's idioms — encoding them as few-shot examples in a domain skill dramatically tightens generation variance. `unslop/domain/` is on your path; skills there shadow the core skills when paths match.

## Commands

| Command | Description |
|---|---|
| `/unslop:init` | Initialise `.unslop/` directory, install pre-commit hook |
| `/unslop:spec <file>` | Create or edit the spec for a source file |
| `/unslop:takeover <file>` | Run the takeover pipeline on an existing file |
| `/unslop:generate` | Regenerate all stale managed files |
| `/unslop:sync <file>` | Regenerate one specific managed file |
| `/unslop:status` | List managed files and staleness |
| `/unslop:unamanage <file>` | Remove a file from management (keeps last generated version) |

## Philosophy

The spec is the durable artefact. The code is derived.

This is an inversion of the usual model, where the code is the ground truth and comments or documentation are the afterthought. `unslop` enforces the inversion structurally: managed files are overwritten on every generation cycle, so editing them directly is pointless. The only way to change the behaviour of a managed file is to change its spec.

The practical consequence: code review happens at the spec level, not the code level. Diffs are spec diffs. The generated code is an output of the review process, not an input to it.

This works for a specific class of code. It doesn't work for everything. The `/unslop:takeover` pipeline will tell you which — if the validation loop can't converge on a passing spec without over-specifying to implementation detail, the file probably shouldn't be managed.

## Contributing

The skills directory is the most useful place to contribute. Domain-specific skills for common patterns — FastAPI adapters, Terraform modules, React components, dbt models — make `unslop` useful for more codebases with less configuration. PRs welcome.

## Acknowledgements

Built on [superpowers](https://github.com/obra/superpowers-marketplace) by Jesse Vincent, without which the disciplined execution layer would need to be reinvented from scratch. The spec-as-source-of-truth model is directly inspired by [CodeSpeak](https://codespeak.dev/).

## License

MPL 2.0
