"""test_shade_fine.py — Fine comparison of SHADE candidates:
0.30 (current v6), 0.33, 0.35, 0.37, 0.40
"""

from __future__ import annotations

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

def make_bot(shade_val):
    class Bot_Shade(BASE_BOT_CLS):
        def bid(self, obs, offered):
            budget = int(obs.te_mine)
            if not offered or budget <= 0:
                return {}
            wanted = []
            for name in offered:
                v = self._power_value(obs, name)
                if v <= 0.0:
                    continue
                amount = int(v / self.config.TE_SALVAGE * shade_val)
                amount = min(amount, int(obs.te_theirs) + 1)
                if amount > 0:
                    wanted.append((v, name, amount))
            out = {}
            for _, name, amount in sorted(wanted, key=lambda t: -t[0]):
                take = min(amount, budget)
                if take <= 0:
                    break
                out[name] = take
                budget -= take
            return out
    return Bot_Shade

def liar(mode):
    class L(_Base):
        name = "liar_" + mode
        width_mode = "floor"
        bid_mode = "value"
        use_t6 = True
        def quote(self, obs):
            self._refresh(obs)
            k = obs.k_mine + (sum(obs.foresight) if obs.foresight else 0)
            v = {"compress": round(k * 0.4), "invert": round(-k), "zero": 0}[mode]
            w = obs.final_cap
            return (v - w // 2, v + (w - w // 2))
    return L

LIARS = [("liar_compress", liar("compress")), ("liar_invert", liar("invert")), ("liar_zero", liar("zero"))]

def evaluate_all():
    shades = [0.30, 0.33, 0.35, 0.37, 0.40]
    print(f"{'SHADE':>6} | {'H2H vs Base':>15} | {'Honest Mean':>12} | {'Worst Honest':>20} | {'Board Mean':>11} | {'Liars Mean':>11}")
    print("-" * 85)
    for s in shades:
        cls = make_bot(s)
        h2h = duel(cls, BASE_BOT_CLS, n_deals=60)
        
        honest = [duel(cls, opp, n_deals=60).mean for _, opp in PANEL]
        h_mean = statistics.fmean(honest)
        worst_idx = min(range(len(PANEL)), key=lambda i: honest[i])
        worst_str = f"{PANEL[worst_idx][0]} ({honest[worst_idx]:+.2f})"
        
        board = [duel(cls, opp, n_deals=60).mean for _, opp in BB.BOARD]
        b_mean = statistics.fmean(board)
        
        liars = [duel(cls, opp, n_deals=60).mean for _, opp in LIARS]
        l_mean = statistics.fmean(liars)
        
        print(f"{s:>6.2f} | {h2h.mean:>+6.2f} +/- {h2h.stderr:4.2f} | {h_mean:>+12.2f} | {worst_str:>20} | {b_mean:>+11.2f} | {l_mean:>+11.2f}")

if __name__ == "__main__":
    evaluate_all()
