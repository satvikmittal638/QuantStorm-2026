"""test_convexity_auction.py — Mathematical option-theoretic valuation of SUBSTITUTE in the auction.

Theorem:
SUBSTITUTE caps loss at -2.0. The option premium of max(X, -2.0) - X for X ~ N(0, sigma^2)
is analytically:
    Premium = sigma * phi(2/sigma) - 2 * Phi(-2/sigma)

Since sigma = sqrt(unseen), and unseen decreases from ~32 (Round 1) to ~4 (Round 5),
the option premium is STRICTLY DECREASING in round number:
    R1: ~1.40 ticks
    R2: ~1.12 ticks
    R3: ~0.79 ticks
    R4: ~0.40 ticks
    R5: ~0.17 ticks

Previous heuristic was 0.5 * (r + 1), which was strictly INCREASING (1.0 -> 3.0),
causing massive overpayment for SUBSTITUTE in Rounds 4 & 5.
"""

from __future__ import annotations
import os, sys, statistics
from math import erf, exp, sqrt, comb

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps"))
LAB = os.path.dirname(os.path.abspath(__file__))
if REPO not in sys.path: sys.path.insert(0, REPO)
if LAB not in sys.path: sys.path.insert(0, LAB)

from engine import play_match
from game_config import GameConfig
from arena import load_bot, duel, SEEDS, N_DEALS
from opponents import PANEL, LIARS
import board_bots as BB

CONFIG = GameConfig()
BASE_PATH = os.path.join(LAB, "bot", "qs_bot.py")
BaseBotCls = load_bot(BASE_PATH, "v9_base")

def _norm_cdf(x): return 0.5 * (1.0 + erf(x / 1.4142135623730951))
def _norm_pdf(x): return exp(-0.5 * x * x) / 2.5066282746310002

def make_variant(suffix, overrides):
    class V(BaseBotCls): pass
    V.name = f"QS_{suffix}"
    for k, fn in overrides.items():
        setattr(V, k, fn)
    return V


# ═════════════════════════════════════════════════════════════════
# Exact Analytical Substitute Auction Valuation
# ═════════════════════════════════════════════════════════════════

def _bachelier_sub_premium(sigma: float, cap: float = 2.0) -> float:
    """Analytical value of max(X, -cap) - E[X] for zero-mean normal."""
    if sigma <= 1e-4:
        return 0.0
    z = cap / sigma
    return sigma * _norm_pdf(z) - cap * (1.0 - _norm_cdf(z))


def _power_value_exact_convexity(self, obs, name: str) -> float:
    r = obs.round
    if name == "FORESIGHT":
        m = min(16, 4 * r)
        return 0.75 * sqrt(m) + (0.5 if obs.is_maker else 0.0)
    elif name == "SUBSTITUTE":
        # Analytical Bachelier option premium
        sigma = sqrt(max(1, self._unseen(obs)))
        return _bachelier_sub_premium(sigma, cap=2.0)
    elif name == "TRICK_ROOM":
        return 0.6 / r
    elif name == "STEALTH_ROCK":
        remaining = 5 - r + 1
        return 2.0 * 0.25 * remaining
    return 0.0


ExactConvexityAuctionBot = make_variant("ExactConvexityAuction", {
    "_power_value": _power_value_exact_convexity,
})


def main():
    print()
    print("=" * 115)
    print("TESTING ANALYTICAL BACHELIER SUBSTITUTE AUCTION VALUATION")
    print("=" * 115)

    for label, cls in [("Base v9 (heuristic)", BaseBotCls), ("v10 Exact Convexity", ExactConvexityAuctionBot)]:
        h2h = duel(cls, BaseBotCls, SEEDS, 50)
        b_scores = [(name, duel(cls, opp, SEEDS, 50).mean) for name, opp in BB.BOARD]
        b_mean = statistics.fmean([s for _, s in b_scores])
        p_scores = [(name, duel(cls, opp, SEEDS, 50).mean) for name, opp in PANEL]
        p_mean = statistics.fmean([s for _, s in p_scores])
        l_scores = [(name, duel(cls, opp, SEEDS, 50).mean) for name, opp in LIARS]
        l_mean = statistics.fmean([s for _, s in l_scores])
        print(f"  {label:<28s} | H2H: {h2h.mean:>+5.2f} | Board: {b_mean*20:>+6.1f} ({b_mean:>+5.2f}/d) | Honest: {p_mean*20:>+6.1f} | Liar: {l_mean*20:>+6.1f}")

    print("=" * 115)


if __name__ == "__main__":
    main()
