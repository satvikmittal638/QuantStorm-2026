"""experiment_game_mechanics.py — Implementing advanced game-mechanic strategies:
1. Exact SUBSTITUTE Convexity Option Valuation (Bachelier model on capped loss)
2. Shift Power Terminal Value Arbitrage (TRICK_ROOM / STEALTH_ROCK early-turn reservation price)
3. Opponent SUBSTITUTE Defense (penalizing trades when opponent has the free put)
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

def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def option_val_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    """Expected payoff of max(X, -cap) for X ~ N(mu, sigma^2).
    E[max(X, -K)] = mu * Phi((mu+K)/sigma) - K * (1 - Phi((mu+K)/sigma)) + sigma * phi((mu+K)/sigma)
    """
    if sigma <= 1e-4:
        return max(mu, -cap)
    z = (mu + cap) / sigma
    phi_z = norm_pdf(z)
    Phi_z = norm_cdf(z)
    return mu * Phi_z - cap * (1.0 - Phi_z) + sigma * phi_z

def option_val_opponent_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    """Our expected payoff when opponent holds SUBSTITUTE: min(X, +cap).
    Since X + Y = 0, our payoff is -max(-X, -cap).
    E[min(X, K)] = - E[max(-X, -K)]
    """
    return -option_val_substitute(-mu, sigma, cap)


class Bot_GameMechanics(BASE_BOT_CLS):
    """Integrates game-mechanic edges:
    1. SUBSTITUTE Option Math
    2. Shift-Power Reservation Price
    3. Optimal Shading (0.33)
    """
    SHADE_VAL = 0.33

    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote

        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        shift = self._shift(obs)
        sigma = math.sqrt(max(1, self._unseen(obs)))

        # -- Turn 6 (Last turn) --
        if turn >= obs.n_turns:
            force_px = ask + shift
            # If we hold SUBSTITUTE, calculate exact capped payoff
            if "SUBSTITUTE" in obs.powers_mine:
                opt_buy = option_val_substitute(v - ask, sigma)
                opt_sell = option_val_substitute(bid - v, sigma)
                opt_force = option_val_substitute(force_px - v, sigma) - fee
            elif "SUBSTITUTE" in obs.powers_theirs:
                opt_buy = option_val_opponent_substitute(v - ask, sigma)
                opt_sell = option_val_opponent_substitute(bid - v, sigma)
                opt_force = option_val_opponent_substitute(force_px - v, sigma) - fee
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

        # -- Earlier turns (Turns 2 to 5) --
        # 1. Option-adjusted edge
        raw_buy = v - ask
        raw_sell = bid - v
        if "SUBSTITUTE" in obs.powers_mine:
            ev_buy = option_val_substitute(raw_buy, sigma)
            ev_sell = option_val_substitute(raw_sell, sigma)
        elif "SUBSTITUTE" in obs.powers_theirs:
            ev_buy = option_val_opponent_substitute(raw_buy, sigma)
            ev_sell = option_val_opponent_substitute(raw_sell, sigma)
        else:
            ev_buy = raw_buy
            ev_sell = raw_sell

        # 2. Reservation threshold:
        # Base ride fraction of spread
        bar = 0.8 * (ask - bid)
        
        # If we hold positive shift (TRICK_ROOM / STEALTH_ROCK), we have an inherent
        # Turn 6 option worth (shift - 2.0), so we demand higher compensation to trade early!
        if shift > 0 and not obs.is_maker:
            bar = max(bar, float(shift - 2.0))

        # If we hold SUBSTITUTE, the option value ev_buy/ev_sell is already lifted by convexity,
        # so we compare ev_buy/ev_sell directly against bar
        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"

        # Shrink toward estimate
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}
        wanted = []
        for name in offered:
            v = self._power_value(obs, name)
            if v <= 0.0:
                continue
            amount = int(v / self.config.TE_SALVAGE * self.SHADE_VAL)
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

def test_mechanics_bot():
    print("=" * 80)
    print("TESTING GAME MECHANICS CONVEXITY BOT")
    print("=" * 80)
    cls = Bot_GameMechanics
    h2h = duel(cls, BASE_BOT_CLS, n_deals=60)
    print(f"Head-to-Head vs Base (v6): {h2h.mean:+6.2f} +/- {h2h.stderr:4.2f}")
    
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
    test_mechanics_bot()
