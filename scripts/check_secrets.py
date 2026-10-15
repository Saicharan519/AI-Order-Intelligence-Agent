"""Secret scanner, run as a git pre-commit hook and in CI.

Usage:
    python scripts/check_secrets.py --staged   # files staged for commit (pre-commit hook)
    python scripts/check_secrets.py --all      # every tracked or committable file

Three checks:
  1. Forbidden paths: .env files (except .env.example) and raw dataset files.
  2. Known secret formats (API keys, private keys) and env-style assignments with a value.
  3. Exact values from the local .env: catches a real password pasted anywhere.

Findings report file, line and rule only. Secret values are never printed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent

# TOKEN(?!S): an access TOKEN is secret, a count of TOKENS (e.g. LLM_MAX_TOKENS_PER_DAY) is not.
SECRET_NAME = r"[A-Z0-9_]*(?:PASSWORD|API_KEY|SECRET|TOKEN(?!S)|ACCESS_CODE)[A-Z0-9_]*"  # noqa: S105

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("api-key-sk", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # KEY=value at line start, no spaces around "=" (env-file and shell syntax), value non-empty.
    # Python constants such as `SECRET_NAME = ...` use spaces and are not matched.
    ("env-assignment", re.compile(rf"^\s*(?:export\s+)?({SECRET_NAME})=['\"]?([^\s'\"#]+)")),
]

# Values that are clearly placeholders, not secrets
PLACEHOLDER = re.compile(
    r"^(?:<.*>|\$\{.*\}|\.\.\.|x+|changeme|your[_-].*|example.*|none|null)$", re.I
)

MIN_KNOWN_SECRET_LEN = 8


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}"


def forbidden_path(path: str) -> str | None:
    """Return a rule name if this file must never be committed."""
    p = PurePosixPath(path.replace("\\", "/"))
    if p.name == ".env" or (p.name.startswith(".env.") and p.name != ".env.example"):
        return "env-file"
    if p.parts[:2] == ("data", "raw") and p.name != ".gitkeep":
        return "raw-dataset"
    return None


def scan_text(path: str, text: str, known_secrets: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in PATTERNS:
            m = pattern.search(line)
            if not m:
                continue
            if rule == "env-assignment" and PLACEHOLDER.match(m.group(2)):
                continue
            findings.append(Finding(path, lineno, rule))
        for name, value in known_secrets.items():
            if value in line:
                findings.append(Finding(path, lineno, f"value-of-{name}"))
    return findings


def load_known_secrets(env_path: Path) -> dict[str, str]:
    """Secret-like values from the local .env (never printed)."""
    secrets: dict[str, str] = {}
    if not env_path.exists():
        return secrets
    name_re = re.compile(rf"^{SECRET_NAME}$")
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        name, value = raw.split("=", 1)
        name, value = name.strip(), value.strip().strip("'\"")
        if name_re.match(name) and len(value) >= MIN_KNOWN_SECRET_LEN:
            secrets[name] = value
    return secrets


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True,  # noqa: S607
        encoding="utf-8",
    ).stdout


def _candidate_files(staged: bool) -> list[str]:
    if staged:
        out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    else:
        out = _git("ls-files", "--cached", "--others", "--exclude-standard")
    return [line for line in out.splitlines() if line]


def _read(path: str, staged: bool) -> str | None:
    try:
        if staged:
            return _git("show", f":{path}")
        return (REPO_ROOT / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, subprocess.CalledProcessError, OSError):
        return None  # binary or unreadable: skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    known = load_known_secrets(REPO_ROOT / ".env")
    findings: list[Finding] = []
    files = _candidate_files(args.staged)
    for path in files:
        rule = forbidden_path(path)
        if rule:
            findings.append(Finding(path, 0, rule))
            continue
        text = _read(path, args.staged)
        if text is not None:
            findings.extend(scan_text(path, text, known))

    if findings:
        print("Secret check FAILED (values not shown):")
        for f in findings:
            print(f"  {f}")
        print("Remove the secret (keep it only in .env). If one was ever committed, rotate it.")
        return 1
    print(f"Secret check passed ({len(files)} files scanned).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
