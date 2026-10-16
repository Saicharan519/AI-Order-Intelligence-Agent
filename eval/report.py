"""Build eval/reports/ablation.md from the run files in eval/results/ (T-5.6).

python eval/report.py
"""

from __future__ import annotations

import json
import sys

import yaml

from orderintel.config import PROJECT_ROOT
from orderintel.evaluation.golden import CATEGORY_COUNTS
from orderintel.evaluation.stats import wilson_interval

RESULTS = PROJECT_ROOT / "eval" / "results"
REPORT = PROJECT_ROOT / "eval" / "reports" / "ablation.md"
ORDER = ["A", "B", "C", "D"]
CATEGORIES = [c for c in CATEGORY_COUNTS if c != "out_of_scope"]


def prompt_versions(split: str, provider: str = "deepseek") -> list[str]:
    found = {p.stem.rsplit("_", 1)[1] for p in RESULTS.glob(f"{split}_*_{provider}_*.json")}
    return sorted(found)


def load(split: str, prompt: str, provider: str = "deepseek") -> dict[str, dict]:
    runs = {}
    for config in ORDER:
        path = RESULTS / f"{split}_{config}_{provider}_{prompt}.json"
        if path.exists():
            runs[config] = json.loads(path.read_text(encoding="utf-8"))
    return runs


def history_section(split: str) -> list[str]:
    """Strict accuracy per configuration for every prompt version run on this split."""
    versions = prompt_versions(split)
    if len(versions) < 2:
        return []
    lines = [
        "Prompt iterations (strict correct):",
        "",
        "| Prompt | " + " | ".join(ORDER) + " |",
        "|---|" + "---|" * len(ORDER),
    ]
    for v in versions:
        runs = load(split, v)
        lines.append(
            f"| `{v}` | "
            + " | ".join(
                f"{runs[c]['correct']}/{runs[c]['n']}" if c in runs else "-" for c in ORDER
            )
            + " |"
        )
    return lines + [""]


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def section(split: str, runs: dict[str, dict]) -> list[str]:
    if not runs:
        return [f"_No runs on the {split} split yet._", ""]
    lines = [
        "| Config | Data the model sees | Correct | Accuracy (95% CI) | Ran | Repairs "
        "| Calls (cached) | Cost | p50 / p95 latency |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    seen = {
        "A": "raw DDL",
        "B": "raw DDL + glossary",
        "C": "views + glossary",
        "D": "C + validator, EXPLAIN gate, repairs",
    }
    for c, r in runs.items():
        lo, hi = r["ci95"]
        lines.append(
            f"| {c} | {seen[c]} | {r['correct']}/{r['n']} | {pct(r['accuracy'])} "
            f"({pct(lo)}-{pct(hi)}) | {r['ran']}/{r['n']} | {r['repairs_used']} | "
            f"{r['llm_calls']} ({r['cached_calls']}) | ${r['cost_usd']:.4f} | "
            f"{r['latency_p50_ms']:.0f} / {r['latency_p95_ms']:.0f} ms |"
        )
    lines += [
        "",
        "Per category (correct / answerable):",
        "",
        "| Config | " + " | ".join(CATEGORIES) + " |",
        "|---|" + "---|" * len(CATEGORIES),
    ]
    for c, r in runs.items():
        cells = []
        for cat in CATEGORIES:
            v = r["by_category"].get(cat, {"n": 0, "correct": 0})
            cells.append(f"{v['correct']}/{v['n']}")
        lines.append(f"| {c} | " + " | ".join(cells) + " |")
    lines += ["", "Items answered wrongly:", ""]
    for c, r in runs.items():
        wrong = [i for i in r["items"] if not i["correct"]]
        lines.append(
            f"- **{c}** ({len(wrong)}): "
            + (
                ", ".join(f"`{i['id']}` ({i['failure_tag'] or i['auto_tag']})" for i in wrong)
                or "none"
            )
        )
    return lines + [""]


def load_tags(split: str, prompt_version: str) -> dict:
    path = PROJECT_ROOT / "eval" / "reviews" / f"{split}_{prompt_version}_tags.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def review_section(runs: dict[str, dict], tags: dict) -> list[str]:
    if not tags:
        return []
    lines = [
        "Manual review of every wrong answer (`eval/reviews/`). *Data correct* counts answers "
        "whose numbers are right but whose shape differs from the reference (tag "
        "`output_format`: extra columns, text labels instead of booleans, month as text). "
        "The strict score above remains the headline metric.",
        "",
        "| Config | Strict correct | Data correct | Real analytical errors | Format-only misses |",
        "|---|---|---|---|---|",
    ]
    tag_counts: dict[str, dict[str, int]] = {}
    for c, r in runs.items():
        t = tags.get(c, {})
        fmt = sum(1 for v in t.values() if not v["semantic"])
        sem = sum(1 for v in t.values() if v["semantic"])
        data_ok = r["correct"] + fmt
        lo, hi = wilson_interval(data_ok, r["n"])
        lines.append(
            f"| {c} | {r['correct']}/{r['n']} | {data_ok}/{r['n']} "
            f"({pct(data_ok / r['n'])}, CI {pct(lo)}-{pct(hi)}) | {sem} | {fmt} |"
        )
        for v in t.values():
            tag_counts.setdefault(v["tag"], {}).setdefault(c, 0)
            tag_counts[v["tag"]][c] += 1
    lines += [
        "",
        "Failure tags:",
        "",
        "| Tag | " + " | ".join(runs) + " |",
        "|---|" + "---|" * len(runs),
    ]
    for tag in sorted(tag_counts):
        lines.append(
            f"| {tag} | " + " | ".join(str(tag_counts[tag].get(c, 0)) for c in runs) + " |"
        )
    return lines + [""]


def apply_tags(runs: dict[str, dict], tags: dict) -> None:
    for c, r in runs.items():
        for item in r["items"]:
            tagged = tags.get(c, {}).get(item["id"])
            if tagged:
                item["failure_tag"] = tagged["tag"]


def main() -> int:
    versions = prompt_versions("dev")
    selection = PROJECT_ROOT / "eval" / "reviews" / "prompt_selection.yaml"
    if selection.exists():
        prompt = yaml.safe_load(selection.read_text(encoding="utf-8"))["final_prompt"]
    else:
        prompt = versions[-1] if versions else "sqlgen-v1"
    dev = load("dev", prompt)
    apply_tags(dev, load_tags("dev", prompt))
    test_versions = prompt_versions("test")
    test_prompt = test_versions[-1] if test_versions else prompt
    test = load("test", test_prompt)
    apply_tags(test, load_tags("test", test_prompt))
    out = [
        "# Ablation results",
        "",
        "Generated by `eval/report.py` from `eval/results/`. Execution accuracy over answerable "
        "golden items (PRD section 11); 95% Wilson intervals. Model: `deepseek-flash`, thinking "
        f"disabled, temperature 0, prompt `{prompt}`.",
        "",
        "Note on configuration D: its first request is identical to configuration C's, so it "
        "is served from the response cache (temperature 0). D can differ from C only where "
        "the validator or executor rejects the SQL and a repair follows.",
        "",
        "## Development split (36 answerable items; prompt tuning allowed)",
        "",
        *history_section("dev"),
        f"Selected prompt `{prompt}` (rule: `eval/reviews/prompt_selection.yaml`):",
        "",
        *section("dev", dev),
        *review_section(dev, load_tags("dev", prompt)),
        "## Test split (18 answerable items; frozen, run once per configuration)",
        "",
        *section("test", test),
        *review_section(test, load_tags("test", test_prompt)),
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
