"""experiment_adaptive_clean.py — Clean, First-Principles, Adaptive Bot.
Reduces constants: derives power valuations dynamically from game math.
Adapts to opponent bidding history and quote honesty.
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


class Bot_AdaptiveClean(BASE_BOT_CLS):
    """Adaptive Bot with dynamically derived valuations and opponent profiling."""
    
    def reset(self, seat: int, config, seed: int) -> None:
        self.seat = seat
        self.config = config
        self.reads: dict[int, float] = {}   # round -> opponent opening midpoint
        self.opp_quote_honest = True       # verified against foresight if possible
        self.opp_bids_observed = []        # opponent bid costs from auction log

    def _refresh(self, obs) -> None:
        # Check contracts
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                self.reads[c.round] = (c.open_bid + c.open_ask) / 2.0

        # Opponent honesty cross-check: if we had foresight and saw quote
        if obs.foresight and self.reads and obs.round in self.reads:
            f_sum = float(sum(obs.foresight))
            q_mid = self.reads[obs.round]
            # If quote midpoint contradicts foresight significantly, mark dishonest
            if abs(q_mid - f_sum) > 3.0:
                self.opp_quote_honest = False

    def _their_k(self, obs):
        parts = []
        n = len(obs.foresight)
        if n:
            parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))

        # Only trust quotes if not caught lying
        if self.reads and self.opp_quote_honest:
            r0 = max(self.reads)
            parts.append((self.reads[r0], 4.0 * (obs.round - r0) + 2.0))

        if not parts:
            return None

        for est, var in parts:
            if var <= 0.0:
                return est, 0.0

        wsum = sum(1.0 / var for _, var in parts)
        est = sum(e / var for e, var in parts) / wsum
        return est, 1.0 / wsum

    # -- Dynamic First-Principles Power Valuation (No Hardcoded 25-cell Matrix) --

    def _power_value(self, obs, name: str) -> float:
        cfg = self.config
        r = obs.round
        unseen = self._unseen(obs)
        sigma = math.sqrt(max(1, unseen))

        if name == "FORESIGHT":
            # 1. Information reduction: sqrt(m) coins of certainty
            m = min(16, 4 * r)
            info_val = 0.35 * math.sqrt(m)
            # 2. Obligation gain if Maker
            ob_gain = 0.0
            if obs.is_maker:
                unseen_new = max(0, unseen - m)
                try:
                    p_curr = cfg.straddle_prob(r, obs.final_cap, unseen=unseen)
                    p_new = cfg.straddle_prob(r, obs.final_cap, unseen=unseen_new)
                    ob_gain = cfg.MAKER_OBLIGATION * max(0.0, p_new - p_curr)
                except Exception:
                    ob_gain = 0.0
            return info_val + ob_gain

        elif name == "SUBSTITUTE":
            # Exact option convexity value: sigma * phi(2 / sigma)
            z = 2.0 / sigma
            convexity = sigma * _norm_pdf(z)
            return convexity

        elif name == "TRICK_ROOM":
            # Useful on forced fills (prob ~ 0.08)
            return 3.0 * 0.08

        return 0.0  # STEALTH_ROCK & TRANSFORM are zero EV for this bot

    # -- Adaptive Auction Bidding --

    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}

        # 1. Opponent bidding profile from tape
        opp_spent = self.config.TE_BUDGET - obs.te_theirs
        # If opponent has 0 TE left, snipe with 1 TE!
        if obs.te_theirs <= 0:
            return {offered[0]: 1}

        # 2. Base shade
        shade = 0.33
        
        # If opponent is provably passive across multiple rounds (spent <= 1 TE by R2+):
        if obs.round >= 2 and opp_spent <= 1:
            shade = 0.18  # Snipe cheaply against non-bidders to save TE salvage

        wanted = []
        for name in offered:
            v = self._power_value(obs, name)
            if v <= 0.0:
                continue
            amount = int(v / self.config.TE_SALVAGE * shade)
            # Never bid more than their balance + 1
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

def evaluate_adaptive_clean():
    print("=" * 80)
    print("EVALUATING ADAPTIVE CLEAN FIRST-PRINCIPLES BOT")
    print("=" * 80)
    cls = Bot_AdaptiveClean
    h2h = duel(cls, BASE_BOT_CLS, n_deals=60)
    print(f"Head-to-Head vs Base (v7): {h2h.mean:+6.2f} +/- {h2h.stderr:4.2f}")
    
    honest = [duel(cls, opp, n_deals=60).mean for _, opp in PANEL]
    h_mean = statistics.fmean(honest)
    worst_idx = min(range(len(PANEL)), key=lambda i: honest[i])
    print(f"Honest Panel Mean       : {h_mean:+6.2f} | Worst: {PANEL[worst_idx][0]} ({honest[worst_idx]:+.2f})")
    
    board = [duel(cls, opp, n_deals=60).mean for _, opp in BB.BOARD]
    b_mean = statistics.fmean(board)
    worst_b_idx = min(range(len(BB.BOARD)), key=lambda i: board[i])
    print(f"Board Reconstructions   : {b_mean:+6.2f} | Worst: {BB.BOARD[worst_b_idx][0]} ({board[worst_b_idx]:+.2f})")
    
    liars = [duel(cls, opp, n_deals=60).mean for _, opp in LIARS]
    l_mean = statistics.fmean(liars)
    worst_l_idx = min(range(len(LIARS)), key=lambda i: liars[i])
    print(f"Liar Stress Tests       : {l_mean:+6.2f} | Worst: {LIARS[worst_l_idx][0]} ({liars[worst_l_idx]:+.2f})")

if __name__ == "__main__":
    evaluate_adaptive_clean()
