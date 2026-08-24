"""test_t6_fill_price.py — Check the exact forced fill price on Turn 6 under the patched engine.
"""

from __future__ import annotations

import os
import sys

REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps")
)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from engine import play_deal
from game_config import GameConfig
from opponents import FloorQuoter

CONFIG = GameConfig()

class T6ProbeBot:
    name = "T6Probe"
    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config

    def bid(self, obs, offered):
        return {}

    def quote(self, obs):
        return (-2, 2)  # width 4

    def respond(self, obs, quote, turn):
        bid, ask = quote
        if turn == obs.n_turns:
            return ("COUNTER", ask, ask)
        # return same quote
        w = obs.final_cap
        c = (bid + ask) // 2
        return ("COUNTER", max(bid, min(c, ask - w)), min(ask, max(bid + w, c + w)))

    def use_transform(self, obs):
        return False

deal, _, _ = play_deal(FloorQuoter(), T6ProbeBot(), coins=[1]*40, config=CONFIG, seed=7, verbose=True)
for log in deal.logs:
    print(log)
