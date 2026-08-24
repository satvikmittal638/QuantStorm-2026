"""experiment_patched_engine_t6.py — Updating Turn 6 decision model to the patched engine mechanics.
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


class Bot_PatchedT6(BASE_BOT_CLS):
    """Updated to reflect the true engine forced fill price: (bid + ask) // 2 + shift."""

    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote

        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        shift = self._shift(obs)
        sigma = math.sqrt(max(1, self._unseen(obs)))

        # -- Turn 6 (Final turn: Taker only) --
        if turn >= obs.n_turns:
            # Under the patched engine, countering is clamped to width = floor,
            # so the forced fill price is the midpoint + shift!
            floor = obs.final_cap
            # If we counter, the counter width is floor:
            mid = (bid + ask) // 2
            force_px = mid + shift

            # Calculate options with true fill price
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

            # When countering at Turn 6, we return a valid legal counter:
            c = max(bid, min(mid - floor // 2, ask - floor))
            options = (
                (opt_buy, "ACCEPT_BUY"),
                (opt_sell, "ACCEPT_SELL"),
                (opt_force, ("COUNTER", c, c + floor)),
            )
            return max(options, key=lambda o: o[0])[1]

        # -- Earlier turns (Turns 2 to 5) --
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
        w = max(obs.final_cap, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)


def test_patched_engine():
    print("=" * 80)
    print("TESTING PATCHED ENGINE ADAPTED BOT")
    print("=" * 80)
    cls = Bot_PatchedT6
    h2h = duel(cls, BASE_BOT_CLS, n_deals=60)
    print(f"Head-to-Head vs Current Base: {h2h.mean:+6.2f} +/- {h2h.stderr:4.2f}")
    
    honest = [duel(cls, opp, n_deals=60).mean for _, opp in PANEL]
    h_mean = statistics.fmean(honest)
    worst_idx = min(range(len(PANEL)), key=lambda i: honest[i])
    print(f"Honest Panel Mean           : {h_mean:+6.2f} | Worst: {PANEL[worst_idx][0]} ({honest[worst_idx]:+.2f})")
    
    board = [duel(cls, opp, n_deals=60).mean for _, opp in BB.BOARD]
    b_mean = statistics.fmean(board)
    worst_b_idx = min(range(len(BB.BOARD)), key=lambda i: board[i])
    print(f"Board Reconstructions       : {b_mean:+6.2f} | Worst: {BB.BOARD[worst_b_idx][0]} ({board[worst_b_idx]:+.2f})")

if __name__ == "__main__":
    test_patched_engine()
