# SQL parser decision (Q-04)

Date: 2026-10-15 (milestone M4). Versions: sqlglot 30.23.0, pglast 8.6 (libpg_query, PostgreSQL's own grammar).

## Question

Should the validator parse SQL with `sqlglot` or `pglast`?

## Experiment

66 inputs were validated with the sqlglot-based validator, and both the original input and the regenerated (executed) SQL were parsed with pglast:

- 28 SQL attack strings from `eval/golden/attacks.yaml`;
- 12 parser-confusion inputs: nested comments (`/* /* */ ; DROP ... */`), dollar quoting (`$$; DROP ...$$`), `E''` escape strings, doubled quotes, Unicode identifiers (`U&"..."`), trailing `--` comments, backslash-semicolon, regex operators, quoted identifiers;
- 26 legitimate view queries (`tests/fixtures/view_queries.py`).

The question that matters is not whether the parsers agree on every input, but whether **any query the validator accepts could be read by PostgreSQL as something other than exactly one SELECT**, because the executor runs the regenerated SQL.

## Results

| Measure | Result |
|---|---|
| Inputs accepted by the validator | 37 |
| Accepted inputs whose regenerated SQL PostgreSQL does not read as exactly one `SelectStmt` | **0** |
| Attacks accepted by the validator | 3, all by design: two expensive joins (stopped by the executor's cost ceiling) and `SELECT * FROM analytics.order_items` (capped at 500 rows) |
| Nested-comment and dollar-quote tricks | Accepted as harmless single SELECTs; the hidden `DROP`/`DELETE` text is inside a comment or string literal in both parsers, and comments are removed on regeneration |
| `E'\';DROP ...'` escape trick | Rejected by the validator (two statements) |

Differences found (not security issues):

- `SELECT '\x41'` was regenerated as `SELECT 'A'`: sqlglot treats backslashes in ordinary strings as escapes, PostgreSQL (with `standard_conforming_strings = on`) does not. The statement structure is unchanged; only that literal's value differs. Recorded as a known limitation.
- The regex operator `~` is mapped by sqlglot to a function that is not allow-listed, so regex filters are rejected. Acceptable (also avoids expensive regex patterns); `LIKE`/`ILIKE` are allowed.
- pglast alone would not catch `WITH d AS (DELETE ...) SELECT ...`: the top-level statement is still a `SelectStmt`. A whole-tree check is required with either parser.

## Decision

- **sqlglot is the primary parser.** It supports what the validator needs beyond parsing: walking and rewriting the tree (LIMIT enforcement, comment removal, regeneration) and schema-aware column resolution (VR-06). It is pure Python.
- **pglast is added as a second opinion (part of VR-09).** After regeneration, PostgreSQL's real grammar must read the SQL as exactly one SELECT and no `InsertStmt`, `UpdateStmt`, `DeleteStmt`, `MergeStmt`, `intoClause`, or `lockingClause` may appear anywhere in its tree. Cost: one pinned dependency (wheels exist for Windows, macOS and Linux) and about 30 lines.

## What this does not prove

The comparison covers these inputs only. It does not prove the absence of other parser differentials; the database role (SC-01) remains the guarantee if both parsers were wrong in the same way.
