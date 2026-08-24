"""experiment_centering.py — Testing counter placement geometry.
Does centering counters around v (symmetric [v - w//2, v + w//2]) beat the current [v, v + w]?
"""

from __future__ import annotations

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

class Bot_SymmetricCounter(BASE_BOT_CLS):
    """Centers the counter symmetrically around v: [v - w//2, v - w//2 + w]."""
    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote
        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE

        if turn >= obs.n_turns:
            force_px = ask + self._shift(obs)
            options = (
                (v - ask, "ACCEPT_BUY"),
                (bid - v, "ACCEPT_SELL"),
                (force_px - v - fee, ("COUNTER", ask, ask)),
            )
            return max(options, key=lambda o: o[0])[1]

        bar = 0.8 * (ask - bid)
        if "SUBSTITUTE" in obs.powers_mine:
            bar -= float(self.config.POWERS["SUBSTITUTE"]["magnitude"])

        edge_buy, edge_sell = v - ask, bid - v
        if edge_buy > bar and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > bar:
            return "ACCEPT_SELL"

        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        # Symmetrically center counter around v:
        lo = int(round(v)) - w // 2
        c = max(bid, min(lo, ask - w))
        return ("COUNTER", c, c + w)

class Bot_DirectionalCounter(BASE_BOT_CLS):
    """Biases the counter range in our favor based on whether we lean long or short."""
    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote
        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE

        if turn >= obs.n_turns:
            force_px = ask + self._shift(obs)
            options = (
                (v - ask, "ACCEPT_BUY"),
                (bid - v, "ACCEPT_SELL"),
                (force_px - v - fee, ("COUNTER", ask, ask)),
            )
            return max(options, key=lambda o: o[0])[1]

        bar = 0.8 * (ask - bid)
        if "SUBSTITUTE" in obs.powers_mine:
            bar -= float(self.config.POWERS["SUBSTITUTE"]["magnitude"])

        edge_buy, edge_sell = v - ask, bid - v
        if edge_buy > bar and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > bar:
            return "ACCEPT_SELL"

        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        mid = (bid + ask) / 2.0
        if v > mid:
            # We think asset is high -> want to buy cheap or make ask high
            c = max(bid, min(int(round(v)) - w // 2, ask - w))
        else:
            c = max(bid, min(int(round(v)) - w // 2, ask - w))
        return ("COUNTER", c, c + w)

def run_tests():
    print("Testing Counter Geometry Experiments...")
    for label, cls in [("Symmetric Counter [v - w//2, v + w//2]", Bot_SymmetricCounter)]:
        print(f"\n{'='*20} {label} {'='*20}")
        h2h = duel(cls, BASE_BOT_CLS, n_deals=60)
        print(f"H2H vs Base: {h2h.mean:+6.2f} +/- {h2h.stderr:4.2f}")
        
        honest = [duel(cls, opp, n_deals=60).mean for _, opp in PANEL]
        print(f"Honest Mean: {statistics.fmean(honest):+6.2f} (Base is +7.72)")
        
        board = [duel(cls, opp, n_deals=60).mean for _, opp in BB.BOARD]
        print(f"Board Mean : {statistics.fmean(board):+6.2f} (Base is +5.02)")
        
        liars = [duel(cls, opp, n_deals=60).mean for _, opp in LIARS]
        print(f"Liars Mean : {statistics.fmean(liars):+6.2f} (Base is -0.57)")

if __name__ == "__main__":
    run_tests()
