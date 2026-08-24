"""sweep.py — parameter sweeps for qs_bot against the sparring panel.

LOCAL ONLY. Never submitted.

The bot's tunables are module-level constants, and its methods read them as
globals at call time, so a sweep is just: set the global, re-score the panel.

    python lab/sweep.py RIDE_THRESHOLD 0 2 4 8 16
    python lab/sweep.py --quick SHADE 0.4 0.55 0.7
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from arena import OUR_BOT, duel, SEEDS, N_DEALS  # noqa: E402
import opponents                              # noqa: E402


def load_module(path=OUR_BOT, name="qs_subject"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def score(mod, panel, seeds, n_deals):
    """Return (mean, worst_name, worst_value, per-opponent dict)."""
    per = {}
    for name, opp in panel:
        per[name] = duel(mod.Bot, opp, seeds, n_deals).mean
    mean = statistics.fmean(per.values())
    worst = min(per.items(), key=lambda kv: kv[1])
    return mean, worst[0], worst[1], per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("param")
    ap.add_argument("values", nargs="+", type=float)
    ap.add_argument("--seeds", type=int, default=len(SEEDS))
    ap.add_argument("--n_deals", type=int, default=N_DEALS)
    ap.add_argument("--quick", action="store_true",
                    help="reference bots only, for a first look")
    args = ap.parse_args()

    seeds = SEEDS[: args.seeds]
    panel = opponents.REFERENCE if args.quick else opponents.PANEL
    mod = load_module()

    if not hasattr(mod, args.param):
        sys.exit(f"qs_bot has no constant named {args.param!r}")
    original = getattr(mod, args.param)

    names = [n for n, _ in panel]
    print(f"\n  SWEEP {args.param}   (shipped value {original})")
    print(f"  {len(seeds)} seeds x {args.n_deals * 2} deals, panel of {len(panel)}")
    header = "".join(f"{n[:9]:>10s}" for n in names)
    print(f"  {'value':>8s} {'MEAN':>7s} {'worst':>18s}   {header}")
    print(f"  {'-' * (36 + 10 * len(names))}")

    rows = []
    for v in args.values:
        setattr(mod, args.param, v)
        mean, wname, wval, per = score(mod, panel, seeds, args.n_deals)
        rows.append((v, mean, wname, wval))
        cells = "".join(f"{per[n]:>+10.2f}" for n in names)
        print(f"  {v:>8.2f} {mean:>+7.2f} {wname[:12]:>12s}{wval:>+6.2f}   {cells}")

    setattr(mod, args.param, original)
    best = max(rows, key=lambda r: r[1])
    safe = max(rows, key=lambda r: r[3])
    print(f"  {'-' * (36 + 10 * len(names))}")
    print(f"    best mean:  {args.param}={best[0]}  ({best[1]:+.2f})")
    print(f"    best floor: {args.param}={safe[0]}  (worst case {safe[3]:+.2f} vs {safe[2]})")


if __name__ == "__main__":
    main()
