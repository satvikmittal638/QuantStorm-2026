"""arena.py — measurement harness for Divided Oracle bots.

LOCAL ONLY. Never submitted.

Deals have per-deal sigma ~13 ticks, so single matches are noise. This runs a
fixed seed panel against a fixed opponent panel and reports mean +/- stderr.

The natural independent observation is a MIRROR PAIR (direct leg + mirror leg
on the same coin vector), not a single deal: the mirror exists to cancel the
luck of the deal, so the pair is what has low variance. Stderr is computed
across pairs and then reported per deal.

Usage:
    python lab/arena.py                          # panel report for the current bot
    python lab/arena.py --bot strategies/x.py    # panel report for one file
    python lab/arena.py --a strategies/x.py --b strategies/y.py    # single duel
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import statistics
import sys

REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps")
)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from engine import play_match          # noqa: E402
from game_config import GameConfig     # noqa: E402

# ── Panel definition ────────────────────────────────────────────────
# Fixed so every experiment is comparable. Changing these invalidates
# every number in LAB_NOTES.md, so don't, without saying so there.
SEEDS = (7, 11, 23, 41, 97)
N_DEALS = 60          # per phase; mirror doubles it -> 120 deals per seed
CONFIG = GameConfig()


PROJECT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

#: Our entry lives OUTSIDE the cloned repo on purpose. The organisers warn
#: that re-fetching the repo can overwrite or delete anything kept inside it,
#: and the repo has already been updated once mid-competition.
OUR_BOT = os.path.join(PROJECT, "lab", "bot", "qs_bot.py")


def resolve(path: str) -> str:
    """Find a bot file: absolute, then project-relative, then repo-relative."""
    for cand in (path, os.path.join(PROJECT, path), os.path.join(REPO, path)):
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    return os.path.join(REPO, path)   # let the caller fail with a real path


def load_bot(path: str, name: str | None = None):
    """Load a bot file and return its Bot class."""
    full = resolve(path)
    mod_name = name or os.path.splitext(os.path.basename(full))[0]
    spec = importlib.util.spec_from_file_location(mod_name, full)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Bot


class Result:
    """One A-vs-B measurement over the seed panel."""

    def __init__(self, per_pair: list[float], warnings: list[str],
                 violations: int, clamps: int, times: list[float]):
        self.per_pair = per_pair
        self.warnings = warnings
        self.violations = violations
        self.clamps = clamps
        self.times = times

    @property
    def mean(self) -> float:
        """Mean ticks per DEAL for seat A (a pair is two deals)."""
        return statistics.fmean(self.per_pair) / 2 if self.per_pair else 0.0

    @property
    def stderr(self) -> float:
        n = len(self.per_pair)
        if n < 2:
            return 0.0
        return statistics.stdev(self.per_pair) / (n ** 0.5) / 2

    @property
    def avg_ms(self) -> float:
        return statistics.fmean(self.times) if self.times else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.times) if self.times else 0.0

    def __str__(self) -> str:
        return f"{self.mean:+6.2f} +/- {self.stderr:4.2f}"


def duel(bot_a, bot_b, seeds=SEEDS, n_deals=N_DEALS, config=CONFIG) -> Result:
    """Play bot_a against bot_b across the seed panel. Positive = A wins."""
    pairs: list[float] = []
    warnings: list[str] = []
    times: list[float] = []
    violations = clamps = 0

    for sd in seeds:
        m = play_match(bot_a, bot_b, config, seed=sd, n_deals=n_deals, mirror=True)
        # Deals come back interleaved: direct, mirror, direct, mirror...
        pnl = [d.pnl[0] for d in m.deals]
        pairs.extend(pnl[i] + pnl[i + 1] for i in range(0, len(pnl) - 1, 2))
        warnings.extend(m.bot_a_warnings)
        times.extend(m.bot_a_times)
        violations += m.bot_a_violations
        clamps += m.bot_a_clamps

    return Result(pairs, warnings, violations, clamps, times)


def report(bot, panel, label="bot", seeds=SEEDS, n_deals=N_DEALS) -> float:
    """Score `bot` against every opponent in `panel`. Returns the mean."""
    print(f"\n  {label}  ({len(seeds)} seeds x {n_deals * 2} deals each)")
    print(f"  {'-' * 62}")
    means = []
    worst = None
    agg_warn: list[str] = []
    agg_viol = agg_clamp = 0
    agg_max_ms = 0.0
    for name, opp in panel:
        r = duel(bot, opp, seeds, n_deals)
        means.append(r.mean)
        if worst is None or r.mean < worst[1]:
            worst = (name, r.mean)
        agg_warn.extend(r.warnings)
        agg_viol += r.violations
        agg_clamp += r.clamps
        agg_max_ms = max(agg_max_ms, r.max_ms)
        flag = "  <-- LOSING" if r.mean < 0 else ""
        print(f"    vs {name:<22s} {r}{flag}")
    mean = statistics.fmean(means)
    print(f"  {'-' * 62}")
    print(f"    {'MEAN':<25s} {mean:+6.2f}      worst: {worst[0]} {worst[1]:+.2f}")
    if agg_viol or agg_clamp or agg_warn:
        print(f"    health: {agg_viol} violations, {agg_clamp} clamps, "
              f"{len(agg_warn)} warnings, max call {agg_max_ms:.2f}ms")
        for w in agg_warn[:5]:
            print(f"      ! {w}")
    else:
        print(f"    health: clean (max call {agg_max_ms:.2f}ms)")
    return mean


def selfplay_control(bot) -> bool:
    """A bot against itself over mirrored deals must net exactly 0.0.

    Catches seat-dependent bugs, which are otherwise nearly invisible.
    """
    m = play_match(bot, bot, CONFIG, seed=7, n_deals=20, mirror=True)
    ok = abs(m.pnl[0]) < 1e-9
    print(f"  self-play control: {m.pnl[0]:+.9f}  {'OK' if ok else 'FAIL — seat-dependent bug'}")
    return ok


def default_panel():
    from opponents import PANEL
    return PANEL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", nargs="?", const=OUR_BOT, default=None,
                    help="bot file to score against the panel (default: our entry)")
    ap.add_argument("--a", default=None)
    ap.add_argument("--b", default=None)
    ap.add_argument("--seeds", type=int, default=len(SEEDS))
    ap.add_argument("--n_deals", type=int, default=N_DEALS)
    args = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    seeds = SEEDS[: args.seeds]

    if args.a and args.b:
        A, B = load_bot(args.a, "botA"), load_bot(args.b, "botB")
        r = duel(A, B, seeds, args.n_deals)
        print(f"\n  {args.a} vs {args.b}: {r}  ticks/deal")
        return

    if args.bot:
        bot = load_bot(args.bot, "subject")
        selfplay_control(bot)
        report(bot, default_panel(), label=args.bot, seeds=seeds, n_deals=args.n_deals)
        return

    # No args: print the baseline table, which is the harness's own sanity check.
    from opponents import REFERENCE
    print("\n  BASELINE CHECK (should reproduce LAB_NOTES section 2)")
    print(f"  {'-' * 62}")
    names = dict(REFERENCE)
    for a, b, expected in (("adaptive_bidder", "rational", 2.61),
                           ("adaptive_bidder", "naive_ev", 5.30),
                           ("rational", "naive_ev", 1.17)):
        r = duel(names[a], names[b], seeds, args.n_deals)
        print(f"    {a:<18s} vs {b:<12s} {r}   (research run: {expected:+.2f})")


if __name__ == "__main__":
    main()
