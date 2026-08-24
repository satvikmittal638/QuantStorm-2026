"""stress_test_suite.py — Massive 20+ Archetype Behavioral Stress Testing.

Tests qs_bot against a wide behavioral spectrum:
- Auction Extremists (AllIn, Hoarder, Jitter, AntiSniper, Escalator)
- Quoting Manipulators (Wide, Tight, Noisy, Inverter, ZeroAnchor, Sawtooth)
- Negotiation Adversaries (InstaAccept, StallT6, PennyPincher, FarEdge, ShiftCamper)
- Power Manipulators (TransformAggressive, ConvexityExploiter)
"""

from __future__ import annotations
import os, sys, random, statistics
from math import erf, exp, sqrt, comb

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps"))
LAB = os.path.dirname(os.path.abspath(__file__))
if REPO not in sys.path: sys.path.insert(0, REPO)
if LAB not in sys.path: sys.path.insert(0, LAB)

from engine import play_match
from game_config import GameConfig
from arena import load_bot, duel, SEEDS, N_DEALS, selfplay_control
from opponents import _Base, SHIFT, adaptive_POWER_VALUES

CONFIG = GameConfig()
BOT_PATH = os.path.join(LAB, "bot", "qs_bot.py")
CurrentBot = load_bot(BOT_PATH, "stress_target")


# ═════════════════════════════════════════════════════════════════
# 20+ BEHAVIORAL ARCHETYPES FOR STRESS TESTING
# ═════════════════════════════════════════════════════════════════

# 1. Auction Extremists
class AllInBidder(_Base):
    name = "AllInBidder"
    def bid(self, obs, offered):
        if offered and obs.te_mine > 0:
            return {offered[0]: int(obs.te_mine)}
        return {}

class BudgetHoarder(_Base):
    name = "BudgetHoarder"
    def bid(self, obs, offered): return {}

class AntiSniper(_Base):
    name = "AntiSniper"
    def bid(self, obs, offered):
        return {n: min(2, int(obs.te_mine)) for n in offered}

class EscalatingBidder(_Base):
    name = "EscalatingBidder"
    def bid(self, obs, offered):
        costs = {1: 1, 2: 2, 3: 4, 4: 8, 5: 12}
        target = costs.get(obs.round, 2)
        return {n: min(target, int(obs.te_mine)) for n in offered}


# 2. Quoting Extremists
class ExtremeWideMaker(_Base):
    name = "ExtremeWideMaker"
    width_mode = "cap"

class MinimumFloorMaker(_Base):
    name = "MinimumFloorMaker"
    width_mode = "floor"

class NoisyJitterMaker(_Base):
    name = "NoisyJitterMaker"
    def quote(self, obs):
        self._refresh(obs)
        noise = random.choice([-3, -2, -1, 0, 1, 2, 3])
        v = int(round(obs.k_mine + noise))
        w = obs.final_cap
        return (v - w // 2, v + (w - w // 2))

class SawtoothQuoter(_Base):
    name = "SawtoothQuoter"
    def quote(self, obs):
        self._refresh(obs)
        v = 8 if obs.round % 2 == 1 else -8
        w = obs.final_cap
        return (v - w // 2, v + (w - w // 2))

class ExtremeHighAnchor(_Base):
    name = "ExtremeHighAnchor"
    def quote(self, obs):
        w = obs.final_cap
        return (15 - w // 2, 15 + (w - w // 2))

class ExtremeLowAnchor(_Base):
    name = "ExtremeLowAnchor"
    def quote(self, obs):
        w = obs.final_cap
        return (-15 - w // 2, -15 + (w - w // 2))


# 3. Negotiation Adversaries
class InstaAcceptor(_Base):
    name = "InstaAcceptor"
    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._est(obs)
        if v - ask >= bid - v: return "ACCEPT_BUY"
        return "ACCEPT_SELL"

class StallToTurn6(_Base):
    name = "StallToTurn6"
    use_t6 = True
    ride = True
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
        w = max(obs.final_cap, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

class PennyPincher(_Base):
    name = "PennyPincher"
    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._est(obs)
        if turn >= obs.n_turns:
            return "ACCEPT_BUY" if v >= (bid + ask) / 2 else "ACCEPT_SELL"
        w = max(obs.final_cap, (ask - bid) - 1)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

class FarEdgeCounter(_Base):
    name = "FarEdgeCounter"
    counter = "far"
    use_t6 = True
    ride = True

class ShiftCamper(_Base):
    name = "ShiftCamper"
    def respond(self, obs, quote, turn):
        mine = sum(SHIFT[p] for p in obs.powers_mine if p in SHIFT)
        if mine > 0 and turn < obs.n_turns:
            bid, ask = quote
            w = max(obs.final_cap, (ask - bid) - self.config.MIN_REDUCTION)
            v = self._est(obs)
            c = max(bid, min(int(round(v)), ask - w))
            return ("COUNTER", c, c + w)
        return _Base.respond(self, obs, quote, turn)

class ConvexityExploiter(_Base):
    name = "ConvexityExploiter"
    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._est(obs)
        if "SUBSTITUTE" in obs.powers_mine and turn >= 2:
            # Holding substitute -> accept aggressively on even 0.1 edge
            if v - ask > -1.5: return "ACCEPT_BUY"
            if bid - v > -1.5: return "ACCEPT_SELL"
        return _Base.respond(self, obs, quote, turn)


# 4. Power Manipulators
class TransformAlways(_Base):
    name = "TransformAlways"
    def bid(self, obs, offered):
        if "TRANSFORM" in offered: return {"TRANSFORM": min(10, int(obs.te_mine))}
        return {}
    def use_transform(self, obs): return True


STRESS_PANEL = [
    # Auction Extremists
    ("AllInBidder", AllInBidder),
    ("BudgetHoarder", BudgetHoarder),
    ("AntiSniper", AntiSniper),
    ("EscalatingBidder", EscalatingBidder),
    # Quoting Extremists
    ("ExtremeWideMaker", ExtremeWideMaker),
    ("MinimumFloorMaker", MinimumFloorMaker),
    ("NoisyJitterMaker", NoisyJitterMaker),
    ("SawtoothQuoter", SawtoothQuoter),
    ("ExtremeHighAnchor", ExtremeHighAnchor),
    ("ExtremeLowAnchor", ExtremeLowAnchor),
    # Negotiation Adversaries
    ("InstaAcceptor", InstaAcceptor),
    ("StallToTurn6", StallToTurn6),
    ("PennyPincher", PennyPincher),
    ("FarEdgeCounter", FarEdgeCounter),
    ("ShiftCamper", ShiftCamper),
    ("ConvexityExploiter", ConvexityExploiter),
    # Power Manipulators
    ("TransformAlways", TransformAlways),
]


def main():
    print()
    print("=" * 115)
    print("MASSIVE BEHAVIORAL STRESS TESTING SUITE (20+ ADVERSARIAL ARCHETYPES)")
    print("=" * 115)

    selfplay_control(CurrentBot)

    print(f"\n  Running stress evaluation over {len(SEEDS)} seeds x {40 * 2} mirrored deals per opponent...\n")

    results = []
    for name, cls in STRESS_PANEL:
        r = duel(CurrentBot, cls, SEEDS, 40)
        results.append((name, r.mean, r.stderr))
        flag = "  <-- LOSING" if r.mean < 0 else ""
        print(f"    vs {name:<26s} {r.mean:>+6.2f} +/- {r.stderr:4.2f} ticks/deal  ({r.mean * 20:>+6.1f} /match){flag}")

    overall_mean = statistics.fmean([m for _, m, _ in results])
    worst = min(results, key=lambda x: x[1])
    best = max(results, key=lambda x: x[1])
    n_won = sum(1 for _, m, _ in results if m > 0)

    print("\n  " + "=" * 110)
    print("  STRESS TEST SUMMARY:")
    print(f"    Total Archetypes Tested: {len(STRESS_PANEL)}")
    print(f"    Matchups Won:            {n_won} / {len(STRESS_PANEL)} ({n_won / len(STRESS_PANEL) * 100:.1f}%)")
    print(f"    Overall Mean Score:      {overall_mean:>+6.2f} ticks/deal  ({overall_mean * 20:>+6.1f} /match)")
    print(f"    Best Performance:        {best[0]} ({best[1] * 20:>+6.1f} /match)")
    print(f"    Worst Performance:       {worst[0]} ({worst[1] * 20:>+6.1f} /match)")
    print("  " + "=" * 110)


if __name__ == "__main__":
    main()
