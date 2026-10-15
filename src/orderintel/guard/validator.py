"""SQL validator (technical design, section 7.2, rules VR-01 to VR-09).

Every query, whether written by the model or by a playbook, passes through validate()
before it can reach the database. The validator parses the SQL into a syntax tree with
sqlglot and applies allow-lists; it never pattern-matches on the raw text.

The output is a ValidatedSQL object holding SQL that was REGENERATED from the syntax
tree: comments are dropped, a LIMIT is enforced, and the original string is never
executed. The executor only accepts ValidatedSQL objects, so there is no other path from
model output to the database (FR-04).

This is defence in depth, not the only wall: the oi_agent role cannot write or read
outside the views even if a rule here had a gap (docs/postgres_findings.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import sqlglot
from pglast.parser import ParseError as PgParseError
from pglast.parser import parse_sql_json
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from orderintel.guard.allowlists import (
    ALLOWED_CAST_TYPES,
    ALLOWED_FUNCTIONS,
    DENIED_FUNCTION_HINTS,
    view_columns,
)

ROW_CAP = 500
MAX_SQL_LENGTH = 4000
MAX_RELATIONS = 6
MAX_IN_LIST = 100
MAX_SUBQUERY_DEPTH = 4
SCHEMA = "analytics"

RULES = {
    "VR-01": "exactly one statement",
    "VR-02": "SELECT only (including CTEs and set operations)",
    "VR-03": "no SELECT INTO, no FOR UPDATE/SHARE",
    "VR-04": "only analytics views (or CTEs defined in the query)",
    "VR-05": "only allow-listed functions and cast types",
    "VR-06": "every column resolves against the view columns",
    "VR-07": f"LIMIT enforced (at most {ROW_CAP} rows returned)",
    "VR-08": "size limits: length, relations, IN lists, nesting, no recursion",
    "VR-09": "comments removed; SQL regenerated from the syntax tree and re-checked by "
    "PostgreSQL's own parser",
}

# Statement and clause types that must never appear anywhere in the tree (VR-02).
# Resolved by name so a sqlglot version without one of them still imports.
_FORBIDDEN_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "AlterTable",
    "AlterColumn",
    "TruncateTable",
    "Command",
    "Copy",
    "Set",
    "SetItem",
    "Transaction",
    "Commit",
    "Rollback",
    "Use",
    "Grant",
    "Revoke",
    "Pragma",
    "LoadData",
    "Describe",
    "Cache",
    "Uncache",
    "Refresh",
    "Kill",
    "Analyze",
    "Comment",
    "Summarize",
)  # FOR UPDATE/SHARE (exp.Lock) is reported by VR-03; LOCK TABLE parses as a Command
FORBIDDEN_NODES = tuple(
    t for t in (getattr(exp, n, None) for n in _FORBIDDEN_NODE_NAMES) if isinstance(t, type)
)
QUERY_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.message}"


_TOKEN = object()  # only this module can mint ValidatedSQL


@dataclass(frozen=True)
class ValidatedSQL:
    sql: str
    row_cap: int
    limit_note: str
    _token: object = field(repr=False, compare=False, default=None)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise TypeError("ValidatedSQL can only be created by the validator")


@dataclass
class ValidationResult:
    ok: bool
    validated: ValidatedSQL | None = None
    violations: list[Violation] = field(default_factory=list)
    rules_checked: list[str] = field(default_factory=lambda: list(RULES))

    @property
    def sql(self) -> str | None:
        return self.validated.sql if self.validated else None

    def feedback(self) -> str:
        """Short, model-facing explanation used by the repair loop."""
        return "; ".join(str(v) for v in self.violations)


def _function_name(node: exp.Func) -> str:
    return node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()


def _cast_type(node: exp.Cast) -> str:
    target = node.to.this
    return target.name if isinstance(target, exp.DataType.Type) else str(target).upper()


def _check_tree(root: exp.Expression, views: dict) -> list[Violation]:
    v: list[Violation] = []

    # VR-02: nothing but a query, anywhere in the tree (catches DELETE inside a CTE)
    for node in root.walk():
        if isinstance(node, FORBIDDEN_NODES):
            v.append(Violation("VR-02", f"{type(node).__name__} is not allowed"))
            return v

    # VR-03
    for sel in root.find_all(exp.Select):
        if sel.args.get("into"):
            v.append(Violation("VR-03", "SELECT INTO is not allowed"))
        if sel.args.get("locks"):
            v.append(Violation("VR-03", "FOR UPDATE / FOR SHARE is not allowed"))

    # VR-08: recursion
    for w in root.find_all(exp.With):
        if w.args.get("recursive"):
            v.append(Violation("VR-08", "recursive CTEs are not allowed"))

    # VR-04: relations
    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    n_view_refs = 0
    for t in root.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            v.append(Violation("VR-04", f"table functions are not allowed: {t.sql()}"))
            continue
        name, db, catalog = t.name.lower(), t.db.lower(), t.catalog.lower()
        if not db and not catalog and name in cte_names:
            continue
        if catalog or db not in ("", SCHEMA) or name not in views:
            allowed = ", ".join(sorted(views))
            v.append(
                Violation("VR-04", f"relation {t.sql()} is not allowed; use one of: {allowed}")
            )
            continue
        n_view_refs += 1
    if n_view_refs > MAX_RELATIONS:
        v.append(Violation("VR-08", f"{n_view_refs} view references; at most {MAX_RELATIONS}"))

    # VR-05: functions and casts
    for f in root.find_all(exp.Func):
        name = _function_name(f)
        if name not in ALLOWED_FUNCTIONS:
            hint = DENIED_FUNCTION_HINTS.get(name, "not in the allow-list")
            v.append(Violation("VR-05", f"function {name.lower()} is not allowed ({hint})"))
    for c in root.find_all(exp.Cast):
        if _cast_type(c) not in ALLOWED_CAST_TYPES:
            v.append(Violation("VR-05", f"cast to {_cast_type(c).lower()} is not allowed"))
    if any(True for _ in root.find_all(exp.Placeholder, exp.Parameter)):
        v.append(Violation("VR-05", "parameters/placeholders are not allowed in generated SQL"))

    # VR-08: IN-list size and nesting depth
    for i in root.find_all(exp.In, exp.Array):
        if len(i.expressions) > MAX_IN_LIST:
            v.append(
                Violation("VR-08", f"list of {len(i.expressions)} items; at most {MAX_IN_LIST}")
            )
    for sel in root.find_all(exp.Select):
        depth, parent = 0, sel.parent
        while parent is not None:
            depth += isinstance(parent, exp.Select)
            parent = parent.parent
        if depth > MAX_SUBQUERY_DEPTH:
            v.append(Violation("VR-08", f"subqueries nested deeper than {MAX_SUBQUERY_DEPTH}"))
            break
    return v


# Keys in PostgreSQL's own parse tree that must never appear in an executable query.
_PG_FORBIDDEN_KEYS = frozenset(
    {
        "InsertStmt",
        "UpdateStmt",
        "DeleteStmt",
        "MergeStmt",
        "intoClause",
        "lockingClause",
    }
)


def _pg_keys(node: object):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _pg_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _pg_keys(v)


def _postgres_second_opinion(sql: str) -> list[Violation]:
    """VR-09: PostgreSQL's real grammar (pglast/libpg_query) must read the regenerated SQL
    as exactly one SELECT with no data-modifying node anywhere. Guards against sqlglot
    printing something PostgreSQL would interpret differently (Q-04)."""
    try:
        stmts = json.loads(parse_sql_json(sql)).get("stmts", [])
    except PgParseError as e:
        return [Violation("VR-09", f"PostgreSQL grammar rejects the regenerated SQL: {e}")]
    if len(stmts) != 1 or "SelectStmt" not in stmts[0].get("stmt", {}):
        return [Violation("VR-09", "PostgreSQL grammar does not read this as exactly one SELECT")]
    bad = _PG_FORBIDDEN_KEYS.intersection(_pg_keys(stmts[0]))
    if bad:
        return [Violation("VR-09", f"PostgreSQL grammar finds forbidden clauses: {sorted(bad)}")]
    return []


def _check_columns(root: exp.Expression) -> list[Violation]:
    """VR-06, on a copy: qualification rewrites the tree, so it is never executed."""
    try:
        qualify(
            root.copy(),
            schema={SCHEMA: view_columns()},
            db=SCHEMA,
            dialect="postgres",
            validate_qualify_columns=True,
            quote_identifiers=False,
            identify=False,
        )
    except OptimizeError as e:
        return [Violation("VR-06", str(e).split(". Line")[0])]
    except Exception as e:  # noqa: BLE001 - any resolver failure is a rejection
        return [Violation("VR-06", f"could not resolve columns ({type(e).__name__})")]
    return []


def _enforce_limit(root: exp.Expression, row_cap: int) -> tuple[exp.Expression, str, list]:
    """VR-07: LIMIT row_cap + 1 lets the executor detect (and flag) truncation."""
    fetch = row_cap + 1
    limit = root.args.get("limit")
    if limit is None:
        return root.limit(fetch, copy=False), f"LIMIT {fetch} added", []
    value = limit.expression
    if not isinstance(value, exp.Literal) or not value.is_int:
        return root, "", [Violation("VR-07", "LIMIT must be a whole-number literal")]
    if int(value.this) > row_cap:
        return root.limit(fetch, copy=False), f"LIMIT {value.this} lowered to {fetch}", []
    return root, "", []


def validate(sql: str, *, row_cap: int = ROW_CAP) -> ValidationResult:
    if len(sql) > MAX_SQL_LENGTH:
        return ValidationResult(
            False,
            violations=[
                Violation("VR-08", f"SQL is {len(sql)} characters; at most {MAX_SQL_LENGTH}")
            ],
        )

    # VR-01: parse; exactly one statement
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as e:
        msg = str(e).splitlines()[0][:200]
        return ValidationResult(False, violations=[Violation("VR-01", f"could not parse: {msg}")])
    if len(statements) != 1:
        return ValidationResult(
            False,
            violations=[
                Violation("VR-01", f"{len(statements)} statements; exactly one is allowed")
            ],
        )
    root = statements[0]
    while isinstance(root, exp.Subquery) and isinstance(root.this, QUERY_ROOTS):
        root = root.this  # "(SELECT ...)" written with outer parentheses

    # VR-02: the root must be a query
    if not isinstance(root, QUERY_ROOTS):
        return ValidationResult(
            False,
            violations=[Violation("VR-02", f"only SELECT is allowed, got {type(root).__name__}")],
        )

    views = view_columns()
    violations = _check_tree(root, views)
    if not violations:
        violations = _check_columns(root)
    if violations:
        return ValidationResult(False, violations=violations)

    root, limit_note, limit_violations = _enforce_limit(root, row_cap)
    if limit_violations:
        return ValidationResult(False, violations=limit_violations)

    # VR-09: regenerate from the tree (drops comments); re-parse as a consistency check
    canonical = root.sql(dialect="postgres", comments=False)
    reparsed = [s for s in sqlglot.parse(canonical, read="postgres") if s is not None]
    if len(reparsed) != 1 or not isinstance(reparsed[0], QUERY_ROOTS):
        return ValidationResult(
            False,
            violations=[
                Violation("VR-09", "regenerated SQL did not round-trip to a single SELECT")
            ],
        )
    second_opinion = _postgres_second_opinion(canonical)
    if second_opinion:
        return ValidationResult(False, violations=second_opinion)

    return ValidationResult(True, ValidatedSQL(canonical, row_cap, limit_note, _TOKEN))
