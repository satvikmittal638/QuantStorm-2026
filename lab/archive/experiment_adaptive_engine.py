"""experiment_adaptive_engine.py — Comprehensive Bayesian Profiler, Inventory-Skewed MM, and Dynamic Auction Sizing.
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


class Bot_AdaptiveFull(BASE_BOT_CLS):
    """Integrates:
    1. Online Bayesian Opponent Profiler (Honesty, Drift, Passive, Aggro)
    2. Inventory-Skewed Quote Engine
    3. Dynamic Game-Theoretic Auction Engine
    """

    def reset(self, seat: int, config, seed: int) -> None:
        self.seat = seat
        self.config = config
        self.reads: dict[int, float] = {}
        
        # Bayesian Belief State:
        self.p_honest = 0.80   # Probability opponent quotes reflect true sum
        self.p_passive = 0.20  # Probability opponent is a non-bidder / sniper
        self.p_forcer = 0.30   # Probability opponent forces on Turn 6

    def _refresh(self, obs) -> None:
        # Check auction tape to update bidding profile
        if obs.auction_log:
            opp_wins = [e for e in obs.auction_log if e["seat"] != self.seat]
            if opp_wins:
                last_win = opp_wins[-1]
                if last_win["cost"] >= 5:
                    self.p_passive *= 0.2
                    self.p_forcer = min(1.0, self.p_forcer + 0.3)
                elif last_win["cost"] == 0:
                    self.p_passive = min(1.0, self.p_passive + 0.3)

        # Process contract opening quotes
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                mid = (c.open_bid + c.open_ask) / 2.0
                r = c.round
                
                # Check physical coin feasibility: |mid| <= 4 * r
                if abs(mid) > 4 * r + 1.0:
                    self.p_honest *= 0.1  # Blatant lie
                
                # Check cross-round drift feasibility
                for prev_r, prev_mid in self.reads.items():
                    max_possible_delta = 4 * abs(r - prev_r)
                    if abs(mid - prev_mid) > max_possible_delta + 1.0:
                        self.p_honest *= 0.1  # Impossible jump

                self.reads[r] = mid

        # Cross-check against FORESIGHT if available
        if obs.foresight and self.reads and obs.round in self.reads:
            f_sum = float(sum(obs.foresight))
            q_mid = self.reads[obs.round]
            if abs(q_mid - f_sum) > 2.5:
                self.p_honest = 0.0  # Confirmed liar
            else:
                self.p_honest = min(1.0, self.p_honest + 0.2)

    def _their_k(self, obs):
        parts = []
        n = len(obs.foresight)
        if n:
            parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))

        # Only trust quotes if p_honest is sufficiently high
        if self.reads and self.p_honest > 0.3:
            r0 = max(self.reads)
            # Variance inflates as honesty drops
            noise = 2.0 / self.p_honest
            parts.append((self.reads[r0], 4.0 * (obs.round - r0) + noise))

        if not parts:
            return None

        for est, var in parts:
            if var <= 0.0:
                return est, 0.0

        wsum = sum(1.0 / var for _, var in parts)
        est = sum(e / var for e, var in parts) / wsum
        return est, 1.0 / wsum

    # ── Inventory Skewing in Market Making ──────────────────────────

    def quote(self, obs):
        self._refresh(obs)
        cfg = self.config
        v = int(round(self._est(obs)))
        r, floor, cap = obs.round, obs.final_cap, obs.spread_cap
        unseen = self._unseen(obs)

        # Inventory delta: our TE relative to opponent
        te_inventory_cushion = obs.te_mine - obs.te_theirs

        best_ev, best_lo, best_w = None, v - floor // 2, floor
        for w in range(floor, cap + 1):
            lo = v - w // 2
            if lo % 2:
                lo += 1
            try:
                priced = cfg.straddle_prob(r, w)
            except Exception:
                continue
            true_p = self._cover(unseen, lo - v, lo - v + w)
            ev = (cfg.MAKER_OBLIGATION * (true_p - priced)
                  - cfg.WIDTH_PREMIUM * (w - floor))

            # Inventory skew: if in TE deficit, tighten spreads to avoid obligation variance
            if te_inventory_cushion < 0:
                ev -= 0.02 * abs(te_inventory_cushion) * (w - floor)

            if best_ev is None or ev > best_ev:
                best_ev, best_lo, best_w = ev, lo, w

        return (best_lo, best_lo + best_w)

    # ── Adaptive Negotiation & Ride Hurdle ──────────────────────────

    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote

        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0
            if abs((bid + ask) / 2.0) > 4 * obs.round + 1.0:
                self.p_honest *= 0.1

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        shift = self._shift(obs)
        sigma = math.sqrt(max(1, self._unseen(obs)))
        floor = obs.final_cap

        # -- Turn 6 (Final turn: Taker only) --
        if turn >= obs.n_turns:
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

        # Dynamic ride hurdle
        ride = 0.80
        if self.p_forcer > 0.5:
            ride = 0.85  # Ride harder against stallers
        bar = ride * (ask - bid)
        if shift > 0 and not obs.is_maker:
            bar = max(bar, float(shift - 2.0))

        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"

        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

    # ── Dynamic Auction Bidding (CFR / Game-Theoretic Sizing) ────────

    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}

        # If opponent has 0 TE, snipe with 1 TE!
        if obs.te_theirs <= 0:
            return {offered[0]: 1}

        # Dynamic shade based on opponent bidding profile
        if self.p_passive > 0.6:
            shade = 0.20  # Snipe cheaply against non-bidders
        elif self.p_forcer > 0.6:
            shade = 0.35  # Contest powers against aggressive players
        else:
            shade = 0.33

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

def test_full():
    print("=" * 80)
    print("TESTING FULL ADAPTIVE SYSTEM")
    print("=" * 80)
    cls = Bot_AdaptiveFull
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
    test_full()
