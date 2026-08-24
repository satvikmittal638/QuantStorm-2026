"""test_joint_optimization.py — Testing joint parameter configurations.
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

def make_candidate(shade=0.33, ride_frac=0.8, read_noise=2.0):
    class Candidate(BASE_BOT_CLS):
        def respond(self, obs, quote, turn: int):
            self._refresh(obs)
            bid, ask = quote
            if turn == 2 and not obs.is_maker and obs.round not in self.reads:
                self.reads[obs.round] = (bid + ask) / 2.0

            v = self._est(obs)
            fee = self.config.FORCED_FILL_FEE

            if turn >= obs.n_turns:
                force_px = ask + self._shift(obs)
                options = (
                    (v - ask, "ACCEPT_BUY"),
                    (bid - v, "ACCEPT_SELL"),
                    (force_px - v - fee, ("COUNTER", ask, ask)),
                )
                return max(options, key=lambda o: o[0])[1]

            bar = ride_frac * (ask - bid)
            if "SUBSTITUTE" in obs.powers_mine:
                bar -= float(self.config.POWERS["SUBSTITUTE"]["magnitude"])

            edge_buy, edge_sell = v - ask, bid - v
            if edge_buy > bar and edge_buy >= edge_sell:
                return "ACCEPT_BUY"
            if edge_sell > bar:
                return "ACCEPT_SELL"

            w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
            c = max(bid, min(int(round(v)), ask - w))
            return ("COUNTER", c, c + w)

        def _their_k(self, obs):
            parts = []
            n = len(obs.foresight)
            if n:
                parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))
            if self.reads:
                r0 = max(self.reads)
                parts.append((self.reads[r0], 4.0 * (obs.round - r0) + read_noise))
            if not parts:
                return None
            for est, var in parts:
                if var <= 0.0:
                    return est, 0.0
            wsum = sum(1.0 / var for _, var in parts)
            est = sum(e / var for e, var in parts) / wsum
            return est, 1.0 / wsum

        def bid(self, obs, offered):
            budget = int(obs.te_mine)
            if not offered or budget <= 0:
                return {}
            wanted = []
            for name in offered:
                v = self._power_value(obs, name)
                if v <= 0.0:
                    continue
                amount = int(v / self.config.TE_SALVAGE * shade)
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

    return Candidate

def run_grid():
    configs = [
        ("Base v6 (0.30, 0.80, 2.0)", 0.30, 0.80, 2.0),
        ("Candidate A (0.33, 0.80, 2.0)", 0.33, 0.80, 2.0),
        ("Candidate B (0.35, 0.80, 2.0)", 0.35, 0.80, 2.0),
        ("Candidate C (0.33, 0.85, 2.0)", 0.33, 0.85, 2.0),
        ("Candidate D (0.33, 0.75, 2.0)", 0.33, 0.75, 2.0),
        ("Candidate E (0.33, 0.80, 2.5)", 0.33, 0.80, 2.5),
        ("Candidate F (0.33, 0.80, 1.5)", 0.33, 0.80, 1.5),
    ]

    print(f"{'Config':<32} | {'H2H vs Base':>15} | {'Honest':>7} | {'Worst':>18} | {'Board':>7} | {'Liars':>7}")
    print("-" * 95)
    for label, s, rf, rn in configs:
        cls = make_candidate(shade=s, ride_frac=rf, read_noise=rn)
        h2h = duel(cls, BASE_BOT_CLS, n_deals=60)
        honest = [duel(cls, opp, n_deals=60).mean for _, opp in PANEL]
        h_mean = statistics.fmean(honest)
        w_idx = min(range(len(PANEL)), key=lambda i: honest[i])
        w_str = f"{PANEL[w_idx][0]} ({honest[w_idx]:+.2f})"
        b_mean = statistics.fmean([duel(cls, opp, n_deals=60).mean for _, opp in BB.BOARD])
        l_mean = statistics.fmean([duel(cls, opp, n_deals=60).mean for _, opp in LIARS])
        print(f"{label:<32} | {h2h.mean:>+6.2f} +/- {h2h.stderr:4.2f} | {h_mean:>+7.2f} | {w_str:>18} | {b_mean:>+7.2f} | {l_mean:>+7.2f}")

if __name__ == "__main__":
    run_grid()
