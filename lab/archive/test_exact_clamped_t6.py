"""test_exact_clamped_t6.py — Exact clamped Turn 6 pricing under the updated engine.
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

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / 2.5066282746310002

def _option_val_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    if sigma <= 1e-4:
        return max(mu, -cap)
    z = (mu + cap) / sigma
    phi_z = _norm_pdf(z)
    Phi_z = _norm_cdf(z)
    return mu * Phi_z - cap * (1.0 - Phi_z) + sigma * phi_z

def _option_val_opponent_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    return -_option_val_substitute(-mu, sigma, cap)


class Bot_ExactT6(BASE_BOT_CLS):
    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote

        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        shift = self._shift(obs)
        sigma = math.sqrt(max(1, self._unseen(obs)))
        floor = obs.final_cap

        # -- Turn 6 (Final turn: Taker only) --
        if turn >= obs.n_turns:
            # Under the engine patch, countering (ask, ask) produces window [ask - floor, ask]
            # with midpoint = ask - floor // 2
            force_px = max((bid + ask) // 2, ask - floor // 2) + shift
            
            if "SUBSTITUTE" in obs.powers_mine:
                opt_buy = _option_val_substitute(v - ask, sigma)
                opt_sell = _option_val_substitute(bid - v, sigma)
                opt_force = _option_val_substitute(force_px - v, sigma) - fee
            elif "SUBSTITUTE" in obs.powers_theirs:
                opt_buy = _option_val_opponent_substitute(v - ask, sigma)
                opt_sell = _option_val_opponent_substitute(bid - v, sigma)
                opt_force = _option_val_opponent_substitute(force_px - v, sigma) - fee
            else:
                opt_buy = v - ask
                opt_sell = bid - v
                opt_force = force_px - v - fee

            options = (
                (opt_buy, "ACCEPT_BUY"),
                (opt_sell, "ACCEPT_SELL"),
                (opt_force, ("COUNTER", ask, ask)),
            )
            return max(options, key=lambda o: o[0])[1]

        # -- Turns 2 to 5 --
        raw_buy = v - ask
        raw_sell = bid - v
        if "SUBSTITUTE" in obs.powers_mine:
            ev_buy = _option_val_substitute(raw_buy, sigma)
            ev_sell = _option_val_substitute(raw_sell, sigma)
        elif "SUBSTITUTE" in obs.powers_theirs:
            ev_buy = _option_val_opponent_substitute(raw_buy, sigma)
            ev_sell = _option_val_opponent_substitute(raw_sell, sigma)
        else:
            ev_buy = raw_buy
            ev_sell = raw_sell

        bar = 0.8 * (ask - bid)
        if shift > 0 and not obs.is_maker:
            bar = max(bar, float(shift - 2.0))

        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"

        # Width cannot shrink below floor under the patched engine
        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

def run_test():
    print("Testing Exact Clamped T6 Engine...")
    cls = Bot_ExactT6
    h2h = duel(cls, BASE_BOT_CLS, n_deals=60)
    print(f"H2H vs Base: {h2h.mean:+6.2f} +/- {h2h.stderr:4.2f}")
    
    honest = [duel(cls, opp, n_deals=60).mean for _, opp in PANEL]
    print(f"Honest Mean: {statistics.fmean(honest):+6.2f}")
    
    board = [duel(cls, opp, n_deals=60).mean for _, opp in BB.BOARD]
    print(f"Board Mean : {statistics.fmean(board):+6.2f}")

if __name__ == "__main__":
    run_test()
