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
