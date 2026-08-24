"""scoreboard.py -- the full internal score for a candidate bot.

LOCAL ONLY. Never submitted.

Four opponent groups, because each answers a different question:

  HONEST    the reference bots + honest archetypes. The best-validated proxy
            for "a competent opponent that quotes truthfully". Most of the
            real field is probably here.
  BOARD     reconstructions of the ten hidden leaderboard bots. WEAK EVIDENCE:
            rank concordance with the real board is 47%, no better than
            chance, and shipping on their say-so already cost us points once.
            Reported for information, never tuned against.
  LIARS     opponents that distort their opening quote. Stress tests for the
            one structural vulnerability we know we have.
  VERSIONS  our own past releases. A candidate that cannot beat the build it
            replaces is not an improvement, and self-play against an ancestor
            is the sharpest regression test available -- the mirror makes an
            identical bot score exactly 0.00, so every tick is signal.

Scores print in ticks/deal AND in board units (x20 = per match of 20 deals),
so they can be compared against the real leaderboard number directly.

    python3 lab/scoreboard.py                       # score the working bot
    python3 lab/scoreboard.py --bot lab/versions/v1_board_84.83.py
    python3 lab/scoreboard.py --quick               # honest + versions only
"""

from __future__ import annotations

import argparse
import glob
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from arena import duel, load_bot, OUR_BOT, SEEDS, N_DEALS, selfplay_control  # noqa: E402
import opponents as OP      # noqa: E402
import board_bots as BB     # noqa: E402

VERSIONS_DIR = os.path.join(HERE, "versions")


def liar(mode):
    """Opponents that lie with the opening quote but price on the truth."""
    class L(OP._Base):
        name = "liar_" + mode
        width_mode = "floor"
        bid_mode = "value"
        use_t6 = True

        def quote(self, obs):
            self._refresh(obs)
            k = obs.k_mine + (sum(obs.foresight) if obs.foresight else 0)
            v = {"compress": round(k * 0.4),
                 "invert": round(-k),
                 "zero": 0}[mode]
            w = obs.final_cap
            return (v - w // 2, v + (w - w // 2))
    return L


LIARS = [("liar_" + m, liar(m)) for m in ("compress", "invert", "zero")]


def version_panel():
    """Every archived release, oldest first."""
    out = []
    for path in sorted(glob.glob(os.path.join(VERSIONS_DIR, "v*.py"))):
        tag = os.path.splitext(os.path.basename(path))[0]
        try:
            out.append((tag, load_bot(path, "ver_" + tag.replace(".", "_"))))
        except Exception as e:
            print(f"  !! could not load {tag}: {e}")
    return out


def group(bot, panel, label, seeds, n_deals, note=""):
    if not panel:
        return None
    print(f"\n  {label}{note}")
    print(f"  {'-' * 64}")
    vals = []
    for name, opp in panel:
        r = duel(bot, opp, seeds, n_deals)
        vals.append(r.mean)
        flag = "  <-- LOSING" if r.mean < 0 else ""
        print(f"    vs {name:<26s} {r.mean:+7.2f} +/- {r.stderr:4.2f}"
              f"   ({r.mean * 20:+7.1f} /match){flag}")
    m = statistics.fmean(vals)
    worst = min(zip([n for n, _ in panel], vals), key=lambda t: t[1])
    print(f"    {'GROUP MEAN':<29s} {m:+7.2f}          ({m * 20:+7.1f} /match)"
          f"   worst: {worst[0]} {worst[1]:+.2f}")
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default=OUR_BOT)
    ap.add_argument("--seeds", type=int, default=len(SEEDS))
    ap.add_argument("--n_deals", type=int, default=N_DEALS)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    seeds = SEEDS[: args.seeds]
    bot = load_bot(args.bot, "subject")

    print(f"\n  SCOREBOARD: {os.path.basename(args.bot)}")
    print(f"  {len(seeds)} seeds x {args.n_deals * 2} mirrored deals per matchup")
    print("  " + "=" * 64)
    selfplay_control(bot)

    honest = group(bot, OP.PANEL, "HONEST PANEL", seeds, args.n_deals,
                   "   (best-validated proxy)")
    versions = group(bot, version_panel(), "PAST VERSIONS", seeds, args.n_deals,
                     "   (regression: 0.00 == identical)")
    board = liars = None
    if not args.quick:
        board = group(bot, BB.BOARD, "BOARD RECONSTRUCTIONS", seeds, args.n_deals,
                      "   (WEAK EVIDENCE -- 47% concordance)")
        liars = group(bot, LIARS, "LIARS", seeds, args.n_deals,
                      "   (stress test, not a tuning target)")

    print("\n  " + "=" * 64)
    print("  SUMMARY")
    for lbl, v in (("honest", honest), ("versions", versions),
                   ("board-recon", board), ("liars", liars)):
        if v is not None:
            print(f"    {lbl:<14s} {v:+7.2f} ticks/deal   ({v * 20:+7.1f} /match)")
    print("\n  Real board reference: v1 scored +84.83/match. Only the real")
    print("  leaderboard validates a change; local deltas under ~0.5")
    print("  ticks/deal have already proven unshippable.")


if __name__ == "__main__":
    main()
