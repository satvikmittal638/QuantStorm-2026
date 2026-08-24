"""experiment_t4_prep.py — Turn 4 Taker preparation for Turn 6 forced fill.
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

class Bot_T4_PushAsk(BASE_BOT_CLS):
    """When Taker on Turn 4, if we intend to ride/force on T6 and v < (bid+ask)/2,
    we push the ask to ask (c = ask - w) so our T6 short-at-ask is fatter."""
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
        
        # If we are Taker on Turn 4 (turn == 4 and not obs.is_maker)
        if turn == 4 and not obs.is_maker:
            if v <= (bid + ask) / 2.0:
                c = ask - w
            else:
                c = bid
        else:
            c = max(bid, min(int(round(v)), ask - w))

        c = max(bid, min(c, ask - w))
        return ("COUNTER", c, c + w)

def run_tests():
    print("Testing Turn 4 Taker Strategy...")
    cls = Bot_T4_PushAsk
    h2h = duel(cls, BASE_BOT_CLS, n_deals=60)
    print(f"H2H vs Base: {h2h.mean:+6.2f} +/- {h2h.stderr:4.2f}")
    
    honest = [duel(cls, opp, n_deals=60).mean for _, opp in PANEL]
    print(f"Honest Mean: {statistics.fmean(honest):+6.2f} (Base is +7.72)")
    
    board = [duel(cls, opp, n_deals=60).mean for _, opp in BB.BOARD]
    print(f"Board Mean : {statistics.fmean(board):+6.2f} (Base is +5.02)")

if __name__ == "__main__":
    run_tests()
