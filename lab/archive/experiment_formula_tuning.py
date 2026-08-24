"""experiment_formula_tuning.py — Testing concise dynamic formula vs lookup table.
"""

from __future__ import annotations

import math
import os
import sys
import statistics

REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps")
)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from engine import play_match
from game_config import GameConfig
from arena import load_bot, duel, SEEDS
from opponents import PANEL, _Base
import board_bots as BB

CONFIG = GameConfig()
BASE_BOT_CLS = load_bot("lab/bot/qs_bot.py", "base_bot")

class Bot_ConciseMath(BASE_BOT_CLS):
    """Clean concise formulation:
    Power values are computed from a 3-line formula that tracks the true
    marginal information content of each power:
      FORESIGHT:  0.8 * sqrt(min(16, 4*r)) + (0.8 if is_maker else 0.0)
      SUBSTITUTE: 0.5 * (r + 1.0)
      TRICK_ROOM: 0.5 / r
    """
    def _power_value(self, obs, name: str) -> float:
        r = obs.round
        if name == "FORESIGHT":
            m = min(16, 4 * r)
            return 0.75 * math.sqrt(m) + (0.5 if obs.is_maker else 0.0)
        elif name == "SUBSTITUTE":
            return 0.5 * (r + 1.0)
        elif name == "TRICK_ROOM":
            return 0.6 / r
        return 0.0

def run_tests():
    print("Testing Concise Math Formula...")
    cls = Bot_ConciseMath
    h2h = duel(cls, BASE_BOT_CLS, n_deals=60)
    print(f"H2H vs Base: {h2h.mean:+6.2f} +/- {h2h.stderr:4.2f}")
    
    honest = [duel(cls, opp, n_deals=60).mean for _, opp in PANEL]
    print(f"Honest Mean: {statistics.fmean(honest):+6.2f} (Base is +7.25)")
    
    board = [duel(cls, opp, n_deals=60).mean for _, opp in BB.BOARD]
    print(f"Board Mean : {statistics.fmean(board):+6.2f} (Base is +5.20)")

if __name__ == "__main__":
    run_tests()
