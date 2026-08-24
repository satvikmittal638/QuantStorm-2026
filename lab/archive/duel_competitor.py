"""duel_competitor.py — Direct match: Our Bot vs Competitor Reconstruction.
"""

from __future__ import annotations
import os, sys, statistics
from math import erf, exp, sqrt, comb

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps"))
LAB = os.path.dirname(os.path.abspath(__file__))
if REPO not in sys.path: sys.path.insert(0, REPO)
if LAB not in sys.path: sys.path.insert(0, LAB)

from engine import play_match
from game_config import GameConfig
from arena import load_bot, duel, SEEDS, N_DEALS, selfplay_control
from competitor_bot import CompetitorBot
import board_bots as BB
from opponents import PANEL, LIARS

CONFIG = GameConfig()
OUR_BOT_PATH = os.path.join(LAB, "bot", "qs_bot.py")
OurBotCls = load_bot(OUR_BOT_PATH, "our_bot")


def main():
    print()
    print("=" * 115)
    print("DIRECT HEAD-TO-HEAD: OUR BOT vs COMPETITOR RECONSTRUCTION (+168.69)")
    print(f"Config: {len(SEEDS)} seeds x 100 mirrored deals (1,000 total deals)")
    print("=" * 115)

    # 1. Direct Head-to-Head Duel
    res = duel(OurBotCls, CompetitorBot, SEEDS, 100)
    print(f"\n  HEAD-TO-HEAD RESULT:")
    print(f"    Our Bot (QS) vs Competitor: {res.mean:>+6.2f} +/- {res.stderr:4.2f} ticks/deal  ({res.mean * 20:>+6.1f} /match)")
    if res.mean > 0:
        print(f"    --> OUR BOT WINS by +{res.mean*20:.1f} PnL per match!")
    else:
        print(f"    --> Competitor leads by {res.mean*20:.1f} PnL per match!")

    # 2. Score on the 10 Board Reconstructions
    print("\n" + "-" * 115)
    print("BOARD RECONSTRUCTIONS BREAKDOWN:")
    print(f"{'Opponent':<28s} {'Our Bot (QS)':<18s} {'Competitor':<18s} {'Delta':<15s}")
    print("-" * 115)
    our_b_scores = []
    comp_b_scores = []
    for name, opp in BB.BOARD:
        s_our = duel(OurBotCls, opp, SEEDS, 40).mean * 20
        s_comp = duel(CompetitorBot, opp, SEEDS, 40).mean * 20
        our_b_scores.append(s_our)
        comp_b_scores.append(s_comp)
        delta = s_comp - s_our
        print(f"  {name:<26s} {s_our:>+12.1f}       {s_comp:>+12.1f}       {delta:>+10.1f}")

    print("-" * 115)
    print(f"  {'BOARD MEAN':<26s} {statistics.fmean(our_b_scores):>+12.1f}       {statistics.fmean(comp_b_scores):>+12.1f}       {statistics.fmean(comp_b_scores) - statistics.fmean(our_b_scores):>+10.1f}")

    # 3. Score on Liars
    our_l = statistics.fmean([duel(OurBotCls, opp, SEEDS, 40).mean * 20 for _, opp in LIARS])
    comp_l = statistics.fmean([duel(CompetitorBot, opp, SEEDS, 40).mean * 20 for _, opp in LIARS])
    print(f"\n  LIARS STRESS TEST:")
    print(f"    Our Bot vs Liars:    {our_l:>+6.1f} /match")
    print(f"    Competitor vs Liars: {comp_l:>+6.1f} /match")

    print("\n" + "=" * 115)


if __name__ == "__main__":
    main()
