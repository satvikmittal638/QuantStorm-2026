"""experiment_game_theory.py — Testing specific game-theoretic edge cases:
1. Turn 5 Maker Defense: Collapsing spread on T5 to defuse Taker's T6 forced-fill trap
2. Round 5 Zero-Variance Exploitation: Exploit the exact known hand in Round 5
3. Dynamic / Adaptive Shading in the Auction
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
from opponents import PANEL

CONFIG = GameConfig()
BASE_BOT_CLS = load_bot("lab/bot/qs_bot.py", "base_bot")

class Bot_T5_Collapse(BASE_BOT_CLS):
    """Experiment 1: Maker at Turn 5 collapses the spread to (v, v)
    to neutralize Taker's T6 forced-sell option."""
    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote
        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE

        # Last turn (Taker at T6)
        if turn >= obs.n_turns:
            force_px = ask + self._shift(obs)
            options = (
                (v - ask, "ACCEPT_BUY"),
                (bid - v, "ACCEPT_SELL"),
                (force_px - v - fee, ("COUNTER", ask, ask)),
            )
            return max(options, key=lambda o: o[0])[1]

        # Maker at Turn 5 (obs.is_maker and turn == 5)
        # Collapsing to round(v) kills their option.
        if obs.is_maker and turn == obs.n_turns - 1:
            c = max(bid, min(int(round(v)), ask))
            return ("COUNTER", c, c)

        bar = 0.8 * (ask - bid)
        if "SUBSTITUTE" in obs.powers_mine:
            bar -= float(self.config.POWERS["SUBSTITUTE"]["magnitude"])

        edge_buy, edge_sell = v - ask, bid - v
        if edge_buy > bar and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > bar:
            return "ACCEPT_SELL"

        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)


class Bot_R5_ZeroVariance(BASE_BOT_CLS):
    """Experiment 2: In Round 5, we have seen all 20 coins.
    We know k_mine with 0 variance. If we also have foresight or quotes,
    our estimate of S is extremely sharp."""
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

        # In round 5, variance is lowest. If edge is positive and beats small margin, take it earlier
        if obs.round == 5:
            bar = 0.3 * (ask - bid)
        else:
            bar = 0.8 * (ask - bid)

        if "SUBSTITUTE" in obs.powers_mine:
            bar -= float(self.config.POWERS["SUBSTITUTE"]["magnitude"])

        edge_buy, edge_sell = v - ask, bid - v
        if edge_buy > bar and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > bar:
            return "ACCEPT_SELL"

        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)


def evaluate_variant(name, bot_cls):
    print(f"\n{'='*20} EVALUATING: {name} {'='*20}")
    # 1. Head to head vs BASE
    h2h = duel(bot_cls, BASE_BOT_CLS, n_deals=60)
    print(f"Head-to-Head vs Current Base: {h2h.mean:+6.2f} +/- {h2h.stderr:4.2f}")
    
    # 2. Honest Panel
    honest_scores = []
    for opp_name, opp_cls in PANEL:
        res = duel(bot_cls, opp_cls, n_deals=60)
        honest_scores.append(res.mean)
        print(f"  vs {opp_name:<18}: {res.mean:+6.2f} +/- {res.stderr:4.2f}")
    mean_honest = statistics.fmean(honest_scores)
    print(f"--> Honest Panel Mean: {mean_honest:+6.2f} (Base is +7.72)")

if __name__ == "__main__":
    evaluate_variant("T5 Maker Collapse (Defuse T6)", Bot_T5_Collapse)
    evaluate_variant("R5 Lower Ride Bar (Low Variance)", Bot_R5_ZeroVariance)
