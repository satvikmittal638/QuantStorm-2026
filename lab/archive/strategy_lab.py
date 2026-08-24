"""strategy_lab.py — Deep Game-Theoretic Strategy Exploration.

Explores 10+ distinct strategic hypotheses derived from careful rulebook
analysis. Each hypothesis isolates ONE mechanic change and measures its
marginal impact via head-to-head and panel dueling.

Run:  python lab/strategy_lab.py
"""

from __future__ import annotations

import math
import os
import statistics
import sys

REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps")
)
LAB = os.path.dirname(os.path.abspath(__file__))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if LAB not in sys.path:
    sys.path.insert(0, LAB)

from engine import play_match
from game_config import GameConfig
from arena import load_bot, duel, SEEDS, N_DEALS, Result
from opponents import PANEL, LIARS

CONFIG = GameConfig()

# ═════════════════════════════════════════════════════════════════
# The v8 base bot for head-to-head comparison
# ═════════════════════════════════════════════════════════════════
BASE_PATH = os.path.join(LAB, "bot", "qs_bot.py")
BaseBotCls = load_bot(BASE_PATH, "base_bot_ref")

# ═════════════════════════════════════════════════════════════════
# Math helpers (copied from qs_bot to keep variants self-contained)
# ═════════════════════════════════════════════════════════════════
from math import comb, erf, exp, sqrt

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / 1.4142135623730951))

def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / 2.5066282746310002

def _option_val_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    if sigma <= 1e-4:
        return max(mu, -cap)
    z = (mu + cap) / sigma
    return mu * _norm_cdf(z) - cap * (1.0 - _norm_cdf(z)) + sigma * _norm_pdf(z)

def _option_val_opponent_substitute(mu: float, sigma: float, cap: float = 2.0) -> float:
    return -_option_val_substitute(-mu, sigma, cap)


# ═════════════════════════════════════════════════════════════════
#  VARIANT FACTORY: Creates variant bots by patching methods
# ═════════════════════════════════════════════════════════════════

import random
from copy import deepcopy


def make_variant(name_suffix, overrides: dict):
    """Create a Bot class that inherits from BaseBotCls with overrides."""
    # We can't subclass a loaded Bot easily, so we use composition:
    # Create a fresh class that wraps BaseBotCls and overrides specific methods.

    class Variant(BaseBotCls):
        pass

    Variant.name = f"QS_{name_suffix}"
    for method_name, method_fn in overrides.items():
        setattr(Variant, method_name, method_fn)
    return Variant


# ═════════════════════════════════════════════════════════════════
# HYPOTHESIS 1: OPTIMAL T6 COUNTER PLACEMENT
#
# The current bot always counters at (ask, ask) on Turn 6, which
# clamps to [ask-floor, ask]. But countering at [bid, bid+floor]
# might be better when v < midpoint (we'd be SHORT and want LOW price).
# ═════════════════════════════════════════════════════════════════

def _respond_optimal_t6(self, obs, quote, turn: int):
    self._refresh(obs)
    bid, ask = quote

    if turn == 2 and not obs.is_maker and obs.round not in self.reads:
        mid = (bid + ask) / 2.0
        self.reads[obs.round] = mid
        if abs(mid) > 4 * obs.round + 1.0:
            self.p_honest *= 0.1

    v = self._est(obs)
    fee = self.config.FORCED_FILL_FEE
    shift = self._shift(obs)
    sigma = sqrt(max(1, self._unseen(obs)))
    floor = obs.final_cap

    if turn >= obs.n_turns:
        # Evaluate ALL legal counter placements
        sub_mine = "SUBSTITUTE" in obs.powers_mine
        sub_theirs = "SUBSTITUTE" in obs.powers_theirs

        def _ev(raw):
            if sub_mine:
                return _option_val_substitute(raw, sigma)
            elif sub_theirs:
                return _option_val_opponent_substitute(raw, sigma)
            return raw

        candidates = [
            (_ev(v - ask), "ACCEPT_BUY"),
            (_ev(bid - v), "ACCEPT_SELL"),
        ]

        # Counter at top: [max(bid, ask-floor), ask]
        top_lo = max(bid, ask - floor)
        top_px = (top_lo + ask) // 2 + shift
        # We counter -> last quoter -> we are SHORT. PnL = price - S
        candidates.append((_ev(top_px - v) - fee, ("COUNTER", top_lo, ask)))

        # Counter at bottom: [bid, min(ask, bid+floor)]
        bot_hi = min(ask, bid + floor)
        bot_px = (bid + bot_hi) // 2 + shift
        candidates.append((_ev(bot_px - v) - fee, ("COUNTER", bid, bot_hi)))

        # Counter centered on v
        cv = int(round(v))
        c_lo = max(bid, min(cv - floor // 2, ask - floor))
        c_hi = min(ask, c_lo + floor)
        c_lo = max(bid, c_hi - floor)
        c_px = (c_lo + c_hi) // 2 + shift
        candidates.append((_ev(c_px - v) - fee, ("COUNTER", c_lo, c_hi)))

        return max(candidates, key=lambda o: o[0])[1]

    # -- Turns 2 to 5 (unchanged) --
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

    ride = 0.80
    if self.p_forcer > 0.5:
        ride = 0.85
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


OptimalT6 = make_variant("OptT6", {"respond": _respond_optimal_t6})


# ═════════════════════════════════════════════════════════════════
# HYPOTHESIS 2: STEALTH_ROCK REVALUATION
#
# STEALTH_ROCK gives +2 shift on ALL remaining forced fills.
# If we force ~50% of rounds, remaining_rounds * 0.5 * 2.0 = big value.
# Currently _power_value returns 0.0 for STEALTH_ROCK!
# ═════════════════════════════════════════════════════════════════

def _power_value_sr(self, obs, name: str) -> float:
    r = obs.round
    if name == "FORESIGHT":
        m = min(16, 4 * r)
        return 0.75 * sqrt(m) + (0.5 if obs.is_maker else 0.0)
    elif name == "SUBSTITUTE":
        return 0.5 * (r + 1.0)
    elif name == "TRICK_ROOM":
        return 0.6 / r
    elif name == "STEALTH_ROCK":
        remaining = 5 - r + 1  # Including this round
        return 2.0 * 0.45 * remaining
    elif name == "TRANSFORM":
        return 0.0
    return 0.0

StealthRockRevalued = make_variant("SR_Reval", {"_power_value": _power_value_sr})


# ═════════════════════════════════════════════════════════════════
# HYPOTHESIS 3: TRANSFORM DENIAL
#
# TRANSFORM is once-per-deal. If opponent wins it, they could swap
# to our better hand. Cost of denial: 1-2 TE = 0.08-0.16 ticks.
# ═════════════════════════════════════════════════════════════════

def _power_value_td(self, obs, name: str) -> float:
    r = obs.round
    if name == "FORESIGHT":
        m = min(16, 4 * r)
        return 0.75 * sqrt(m) + (0.5 if obs.is_maker else 0.0)
    elif name == "SUBSTITUTE":
        return 0.5 * (r + 1.0)
    elif name == "TRICK_ROOM":
        return 0.6 / r
    elif name == "TRANSFORM":
        return 0.12  # ~1.5 TE denial bid
    return 0.0

TransformDenial = make_variant("TR_Deny", {"_power_value": _power_value_td})


# ═════════════════════════════════════════════════════════════════
# HYPOTHESIS 4: MAKER T5 COUNTER-STEERING
#
# On Turn 5 as Maker, the Taker moves last (Turn 6).
# If Taker forces: they counter -> they are SHORT.
# As Maker we'll be LONG. Fill price = midpoint + shift.
# Higher ask -> higher midpoint -> better for us (LONG).
# So we push the ask as high as legally allowed.
# ═════════════════════════════════════════════════════════════════

def _respond_t5_steer(self, obs, quote, turn: int):
    self._refresh(obs)
    bid, ask = quote

    if turn == 2 and not obs.is_maker and obs.round not in self.reads:
        mid = (bid + ask) / 2.0
        self.reads[obs.round] = mid
        if abs(mid) > 4 * obs.round + 1.0:
            self.p_honest *= 0.1

    v = self._est(obs)
    fee = self.config.FORCED_FILL_FEE
    shift = self._shift(obs)
    sigma = sqrt(max(1, self._unseen(obs)))
    floor = obs.final_cap

    # Turn 6 (base logic)
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

    # TURN 5 AS MAKER: push counter high
    if turn == 5 and obs.is_maker:
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
        bar = 0.80 * (ask - bid)
        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"
        # Steer high: maximize ask
        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        new_ask = ask
        new_bid = max(bid, ask - w)
        return ("COUNTER", new_bid, min(ask, new_bid + w))

    # Turns 2-4 (base logic)
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

    ride = 0.80
    if self.p_forcer > 0.5:
        ride = 0.85
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

MakerT5Steer = make_variant("MakerT5", {"respond": _respond_t5_steer})


# ═════════════════════════════════════════════════════════════════
# HYPOTHESIS 5: LOWER RIDE HURDLE (more accepting of trades)
#
# Current ride = 0.80 * spread. What if we drop it to 0.65?
# We accept trades more often, but we trade when we have edge.
# ═════════════════════════════════════════════════════════════════

def _respond_low_ride(self, obs, quote, turn: int):
    self._refresh(obs)
    bid, ask = quote

    if turn == 2 and not obs.is_maker and obs.round not in self.reads:
        mid = (bid + ask) / 2.0
        self.reads[obs.round] = mid
        if abs(mid) > 4 * obs.round + 1.0:
            self.p_honest *= 0.1

    v = self._est(obs)
    fee = self.config.FORCED_FILL_FEE
    shift = self._shift(obs)
    sigma = sqrt(max(1, self._unseen(obs)))
    floor = obs.final_cap

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

    # Lower ride hurdle: 0.65 instead of 0.80
    ride = 0.65
    if self.p_forcer > 0.5:
        ride = 0.70
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

LowRide = make_variant("LowRide", {"respond": _respond_low_ride})


# ═════════════════════════════════════════════════════════════════
# HYPOTHESIS 6: PORTFOLIO HEDGING (track net position across rounds)
#
# If we're already long from rounds 1-3, prefer to go short in
# rounds 4-5 to reduce variance. Only matters when we DON'T have
# strong directional conviction.
# ═════════════════════════════════════════════════════════════════

def _respond_hedge(self, obs, quote, turn: int):
    self._refresh(obs)
    bid, ask = quote

    if turn == 2 and not obs.is_maker and obs.round not in self.reads:
        mid = (bid + ask) / 2.0
        self.reads[obs.round] = mid
        if abs(mid) > 4 * obs.round + 1.0:
            self.p_honest *= 0.1

    v = self._est(obs)
    fee = self.config.FORCED_FILL_FEE
    shift = self._shift(obs)
    sigma = sqrt(max(1, self._unseen(obs)))
    floor = obs.final_cap

    # Compute net position from existing contracts
    net_pos = 0
    for c in obs.contracts:
        if c.long_seat == self.seat:
            net_pos += 1
        else:
            net_pos -= 1

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

        # Hedging: penalize direction that increases net exposure
        hedge_pen = 0.3 * abs(net_pos) if obs.round >= 3 else 0.0
        if net_pos > 0:  # Already long, penalize buying more
            opt_buy -= hedge_pen
        elif net_pos < 0:  # Already short, penalize selling more
            opt_sell -= hedge_pen

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

    # Hedging: when heavily positioned, lower hurdle for offsetting trades
    ride = 0.80
    if self.p_forcer > 0.5:
        ride = 0.85
    bar = ride * (ask - bid)
    if shift > 0 and not obs.is_maker:
        bar = max(bar, float(shift - 2.0))

    # If heavily long and sell is available, lower bar for selling
    if net_pos >= 2 and ev_sell > 0:
        bar *= 0.5  # More willing to sell
    elif net_pos <= -2 and ev_buy > 0:
        bar *= 0.5  # More willing to buy

    if ev_buy > bar and ev_buy >= ev_sell:
        return "ACCEPT_BUY"
    if ev_sell > bar:
        return "ACCEPT_SELL"

    w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
    c = max(bid, min(int(round(v)), ask - w))
    return ("COUNTER", c, c + w)

PortfolioHedge = make_variant("Hedge", {"respond": _respond_hedge})


# ═════════════════════════════════════════════════════════════════
# HYPOTHESIS 7: COMBINED (Best of all edges)
# ═════════════════════════════════════════════════════════════════

def _respond_combined(self, obs, quote, turn: int):
    """Combines: Optimal T6, Maker T5 steering."""
    self._refresh(obs)
    bid, ask = quote

    if turn == 2 and not obs.is_maker and obs.round not in self.reads:
        mid = (bid + ask) / 2.0
        self.reads[obs.round] = mid
        if abs(mid) > 4 * obs.round + 1.0:
            self.p_honest *= 0.1

    v = self._est(obs)
    fee = self.config.FORCED_FILL_FEE
    shift = self._shift(obs)
    sigma = sqrt(max(1, self._unseen(obs)))
    floor = obs.final_cap

    sub_mine = "SUBSTITUTE" in obs.powers_mine
    sub_theirs = "SUBSTITUTE" in obs.powers_theirs

    def _ev(raw):
        if sub_mine:
            return _option_val_substitute(raw, sigma)
        elif sub_theirs:
            return _option_val_opponent_substitute(raw, sigma)
        return raw

    # Turn 6: Optimal counter placement
    if turn >= obs.n_turns:
        candidates = [
            (_ev(v - ask), "ACCEPT_BUY"),
            (_ev(bid - v), "ACCEPT_SELL"),
        ]
        top_lo = max(bid, ask - floor)
        top_px = (top_lo + ask) // 2 + shift
        candidates.append((_ev(top_px - v) - fee, ("COUNTER", top_lo, ask)))
        bot_hi = min(ask, bid + floor)
        bot_px = (bid + bot_hi) // 2 + shift
        candidates.append((_ev(bot_px - v) - fee, ("COUNTER", bid, bot_hi)))
        return max(candidates, key=lambda o: o[0])[1]

    # Turn 5 as Maker: steer high
    if turn == 5 and obs.is_maker:
        ev_buy = _ev(v - ask)
        ev_sell = _ev(bid - v)
        bar = 0.80 * (ask - bid)
        if ev_buy > bar and ev_buy >= ev_sell:
            return "ACCEPT_BUY"
        if ev_sell > bar:
            return "ACCEPT_SELL"
        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        new_ask = ask
        new_bid = max(bid, ask - w)
        return ("COUNTER", new_bid, min(ask, new_bid + w))

    # Turns 2-4: base logic
    ev_buy = _ev(v - ask)
    ev_sell = _ev(bid - v)

    ride = 0.80
    if self.p_forcer > 0.5:
        ride = 0.85
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


def _power_value_combined(self, obs, name: str) -> float:
    r = obs.round
    if name == "FORESIGHT":
        m = min(16, 4 * r)
        return 0.75 * sqrt(m) + (0.5 if obs.is_maker else 0.0)
    elif name == "SUBSTITUTE":
        return 0.5 * (r + 1.0)
    elif name == "TRICK_ROOM":
        return 0.6 / r
    elif name == "STEALTH_ROCK":
        remaining = 5 - r + 1
        return 2.0 * 0.45 * remaining
    elif name == "TRANSFORM":
        return 0.12
    return 0.0

Combined = make_variant("Combined", {
    "respond": _respond_combined,
    "_power_value": _power_value_combined,
})


# ═════════════════════════════════════════════════════════════════
#  EVALUATION HARNESS
# ═════════════════════════════════════════════════════════════════

def eval_bot(label, cls, panel=None, seeds=SEEDS, n_deals=40):
    """Score a bot variant and print one-line summary."""
    if panel is None:
        panel = PANEL

    # Head-to-head vs base
    h2h = duel(cls, BaseBotCls, seeds, n_deals)

    # Panel mean
    panel_scores = []
    for name, opp in panel:
        r = duel(cls, opp, seeds, n_deals)
        panel_scores.append((name, r.mean))

    p_mean = statistics.fmean([s for _, s in panel_scores])
    worst_name, worst_val = min(panel_scores, key=lambda x: x[1])

    # Liar mean
    liar_scores = [duel(cls, opp, seeds, n_deals).mean for _, opp in LIARS]
    l_mean = statistics.fmean(liar_scores)

    print(f"  {label:<30s} | H2H: {h2h.mean:>+6.2f} ±{h2h.stderr:4.2f}"
          f" | Panel: {p_mean:>+5.2f} | Liar: {l_mean:>+5.2f}"
          f" | Worst: {worst_name} ({worst_val:+.2f})")


def main():
    print()
    print("=" * 110)
    print("DEEP STRATEGY EXPLORATION: ISOLATED HYPOTHESIS TESTING")
    print("=" * 110)
    print()
    print(f"  Config: {len(SEEDS)} seeds × {40 * 2} deals each")
    print()

    candidates = [
        ("Base v8 (control)",          BaseBotCls),
        ("H1: Optimal T6 Counter",     OptimalT6),
        ("H2: STEALTH_ROCK Revalued",  StealthRockRevalued),
        ("H3: TRANSFORM Denial",       TransformDenial),
        ("H4: Maker T5 Steering",      MakerT5Steer),
        ("H5: Low Ride Hurdle (0.65)",  LowRide),
        ("H6: Portfolio Hedging",       PortfolioHedge),
        ("H7: ALL COMBINED",           Combined),
    ]

    for label, cls in candidates:
        eval_bot(label, cls)

    print()
    print("=" * 110)


if __name__ == "__main__":
    main()
