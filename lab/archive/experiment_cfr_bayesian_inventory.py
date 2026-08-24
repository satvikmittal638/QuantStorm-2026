"""experiment_cfr_bayesian_inventory.py — Full Implementation of:
1. Analytical Equilibrium Bidding (CFR/Nash Auction Engine)
2. Inventory-Skewed Market Making (Avellaneda-Stoikov TE inventory adaptation)
3. Online Multi-Hypothesis Bayesian Opponent Profiler
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


class Bot_AdaptiveMaster(BASE_BOT_CLS):
    """Integrates:
    - Bayesian Opponent Classification (Honest, Liar, Passive, Aggro)
    - Inventory-Aware Quoting (TE cushion adaptation)
    - Equilibrium Auction Sizing
    """

    def reset(self, seat: int, config, seed: int) -> None:
        self.seat = seat
        self.config = config
        self.rng = None
        self.reads: dict[int, float] = {}

        # Bayesian Posterior over 4 Archetypes:
        # [0]: Honest (prices on k, quotes normally)
        # [1]: Liar / Compressor (distorts quote midpoint)
        # [2]: Passive Non-Bidder (0-1 TE bids)
        # [3]: Aggressive Forcer / Heavy Bidder
        self.posterior = [0.45, 0.15, 0.20, 0.20]

    # ── Bayesian Belief Updater ─────────────────────────────────────

    def _update_beliefs(self, obs) -> None:
        # 1. Update from Auction Tape
        # Check if opponent won any power and how much was paid
        if obs.auction_log:
            last_entry = obs.auction_log[-1]
            if last_entry["seat"] != self.seat:
                cost = last_entry["cost"]
                if cost >= 6:
                    # High bid: strongly indicates Aggressive Bidder
                    self.posterior[3] *= 2.5
                    self.posterior[2] *= 0.1
                elif cost == 0:
                    self.posterior[2] *= 1.5
                    self.posterior[3] *= 0.5

        # 2. Update from Quote Honesty (Cross-checked against FORESIGHT)
        if obs.foresight and self.reads and obs.round in self.reads:
            f_sum = float(sum(obs.foresight))
            q_mid = self.reads[obs.round]
            diff = abs(q_mid - f_sum)
            if diff > 2.5:
                # Strong evidence of liar
                self.posterior[1] *= 5.0
                self.posterior[0] *= 0.1
            else:
                self.posterior[0] *= 2.0
                self.posterior[1] *= 0.2

        # Normalize posterior
        s = sum(self.posterior)
        if s > 0:
            self.posterior = [p / s for p in self.posterior]

    def _refresh(self, obs) -> None:
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                self.reads[c.round] = (c.open_bid + c.open_ask) / 2.0
        self._update_beliefs(obs)

    def _their_k(self, obs):
        parts = []
        n = len(obs.foresight)
        if n:
            parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))

        # Trust in quotes is scaled dynamically by P(Honest)
        p_honest = self.posterior[0]
        p_liar = self.posterior[1]
        
        # If liar probability is high, drop quote read completely
        if self.reads and p_liar < 0.6:
            r0 = max(self.reads)
            # Noise scales inversely with p_honest
            read_noise = 2.0 / max(0.2, p_honest)
            parts.append((self.reads[r0], 4.0 * (obs.round - r0) + read_noise))

        if not parts:
            return None

        for est, var in parts:
            if var <= 0.0:
                return est, 0.0

        wsum = sum(1.0 / var for _, var in parts)
        est = sum(e / var for e, var in parts) / wsum
        return est, 1.0 / wsum

    # ── Inventory-Skewed Quote Solving ──────────────────────────────

    def quote(self, obs):
        self._refresh(obs)
        cfg = self.config
        v = int(round(self._est(obs)))
        r, floor, cap = obs.round, obs.final_cap, obs.spread_cap
        unseen = self._unseen(obs)

        # Inventory advantage (TE cushion)
        te_delta = obs.te_mine - obs.te_theirs
        
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
            
            # Base obligation EV
            ev = (cfg.MAKER_OBLIGATION * (true_p - priced)
                  - cfg.WIDTH_PREMIUM * (w - floor))
            
            # Inventory skew: if TE is in deficit (te_delta < 0), penalize wide spreads
            # to prioritize tighter, safer obligation collection and lower variance
            if te_delta < 0:
                ev -= 0.04 * abs(te_delta) * (w - floor)

            if best_ev is None or ev > best_ev:
                best_ev, best_lo, best_w = ev, lo, w

        return (best_lo, best_lo + best_w)

    # ── Adaptive Negotiation & Trapping ─────────────────────────────

    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote

        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0
            self._update_beliefs(obs)

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

        # Dynamic ride hurdle adjusted by Bayesian belief and shift powers
        # If opponent is an Aggressive Forcer, hold out for Turn 6
        p_aggro = self.posterior[3]
        base_ride = 0.8 + 0.1 * p_aggro
        bar = base_ride * (ask - bid)
        if shift > 0 and not obs.is_maker:
            bar = max(bar, float(shift - 2.0))

        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"

        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

    # ── Equilibrium Auction Bidding ─────────────────────────────────

    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}

        # 1. Check if opponent is broke
        if obs.te_theirs <= 0:
            return {offered[0]: 1}

        # 2. Dynamic shade derived from Bayesian posterior
        # Passive opponent -> shade down to 0.18 to snipe cheap
        # Aggro opponent -> shade up to 0.35 to contest high-value power
        p_passive = self.posterior[2]
        p_aggro = self.posterior[3]
        shade = 0.33 - 0.15 * p_passive + 0.05 * p_aggro
        shade = max(0.18, min(0.38, shade))

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

def evaluate_adaptive_master():
    print("=" * 80)
    print("EVALUATING ADAPTIVE MASTER (CFR AUCTION + INVENTORY SKEW + BAYESIAN PROFILER)")
    print("=" * 80)
    cls = Bot_AdaptiveMaster
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
    evaluate_adaptive_master()
