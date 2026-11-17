"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    # 1. Any metric value in pr["metrics"] is NaN or inf
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, (int, float)) and (math.isnan(v) or math.isinf(v)):
            problems.append(f"metric {k} has invalid value {v}")

    # 2. Row count matches manifest items x seeds
    manifest = pr.get("manifest") or {}
    expected_count = int(manifest.get("items", 0)) * len(manifest.get("seeds") or [])
    rows = pr.get("rows") or []
    if len(rows) != expected_count:
        problems.append(f"row count {len(rows)} != expected {expected_count}")

    # 3. (item_id, seed) set equals baseline's
    base_rows = base.get("rows") or []
    pr_pairs = {(r["item_id"], r["seed"]) for r in rows if "item_id" in r and "seed" in r}
    base_pairs = {(r["item_id"], r["seed"]) for r in base_rows if "item_id" in r and "seed" in r}
    if pr_pairs != base_pairs:
        problems.append("PR (item_id, seed) set differs from baseline (cherry-picked or missing seeds)")

    # 4. Evaluator failures or None values for graded metrics
    if pr.get("evaluator_failures"):
        problems.append(f"evaluator_failures non-empty ({len(pr['evaluator_failures'])} failure(s))")
    graded_spec_metrics = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for r in rows:
        for mid in graded_spec_metrics:
            if r.get(mid) is None:
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has None for metric {mid}")
                break
        if problems and problems[-1].endswith(f"metric {mid}"):
            break

    # 5. Ratchet check with base_spec
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        pr_metrics_by_id = {m["id"]: m for m in spec.get("metrics") or []}
        for bm in base_spec.get("metrics") or []:
            mid = bm["id"]
            if mid not in pr_metrics_by_id:
                problems.append(f"metric {mid} disappeared from spec")
                continue
            pm = pr_metrics_by_id[mid]
            if bm.get("blocking") and not pm.get("blocking"):
                problems.append(f"metric {mid} changed from blocking to non-blocking")
            bth, pth = bm.get("threshold") or {}, pm.get("threshold") or {}
            if "max" in bth:
                if "max" not in pth or pth["max"] > bth["max"]:
                    problems.append(f"metric {mid} threshold max loosened")
            if "min" in bth:
                if "min" not in pth or pth["min"] < bth["min"]:
                    problems.append(f"metric {mid} threshold min loosened")
            if bth.get("no_significant_drop") and not pth.get("no_significant_drop"):
                problems.append(f"metric {mid} dropped no_significant_drop")
            if "max_increase" in bth:
                if "max_increase" not in pth or pth["max_increase"] > bth["max_increase"]:
                    problems.append(f"metric {mid} threshold max_increase loosened")

        pr_slices = {(s["name"], s.get("metric", "pass_rate")): s for s in spec.get("slices") or []}
        for bs in base_spec.get("slices") or []:
            key = (bs["name"], bs.get("metric", "pass_rate"))
            if key not in pr_slices:
                problems.append(f"slice {key[0]}/{key[1]} disappeared from spec")
                continue
            ps = pr_slices[key]
            if bs.get("blocking") and not ps.get("blocking"):
                problems.append(f"slice {key[0]}/{key[1]} changed from blocking to non-blocking")
            if "min" in bs and ("min" not in ps or ps["min"] < bs["min"]):
                problems.append(f"slice {key[0]}/{key[1]} min loosened")
            if bs.get("no_significant_drop") and not ps.get("no_significant_drop"):
                problems.append(f"slice {key[0]}/{key[1]} dropped no_significant_drop")

    # 6. Item slice tags modified between PR and baseline
    base_slice_map = {(r["item_id"], r["seed"]): sorted(r.get("slices") or []) for r in base_rows}
    for r in rows:
        key = (r.get("item_id"), r.get("seed"))
        if key in base_slice_map:
            if sorted(r.get("slices") or []) != base_slice_map[key]:
                problems.append(f"item {r.get('item_id')} slice tags changed in PR")
                break

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})

    for s in spec.get("slices") or []:
        name = s["name"]
        metric = s.get("metric", "pass_rate")
        min_val = s.get("min")
        no_drop = s.get("no_significant_drop", False)
        is_blocking = s.get("blocking", True)

        pr_items = per_item(pr, metric, slice_name=name)
        if not pr_items:
            continue
        val = sum(pr_items.values()) / len(pr_items)

        verdict = "ok"
        note = ""

        if min_val is not None and val < min_val:
            verdict = "fail"

        if no_drop:
            base_items = per_item(base, metric, slice_name=name)
            keys = sorted(set(pr_items) & set(base_items))
            if keys:
                d, lo, hi = stats.paired_bootstrap(
                    [pr_items[k] for k in keys],
                    [base_items[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"

        sid = f"slice:{name}/{metric}"
        if verdict != "ok" and is_blocking:
            blocked.append(sid)

        label = "BLOCK" if verdict == "fail" and is_blocking else ("warn" if verdict == "fail" else "ok")
        th_dict = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<22} {val:<8.4f} {json.dumps(th_dict):<40} {note:<28} {label}")

    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
