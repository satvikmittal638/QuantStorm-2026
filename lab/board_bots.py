"""board_bots.py -- reconstructions of the ten hidden leaderboard opponents.

LOCAL ONLY. Never submitted.

The board reports per-opponent results against ten bots named
o01_raw_bid_sniper .. o10_foresight_deflation. The bots themselves are hidden,
but the names are precise strategy descriptions, so these are reconstructions
from the names plus the board's per-opponent scores.

THESE ARE GUESSES. They exist to expose weaknesses our honest-quoting panel
cannot, not to be tuned against to the last decimal. The calibration test is
whether our RELATIVE ordering against them resembles the board's ordering:

    board (mean PnL/match, our +84.83 submission)
      o01_raw_bid_sniper        +127.22   <- easiest
      o07_obligation_harvester   +94.22
      o02_te_opportunity_cost    +89.99
      o05_transform_arbitrageur  +88.30
      o03_quote_compressor       +86.20
      o06_shift_power_camper     +81.70
      o04_counterspy             +80.15
      o09_min_counter_squeeze    +72.48
      o10_foresight_deflation    +71.82
      o08_forced_fill_engineer   (truncated in the report -- lowest)
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from opponents import _Base, SHIFT, adaptive_POWER_VALUES  # noqa: E402


def _te(cfg, ticks, shade=1.0):
    """Convert a tick valuation into a TE bid at the given shade."""
    return max(0, int(ticks / cfg.TE_SALVAGE * shade))


class _Board(_Base):
    """Shared base: floor width, honest pricing, turn-6 aware.

    Every board bot is assumed competent -- they beat the shipped baselines by
    a wide margin, so none of them is a naive_ev-class bot.
    """
    width_mode = "floor"
    bid_mode = "none"
    use_t6 = True

    def _fit(self, obs, want: dict) -> dict:
        """Clamp a bid plan to the budget. The engine ZEROES an over-budget
        vector, so this must never be left to chance."""
        budget = int(obs.te_mine)
        out = {}
        for name, amt in sorted(want.items(), key=lambda kv: -kv[1]):
            take = max(0, min(int(amt), budget))
            if take > 0:
                out[name] = take
                budget -= take
        return out


# -- o01 ---------------------------------------------------------------

class o01_raw_bid_sniper(_Board):
    """Bids the minimum that can win anything, on everything.

    Takes every power nobody contests for 1-2 TE and banks the rest as
    salvage. Cheap and surprisingly effective against bots that concede the
    auction -- and the board says it is our EASIEST matchup (+127), which
    makes sense: our own shade is low enough to outbid it while still
    keeping most of our budget.
    """
    name = "o01_raw_bid_sniper"

    def bid(self, obs, offered):
        return self._fit(obs, {n: 2 for n in offered})


# -- o02 ---------------------------------------------------------------

class o02_te_opportunity_cost(_Board):
    """Prices every power against what the energy is worth banked.

    A power is bought only when its tick value beats the salvage value of the
    TE it costs. This is the 'correct' textbook bidder and it spends little,
    so the salvage edge we normally collect largely vanishes against it.
    """
    name = "o02_te_opportunity_cost"

    def bid(self, obs, offered):
        want = {}
        for n in offered:
            v = adaptive_POWER_VALUES.get(n, {}).get(obs.round, 0.5)
            # Buy only if the power beats the energy at its own exchange rate,
            # with a margin -- then shade hard because it is first price.
            fair = _te(self.config, v)
            if fair > 4:
                want[n] = int(fair * 0.45)
        return self._fit(obs, want)


# -- o03 ---------------------------------------------------------------

class o03_quote_compressor(_Board):
    """Compresses its opening quote toward zero so the midpoint leaks less.

    Directly attacks quote-reading: a Maker centring honestly broadcasts its
    revealed sum, and this one refuses to. It still prices on the truth
    internally. Our score of +86.20 suggests the real one compresses mildly
    rather than lying outright.
    """
    name = "o03_quote_compressor"
    COMPRESS = 0.45

    def quote(self, obs):
        self._refresh(obs)
        k = obs.k_mine + (sum(obs.foresight) if obs.foresight else 0)
        v = int(round(k * self.COMPRESS))
        w = obs.final_cap
        return (v - w // 2, v + (w - w // 2))


# -- o04 ---------------------------------------------------------------

class o04_counterspy(_Board):
    """Reads us hard and feeds us a poisoned read in return.

    Two-sided: it centres on k_mine + its read of us (so its own price is
    good), which as a side effect makes its midpoint a lie about its own
    hand. This is exactly what OUR bot does, so o04 is close to a mirror of
    us -- consistent with it being one of our tighter matchups (+80.15).
    """
    name = "o04_counterspy"

    def quote(self, obs):
        self._refresh(obs)
        o = self._read()
        f = sum(obs.foresight) if obs.foresight else 0
        v = int(round(obs.k_mine + f + (o if o is not None else 0.0)))
        w = obs.final_cap
        return (v - w // 2, v + (w - w // 2))


# -- o05 ---------------------------------------------------------------

class o05_transform_arbitrageur(_Board):
    """Plays TRANSFORM from both sides: takes it to swap a flat hand, and
    takes it to DENY when its hand is decisive (the power is consumed either
    way, so buying and declining is a veto)."""
    name = "o05_transform_arbitrageur"

    def bid(self, obs, offered):
        want = {}
        for n in offered:
            if n == "TRANSFORM":
                want[n] = _te(self.config, 1.6, 0.75)      # contest it hard
            else:
                v = adaptive_POWER_VALUES.get(n, {}).get(obs.round, 0.5)
                want[n] = _te(self.config, v, 0.35)
        return self._fit(obs, want)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1


# -- o06 ---------------------------------------------------------------

class o06_shift_power_camper(_Board):
    """Buys TRICK_ROOM and STEALTH_ROCK and then wants forced fills.

    STEALTH_ROCK is persistent, so winning it early shifts every remaining
    forced fill. Once it holds shift, it refuses to accept and rides to the
    midpoint, where the shift pays it.
    """
    name = "o06_shift_power_camper"

    def bid(self, obs, offered):
        want = {}
        for n in offered:
            if n == "STEALTH_ROCK":
                want[n] = _te(self.config, 2.0 * (self.config.N_ROUNDS - obs.round + 1) * 0.3, 0.8)
            elif n == "TRICK_ROOM":
                want[n] = _te(self.config, 3.0 * 0.35, 0.8)
            else:
                want[n] = _te(self.config, adaptive_POWER_VALUES.get(n, {}).get(obs.round, 0.5), 0.3)
        return self._fit(obs, want)

    def respond(self, obs, quote, turn):
        mine = sum(SHIFT[p] for p in obs.powers_mine if p in SHIFT)
        if mine > 0 and turn < obs.n_turns:
            # Holding shift: do not settle early, ride to the fill.
            bid, ask = quote
            w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
            v = self._est(obs)
            c = max(bid, min(round(v), ask - w))
            return ("COUNTER", c, c + w)
        return _Board.respond(self, obs, quote, turn)


# -- o07 ---------------------------------------------------------------

class o07_obligation_harvester(_Board):
    """Chooses its opening width to maximise the maker obligation.

    The obligation pays 3.0*(1-p_w) on a straddle and charges 3.0*p_w on a
    miss, scored at the BASELINE unseen -- so a Maker who knows more than
    baseline is paid the difference. This one solves the width for that,
    exactly as we do, and is honest about its centre.
    """
    name = "o07_obligation_harvester"

    def quote(self, obs):
        self._refresh(obs)
        cfg = self.config
        o = self._read()
        f = sum(obs.foresight) if obs.foresight else 0
        v = int(round(obs.k_mine + f + (o if o is not None else 0.0)))
        r = obs.round
        # unseen given what it actually knows
        unseen = cfg.N_PRIVATE - cfg.REVEAL_PER_ROUND * r
        unseen += cfg.N_PRIVATE - (len(obs.foresight) if obs.foresight else 0)
        best_w, best_ev = obs.final_cap, None
        for w in range(obs.final_cap, obs.spread_cap + 1):
            ev = (cfg.MAKER_OBLIGATION
                  * (cfg.straddle_prob(r, w, unseen=unseen) - cfg.straddle_prob(r, w))
                  - cfg.WIDTH_PREMIUM * (w - obs.final_cap))
            if best_ev is None or ev > best_ev:
                best_ev, best_w = ev, w
        return (v - best_w // 2, v + (best_w - best_w // 2))


# -- o08 ---------------------------------------------------------------

class o08_forced_fill_engineer(_Board):
    """Drives rounds to a forced fill on terms it has arranged. OUR WORST.

    It never accepts, and on the last turn it takes the same option we do --
    counter to the far edge, become the short, pay the fee and collect the
    spread. Against a bot that also rides, whoever understands the last turn
    better wins the round, and this one contests shift powers to tilt the
    fill on top.
    """
    name = "o08_forced_fill_engineer"

    def bid(self, obs, offered):
        want = {}
        for n in offered:
            if n in SHIFT:
                want[n] = _te(self.config, SHIFT[n] * 0.5, 0.8)
            else:
                want[n] = _te(self.config, adaptive_POWER_VALUES.get(n, {}).get(obs.round, 0.5), 0.3)
        return self._fit(obs, want)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        if turn >= obs.n_turns:
            sh = self._shift(obs)
            return max([(v - ask, "ACCEPT_BUY"),
                        (bid - v, "ACCEPT_SELL"),
                        ((ask + sh) - v - fee, ("COUNTER", ask, ask))],
                       key=lambda t: t[0])[1]
        # Never settle early; steer the range so the last-turn option is fat.
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        c = (ask - w) if v <= (bid + ask) / 2 else bid
        c = max(bid, min(c, ask - w))
        return ("COUNTER", c, c + w)


# -- o09 ---------------------------------------------------------------

class o09_min_counter_squeeze(_Board):
    """Counters by exactly MIN_REDUCTION every turn, squeezing the range
    down while conceding as little as possible, and never accepts early.

    Against a bot whose counters centre on its own value, the squeezer
    extracts the centre one tick at a time and arrives at the last turn with
    a range it chose.
    """
    name = "o09_min_counter_squeeze"

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE
        if turn >= obs.n_turns:
            sh = self._shift(obs)
            return max([(v - ask, "ACCEPT_BUY"),
                        (bid - v, "ACCEPT_SELL"),
                        ((ask + sh) - v - fee, ("COUNTER", ask, ask))],
                       key=lambda t: t[0])[1]
        # Shrink by exactly one tick, from whichever end is worse for us.
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        if v <= (bid + ask) / 2:
            c = ask - w          # keep the ask, give up the bid
        else:
            c = bid
        c = max(bid, min(c, ask - w))
        return ("COUNTER", c, c + w)


# -- o10 ---------------------------------------------------------------

class o10_foresight_deflation(_Board):
    """Makes information cheap: contests FORESIGHT to deny it, and quotes so
    that reading its midpoint is worthless.

    The name cuts both ways -- deflating the VALUE of foresight means both
    denying the power and making its own hand unreadable. Our second-worst
    matchup (+71.82), which fits: it attacks the read our pricing depends on.
    """
    name = "o10_foresight_deflation"

    def bid(self, obs, offered):
        want = {}
        for n in offered:
            if n == "FORESIGHT":
                want[n] = _te(self.config, 2.0, 0.85)   # deny it
            else:
                want[n] = _te(self.config, adaptive_POWER_VALUES.get(n, {}).get(obs.round, 0.5), 0.3)
        return self._fit(obs, want)

    def quote(self, obs):
        self._refresh(obs)
        # Quote a deliberately uninformative centre: shrunk toward zero and
        # nudged by the round, so a reader latching the midpoint learns little.
        k = obs.k_mine + (sum(obs.foresight) if obs.foresight else 0)
        v = int(round(k * 0.25))
        w = obs.final_cap
        return (v - w // 2, v + (w - w // 2))


BOARD = [
    ("o01_raw_bid_sniper", o01_raw_bid_sniper),
    ("o02_te_opportunity_cost", o02_te_opportunity_cost),
    ("o03_quote_compressor", o03_quote_compressor),
    ("o04_counterspy", o04_counterspy),
    ("o05_transform_arbitrageur", o05_transform_arbitrageur),
    ("o06_shift_power_camper", o06_shift_power_camper),
    ("o07_obligation_harvester", o07_obligation_harvester),
    ("o08_forced_fill_engineer", o08_forced_fill_engineer),
    ("o09_min_counter_squeeze", o09_min_counter_squeeze),
    ("o10_foresight_deflation", o10_foresight_deflation),
]

#: Board's own ordering of our +84.83 submission, for calibration.
BOARD_ACTUAL = {
    "o01_raw_bid_sniper": 127.22,
    "o07_obligation_harvester": 94.22,
    "o02_te_opportunity_cost": 89.99,
    "o05_transform_arbitrageur": 88.30,
    "o03_quote_compressor": 86.20,
    "o06_shift_power_camper": 81.70,
    "o04_counterspy": 80.15,
    "o09_min_counter_squeeze": 72.48,
    "o10_foresight_deflation": 71.82,
    "o08_forced_fill_engineer": None,   # truncated in the report we have
}
