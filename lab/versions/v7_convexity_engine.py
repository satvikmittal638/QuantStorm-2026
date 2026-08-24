# Name: Satvik Mittal
# College: IIT Kanpur
# Roll Number: 240943

"""
qs_bot.py -- Divided Oracle entry (v7 Convexity & Shift Arbitrage Engine - Patched Engine Compatible).

Core Strategic Pillars:

1. THE TAKER OWNS THE LAST TURN & SHIFT POWER ARBITRAGE.
   N_TURNS is 6. Taker moves last. Under the floor-spread engine constraint,
   countering on Turn 6 produces a range anchored at ask of width `floor`,
   executing at `max((bid + ask)//2, ask - floor//2) + shift` for the 2.0 fee.
   Holding TRICK_ROOM (+3) or STEALTH_ROCK (+2) turns Turn 6 into guaranteed
   structural rent. Earlier turns dynamically set their reservation hurdle
   to max(0.8 * spread, shift - 2.0), refusing to settle early for less.

2. ASYMMETRIC SUBSTITUTE CONVEXITY ENGINE (BACHELIER OPTION PRICING).
   SUBSTITUTE caps downside at -2.0 ticks while leaving upside uncapped.
   We price expected contract returns using the exact Bachelier normal option
   formula E[max(X, -2.0)], capturing the variance bonus sigma * phi(z).
   When the OPPONENT holds SUBSTITUTE, we price E[min(X, +2.0)] = -E[max(-X, -2.0)],
   widening our trade hurdle to prevent selling cheap volatility.

3. PRICE ON E[S], NOT ON YOUR OWN COINS.
   E[S] = k_mine + E[k_theirs]. Historical opening quotes and FORESIGHT leaks
   are combined by inverse-variance weighting.

4. EXACT PARITY-LATTICE STRADDLE & JOINT WIDTH SOLVING.
   S is always EVEN. Quotes align to even parity, and width is optimized
   jointly against our true straddle probability versus the canonical baseline.

5. CALIBRATED FIRST-PRICE AUCTION SHADING (SHADE = 0.33).
   Bids at 33% of measured value to capture high-leverage powers against
   active bidders while preserving end-of-deal TE salvage.
"""

from __future__ import annotations

import math
import random
from math import comb, erf, exp, pi, sqrt

# -- Tunables --------------------------------------------------------

RIDE_FRACTION = 0.8
READ_NOISE = 2.0
READ_TRUST = 1.0
SHADE = 0.33
FLAT = 1

POWER_TICKS = {
    "FORESIGHT":    {1: 1.54, 2: 1.32, 3: 2.38, 4: 3.14, 5: 1.49},
    "TRICK_ROOM":   {1: 0.42, 2: 0.31, 3: 0.09, 4: 0.00, 5: 0.00},
    "SUBSTITUTE":   {1: 1.34, 2: 1.26, 3: 1.39, 4: 1.67, 5: 2.55},
    "STEALTH_ROCK": {1: 0.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
    "TRANSFORM":    {1: 0.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
}


# -- Math helpers for Option Pricing ---------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / 1.4142135623730951))

def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / 2.5066282746310002

def _option_val_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    """Expected payoff of max(X, -cap) for X ~ N(mu, sigma^2)."""
    if sigma <= 1e-4:
        return max(mu, -cap)
    z = (mu + cap) / sigma
    phi_z = _norm_pdf(z)
    Phi_z = _norm_cdf(z)
    return mu * Phi_z - cap * (1.0 - Phi_z) + sigma * phi_z

def _option_val_opponent_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    """Our expected payoff when opponent holds SUBSTITUTE: min(X, +cap)."""
    return -_option_val_substitute(-mu, sigma, cap)


class Bot:
    name = "QS"

    # -- lifecycle ---------------------------------------------------

    def reset(self, seat: int, config, seed: int) -> None:
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self.reads: dict[int, float] = {}
        self.opp_bids = 0

    # -- belief ------------------------------------------------------

    def _refresh(self, obs) -> None:
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                self.reads[c.round] = (c.open_bid + c.open_ask) / 2.0

    def _their_k(self, obs):
        parts = []
        n = len(obs.foresight)
        if n:
            parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))

        if self.reads:
            r0 = max(self.reads)
            parts.append((self.reads[r0], 4.0 * (obs.round - r0) + READ_NOISE))

        if not parts:
            return None

        for est, var in parts:
            if var <= 0.0:
                return est, 0.0

        wsum = sum(1.0 / var for _, var in parts)
        est = sum(e / var for e, var in parts) / wsum
        return est, 1.0 / wsum

    def _est(self, obs) -> float:
        tk = self._their_k(obs)
        return float(obs.k_mine) + (tk[0] if tk else 0.0)

    def _unseen(self, obs) -> int:
        cfg = self.config
        mine_left = cfg.N_PRIVATE - cfg.REVEAL_PER_ROUND * obs.round
        theirs = cfg.N_PRIVATE

        n = len(obs.foresight)
        if n:
            theirs = min(theirs, cfg.N_PRIVATE - n)
        if self.reads:
            r0 = max(self.reads)
            known = READ_TRUST * cfg.REVEAL_PER_ROUND * r0
            theirs = min(theirs, cfg.N_PRIVATE - known)

        return max(0, int(round(mine_left + theirs)))

    def _shift(self, obs) -> int:
        total = 0
        for name in ("TRICK_ROOM", "STEALTH_ROCK"):
            mag = int(self.config.POWERS[name]["magnitude"])
            if name in obs.powers_mine:
                total += mag
            if name in obs.powers_theirs:
                total -= mag
        return total

    # -- quoting -----------------------------------------------------

    def _cover(self, m: int, a: int, b: int) -> float:
        if m <= 0:
            return 1.0 if a <= 0 <= b else 0.0
        total = 0
        for j in range(a, b + 1):
            if (j - m) % 2:
                continue
            k = (j + m) // 2
            if 0 <= k <= m:
                total += comb(m, k)
        return total / (1 << m)

    def quote(self, obs):
        self._refresh(obs)
        cfg = self.config
        v = int(round(self._est(obs)))
        r, floor, cap = obs.round, obs.final_cap, obs.spread_cap
        unseen = self._unseen(obs)

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
            if best_ev is None or ev > best_ev:
                best_ev, best_lo, best_w = ev, lo, w

        return (best_lo, best_lo + best_w)

    # -- negotiating -------------------------------------------------

    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote

        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        shift = self._shift(obs)
        sigma = sqrt(max(1, self._unseen(obs)))
        floor = obs.final_cap

        # -- Turn 6 (Final turn: Taker only) --
        if turn >= obs.n_turns:
            # Under the engine floor patch, countering (ask, ask) clamps to [ask - floor, ask]
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

        bar = RIDE_FRACTION * (ask - bid)
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

    # -- the auction -------------------------------------------------

    def _power_value(self, obs, name: str) -> float:
        row = POWER_TICKS.get(name)
        if row is None:
            return 0.5
        return row.get(obs.round, 0.0)

    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}

        wanted: list[tuple[float, str, int]] = []
        for name in offered:
            v = self._power_value(obs, name)
            if v <= 0.0:
                continue

            amount = int(v / self.config.TE_SALVAGE * SHADE)
            amount = min(amount, int(obs.te_theirs) + 1)
            if amount > 0:
                wanted.append((v, name, amount))

        out: dict[str, int] = {}
        for _, name, amount in sorted(wanted, key=lambda t: -t[0]):
            take = min(amount, budget)
            if take <= 0:
                break
            out[name] = take
            budget -= take
        return out

    def use_transform(self, obs) -> bool:
        return False
