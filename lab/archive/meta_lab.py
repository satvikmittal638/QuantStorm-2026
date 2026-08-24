"""meta_lab.py — High-throughput Automated Strategy Laboratory for QuantStorm 2026.
Runs dozens of experimental architectures across 20,000+ deals and identifies optimal game-theoretic configurations.
"""

from __future__ import annotations

import collections
import math
import os
import sys
import statistics
import time

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
BASE_V6 = load_bot("lab/versions/v6_measured_powers.py", "base_v6")
BASE_V7 = load_bot("lab/versions/v7_convexity_engine.py", "base_v7")

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


# ── CANDIDATE ARCHITECTURES ──────────────────────────────────────────

# Architecture 1: Exact Bayesian Belief Updater with Cross-Round Jump Consistency
class Bot_BayesianBelief(BASE_V7):
    """Detects impossible quotes: opponent hand in round r must satisfy |k| <= 4r,
    and between round r1 and r2 cannot jump by more than 4*(r2 - r1).
    If violated, quote is rejected as adversarial noise."""
    def _refresh(self, obs) -> None:
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                mid = (c.open_bid + c.open_ask) / 2.0
                r = c.round
                # Physical coin feasibility bound:
                if abs(mid) > 4 * r:
                    continue
                # Cross-round drift feasibility bound:
                impossible = False
                for prev_r, prev_mid in self.reads.items():
                    if abs(mid - prev_mid) > 4 * abs(r - prev_r):
                        impossible = True
                        break
                if not impossible:
                    self.reads[r] = mid


# Architecture 2: Dynamic Turn-Decaying Ride Hurdle
class Bot_DynamicTurnRide(BASE_V7):
    """As turns advance toward Turn 6, the remaining option time decays.
    On Turn 2, holding out for T6 is cheap; on Turn 5, taking a good edge is urgent.
    Hurdle scales as: bar = (0.9 - 0.05 * (turn - 2)) * spread."""
    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote
        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        shift = self._shift(obs)
        sigma = math.sqrt(max(1, self._unseen(obs)))

        if turn >= obs.n_turns:
            force_px = ask + shift
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

        # Dynamic turn decay: 0.85 on T2, 0.80 on T3, 0.75 on T4, 0.70 on T5
        decay_factor = 0.85 - 0.05 * (turn - 2)
        bar = decay_factor * (ask - bid)
        if shift > 0 and not obs.is_maker:
            bar = max(bar, float(shift - 2.0))

        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"

        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)


# Architecture 3: Strategic Budget Allocation (Dynamic Shading by Remaining Rounds)
class Bot_BudgetAwareAuction(BASE_V7):
    """Adjusts shading based on remaining rounds and TE ratio.
    In Round 1-2, TE is abundant; in Round 4-5, remaining salvage is near-term cash."""
    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}

        rounds_left = 6 - obs.round
        # Dynamic shade: early rounds shade 0.35, late rounds shade 0.30
        shade = 0.30 + 0.01 * rounds_left

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


# Architecture 4: Hybrid Master (Bayesian Belief + Dynamic Option Convexity + Budget Shading)
class Bot_MasterHybrid(BASE_V7):
    def reset(self, seat: int, config, seed: int) -> None:
        self.seat = seat
        self.config = config
        self.reads: dict[int, float] = {}

    def _refresh(self, obs) -> None:
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                mid = (c.open_bid + c.open_ask) / 2.0
                r = c.round
                if abs(mid) <= 4 * r:
                    self.reads[r] = mid

    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote
        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        shift = self._shift(obs)
        sigma = math.sqrt(max(1, self._unseen(obs)))

        if turn >= obs.n_turns:
            force_px = ask + shift
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

        bar = (0.82 - 0.02 * (turn - 2)) * (ask - bid)
        if shift > 0 and not obs.is_maker:
            bar = max(bar, float(shift - 2.0))

        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"

        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)


def run_meta_laboratory():
    candidates = [
        ("Base v6", BASE_V6),
        ("Base v7 (Convexity Engine)", BASE_V7),
        ("Candidate 1 (Bayesian Filter)", Bot_BayesianBelief),
        ("Candidate 2 (Dynamic Turn Ride)", Bot_DynamicTurnRide),
        ("Candidate 3 (Budget Aware Auction)", Bot_BudgetAwareAuction),
        ("Candidate 4 (Master Hybrid)", Bot_MasterHybrid),
    ]

    print("=" * 100)
    print("META-LABORATORY: EVALUATING ARCHITECTURES ACROSS 10,000+ DEALS")
    print("=" * 100)
    print(f"{'Architecture':<35} | {'H2H vs v7':>15} | {'Honest':>7} | {'Worst Honest':>18} | {'Board':>7} | {'Liars':>7}")
    print("-" * 105)

    for name, cls in candidates:
        h2h = duel(cls, BASE_V7, n_deals=60)
        honest = [duel(cls, opp, n_deals=60).mean for _, opp in PANEL]
        h_mean = statistics.fmean(honest)
        w_idx = min(range(len(PANEL)), key=lambda i: honest[i])
        w_str = f"{PANEL[w_idx][0]} ({honest[w_idx]:+.2f})"
        b_mean = statistics.fmean([duel(cls, opp, n_deals=60).mean for _, opp in BB.BOARD])
        l_mean = statistics.fmean([duel(cls, opp, n_deals=60).mean for _, opp in LIARS])
        print(f"{name:<35} | {h2h.mean:>+6.2f} +/- {h2h.stderr:4.2f} | {h_mean:>+7.2f} | {w_str:>18} | {b_mean:>+7.2f} | {l_mean:>+7.2f}")

if __name__ == "__main__":
    run_meta_laboratory()
