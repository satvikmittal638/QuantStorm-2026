"""opponents.py — the sparring panel.

LOCAL ONLY. Never submitted.

The three reference bots plus archetypes for play styles the real field is
likely to contain. The point is to stop us overfitting to three known bots:
Stage 1 is a pass/fail gate against an UNPUBLISHED strategy, so a setting that
is strong on average but catastrophic against one archetype is a real risk.
"""

from __future__ import annotations

import os
import sys

REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps")
)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import importlib.util  # noqa: E402

from arena import load_bot  # noqa: E402

SHIFT = {"TRICK_ROOM": 3, "STEALTH_ROCK": 2}


def _load_module(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


naive_ev = load_bot("strategies/naive_ev.py", "ref_naive")
rational = load_bot("strategies/rational.py", "ref_rational")
adaptive_bidder = load_bot("strategies/adaptive_bidder.py", "ref_adaptive")

# The published power surface, reused by the bidding archetypes so the panel
# contests the auction the way the reference field does.
adaptive_POWER_VALUES = _load_module(
    "strategies/adaptive_bidder.py", "ref_adaptive_mod"
).POWER_VALUES

REFERENCE = [
    ("naive_ev", naive_ev),
    ("rational", rational),
    ("adaptive_bidder", adaptive_bidder),
]


# ── Archetype base ──────────────────────────────────────────────────

class _Base:
    """Honest quote-reading bot. Subclasses flip one dimension each."""

    name = "Archetype"
    width_mode = "cap"      # "cap" | "floor"
    bid_mode = "none"       # "none" | "flat" | "snipe" | "value"
    use_t6 = False          # exploit the turn-6 force-sell
    ride = False            # never accept before turn 6
    counter = "centre"      # "centre" | "far"
    kill_ride = False       # as maker at T5, collapse to own value

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.reads = {}

    # -- belief ------------------------------------------------------
    def _refresh(self, obs):
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                self.reads[c.round] = (c.open_bid + c.open_ask) / 2

    def _read(self):
        return self.reads[max(self.reads)] if self.reads else None

    def _est(self, obs):
        k = obs.k_mine
        o = self._read()
        f = float(sum(obs.foresight)) if obs.foresight else None
        if f is not None and o is not None:
            return k + 0.5 * f + 0.5 * o
        if f is not None:
            return k + f
        if o is not None:
            return k + o
        return float(k)

    def _shift(self, obs):
        mine = sum(SHIFT[p] for p in obs.powers_mine if p in SHIFT)
        theirs = sum(SHIFT[p] for p in obs.powers_theirs if p in SHIFT)
        return mine - theirs

    # -- actions -----------------------------------------------------
    def quote(self, obs):
        self._refresh(obs)
        v = round(obs.k_mine + (sum(obs.foresight) if obs.foresight else 0))
        w = obs.spread_cap if self.width_mode == "cap" else obs.final_cap
        lo = v - w // 2
        return (lo, lo + w)

    def respond(self, obs, quote, turn):
        self._refresh(obs)
        bid, ask = quote
        if turn == 2 and not obs.is_maker:
            self.reads[obs.round] = (bid + ask) / 2
        v = self._est(obs)
        last = obs.n_turns
        fee = self.config.FORCED_FILL_FEE

        if turn == last and self.use_t6:
            opts = [
                (v - ask, "ACCEPT_BUY"),
                (bid - v, "ACCEPT_SELL"),
                ((ask + self._shift(obs)) - v - fee, ("COUNTER", ask, ask)),
            ]
            return max(opts, key=lambda t: t[0])[1]

        if self.kill_ride and obs.is_maker and turn == last - 1:
            c = max(bid, min(round(v), ask))
            return ("COUNTER", c, c)

        if not self.ride:
            if v - ask > 0 and v - ask >= bid - v:
                return "ACCEPT_BUY"
            if bid - v > 0:
                return "ACCEPT_SELL"

        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        if self.counter == "far":
            c = (ask - w) if v <= (bid + ask) / 2 else bid
        else:
            c = max(bid, min(round(v), ask - w))
        c = max(bid, min(c, ask - w))
        return ("COUNTER", c, c + w)

    def bid(self, obs, offered):
        if self.bid_mode == "none" or not offered or obs.te_mine <= 0:
            return {}
        if self.bid_mode == "snipe":
            return {n: 1 for n in offered}
        if self.bid_mode == "flat":
            return {n: min(8, obs.te_mine) for n in offered}
        # "value"/"heavy": adaptive_bidder's published surface, shaded
        shade = 1.0 if self.bid_mode == "heavy" else 0.6
        out = {}
        for n in offered:
            v = adaptive_POWER_VALUES.get(n, {}).get(obs.round, 0.5)
            if v > 0:
                out[n] = max(0, min(int(v / self.config.TE_SALVAGE * shade), obs.te_mine))
        total = sum(out.values())
        if total > obs.te_mine and total > 0:
            out = {k: int(v * obs.te_mine / total) for k, v in out.items()}
        return out

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1


# ── The archetypes ──────────────────────────────────────────────────

class CapQuoter(_Base):
    """Quotes at the maximum width every round. The engine's own fallback
    behaviour, and what naive_ev / rational / starter_bot all do."""
    name = "CapQuoter"


class FloorQuoter(_Base):
    """Quotes at the floor. Pays no width premium — the obvious first fix,
    so a lot of the field will land here."""
    name = "FloorQuoter"
    width_mode = "floor"


class FlatBidder(_Base):
    """No power valuation at all: 8 TE on everything. The repo says this
    captured 93% of the auction axis on the old spec."""
    name = "FlatBidder"
    width_mode = "floor"
    bid_mode = "flat"


class Sniper(_Base):
    """Bids 1 TE on everything — takes any power nobody contests, for free."""
    name = "Sniper"
    width_mode = "floor"
    bid_mode = "snipe"


class T6Bot(_Base):
    """An opponent who also found the turn-6 force-sell."""
    name = "T6Bot"
    width_mode = "floor"
    bid_mode = "value"
    use_t6 = True


class RideKiller(_Base):
    """The direct counter to ride-to-turn-6: as Maker, collapses the range
    to its own value on T5, so the Taker's T6 option is worth ~0. This is
    the bot that should scare us."""
    name = "RideKiller"
    width_mode = "floor"
    bid_mode = "value"
    use_t6 = True
    ride = True
    kill_ride = True


class HeavyBidder(_Base):
    """Fights hard for every power: no shading at all, full published value.

    Here to keep the auction tuning honest. Most of the panel bids little or
    nothing, which biases the shade sweep toward sniping cheap; a field that
    actually contests powers has to be represented or we tune to a fiction."""
    name = "HeavyBidder"
    width_mode = "floor"
    bid_mode = "heavy"
    use_t6 = True


class Aggro(_Base):
    """Pushes the ask away from its own value so its T6 option is fat."""
    name = "Aggro"
    width_mode = "floor"
    bid_mode = "value"
    use_t6 = True
    ride = True
    counter = "far"


class PennyJumper(_Base):
    """Squeezes spread by exactly the minimal reduction every turn to test tight negotiation."""
    name = "PennyJumper"
    width_mode = "floor"
    bid_mode = "value"
    use_t6 = True


class InventoryHoarder(_Base):
    """Hoards TE until rounds 4-5, then dumps all remaining budget on FORESIGHT/SUBSTITUTE."""
    name = "InventoryHoarder"
    width_mode = "floor"
    use_t6 = True
    def bid(self, obs, offered):
        if not offered or obs.te_mine <= 0:
            return {}
        if obs.round >= 4:
            for n in ("FORESIGHT", "SUBSTITUTE"):
                if n in offered:
                    return {n: int(obs.te_mine)}
        return {}


class OptionPoisoner(_Base):
    """If holding SUBSTITUTE, quotes aggressively off-market to bait counterparty trades."""
    name = "OptionPoisoner"
    width_mode = "floor"
    bid_mode = "heavy"
    use_t6 = True
    def quote(self, obs):
        self._refresh(obs)
        v = round(obs.k_mine + (sum(obs.foresight) if obs.foresight else 0))
        w = obs.final_cap
        if "SUBSTITUTE" in obs.powers_mine:
            v += 2  # Skew to bait
        lo = v - w // 2
        return (lo, lo + w)


class AsymmetricSkewMaker(_Base):
    """Quotes 2 ticks higher than fair value to force short fills."""
    name = "AsymmetricSkewMaker"
    width_mode = "floor"
    bid_mode = "value"
    use_t6 = True
    def quote(self, obs):
        self._refresh(obs)
        v = round(obs.k_mine + (sum(obs.foresight) if obs.foresight else 0)) + 2
        w = obs.final_cap
        lo = v - w // 2
        return (lo, lo + w)


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


ARCHETYPES = [
    ("CapQuoter", CapQuoter),
    ("FloorQuoter", FloorQuoter),
    ("FlatBidder", FlatBidder),
    ("Sniper", Sniper),
    ("T6Bot", T6Bot),
    ("RideKiller", RideKiller),
    ("HeavyBidder", HeavyBidder),
    ("Aggro", Aggro),
    ("PennyJumper", PennyJumper),
    ("InventoryHoarder", InventoryHoarder),
    ("OptionPoisoner", OptionPoisoner),
    ("AsymmetricSkewMaker", AsymmetricSkewMaker),
]

PANEL = REFERENCE + ARCHETYPES
LIARS = [
    ("liar_compress", liar("compress")),
    ("liar_invert", liar("invert")),
    ("liar_zero", liar("zero")),
]

