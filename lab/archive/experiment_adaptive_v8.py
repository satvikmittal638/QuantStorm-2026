"""experiment_adaptive_v8.py — Testing v8: Concise First-Principles Math + Online Opponent Adaptation.
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


class Bot_V8_Adaptive(BASE_BOT_CLS):
    """v8: Concise First-Principles Math + Online Opponent Adaptation.
    - Zero hardcoded power matrices.
    - Dynamic opponent quote truth verification.
    - Adaptive budget capping against opponent TE balance.
    """

    def reset(self, seat: int, config, seed: int) -> None:
        self.seat = seat
        self.config = config
        self.reads: dict[int, float] = {}
        self.opp_honest: bool = True  # verified online via FORESIGHT cross-validation

    def _refresh(self, obs) -> None:
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                self.reads[c.round] = (c.open_bid + c.open_ask) / 2.0

        # Online liar detector: if FORESIGHT reveals their exact coins, check their quote
        if obs.foresight and self.reads and obs.round in self.reads:
            f_sum = float(sum(obs.foresight))
            q_mid = self.reads[obs.round]
            if abs(q_mid - f_sum) > 2.5:
                self.opp_honest = False

    def _their_k(self, obs):
        parts = []
        n = len(obs.foresight)
        if n:
            parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))

        # Only incorporate quote reads if the opponent hasn't been caught distorting
        if self.reads and self.opp_honest:
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

    # -- Concise First-Principles Power Valuation --
    def _power_value(self, obs, name: str) -> float:
        r = obs.round
        if name == "FORESIGHT":
            # Information variance reduction + Maker obligation edge
            m = min(16, 4 * r)
            return 0.75 * math.sqrt(m) + (0.5 if obs.is_maker else 0.0)
        elif name == "SUBSTITUTE":
            # Rising option convexity through deal
            return 0.5 * (r + 1.0)
        elif name == "TRICK_ROOM":
            # Value decaying with rounds
            return 0.6 / r
        return 0.0

    # -- Adaptive Auction Bidding --
    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}

        # If opponent has no TE, 1 TE guarantees the win
        if obs.te_theirs <= 0:
            return {offered[0]: 1}

        wanted = []
        for name in offered:
            v = self._power_value(obs, name)
            if v <= 0.0:
                continue
            amount = int(v / self.config.TE_SALVAGE * 0.33)
            # Never bid more than needed to beat opponent's entire balance
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

def test_v8():
    print("=" * 80)
    print("TESTING V8 ADAPTIVE CONCISE ENGINE")
    print("=" * 80)
    cls = Bot_V8_Adaptive
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
    test_v8()
