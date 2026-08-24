"""research_suite.py — Automated high-throughput hypothesis testing engine.
Tests a variety of game-theoretic adjustments and prints clean statistical comparisons.
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

def score_variant(bot_cls, label="Variant", n_deals=60):
    print(f"\n{'='*25} TESTING: {label} {'='*25}")
    # Head to head
    h2h = duel(bot_cls, BASE_BOT_CLS, n_deals=n_deals)
    print(f"  Head-to-Head vs Base: {h2h.mean:+6.2f} +/- {h2h.stderr:4.2f}")
    
    # Honest panel
    honest_scores = {}
    for name, opp in PANEL:
        res = duel(bot_cls, opp, n_deals=n_deals)
        honest_scores[name] = res.mean
    honest_mean = statistics.fmean(honest_scores.values())
    worst_honest = min(honest_scores.items(), key=lambda kv: kv[1])
    
    # Board recon panel
    board_scores = {}
    for name, opp in BB.BOARD:
        res = duel(bot_cls, opp, n_deals=n_deals)
        board_scores[name] = res.mean
    board_mean = statistics.fmean(board_scores.values())
    worst_board = min(board_scores.items(), key=lambda kv: kv[1])

    # Liars
    liar_scores = {}
    for name, opp in LIARS:
        res = duel(bot_cls, opp, n_deals=n_deals)
        liar_scores[name] = res.mean
    liar_mean = statistics.fmean(liar_scores.values())
    worst_liar = min(liar_scores.items(), key=lambda kv: kv[1])

    print(f"  HONEST MEAN : {honest_mean:+6.2f} (Base is +7.72) | Worst: {worst_honest[0]} ({worst_honest[1]:+5.2f})")
    print(f"  BOARD RECON : {board_mean:+6.2f} (Base is +5.02) | Worst: {worst_board[0]} ({worst_board[1]:+5.2f})")
    print(f"  LIARS MEAN  : {liar_mean:+6.2f} (Base is -0.57) | Worst: {worst_liar[0]} ({worst_liar[1]:+5.2f})")
    return {
        'h2h': h2h.mean,
        'honest': honest_mean,
        'worst_honest': worst_honest,
        'board': board_mean,
        'liars': liar_mean
    }

# ── EXPERIMENT 1: Zero STEALTH_ROCK blend (strictly trust measured surface) ──
class Bot_ZeroStealth(BASE_BOT_CLS):
    def _power_value(self, obs, name: str) -> float:
        if name == "STEALTH_ROCK":
            return 0.0
        return super()._power_value(obs, name)

# ── EXPERIMENT 2: Adaptive Shading based on opponent revealed spend ──
class Bot_DynamicShade(BASE_BOT_CLS):
    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}

        opp_spent = self.config.TE_BUDGET - obs.te_theirs
        if obs.round >= 2 and opp_spent <= 1:
            effective_shade = 0.15   # Opponent is not bidding, snipe cheap
        else:
            effective_shade = 0.30

        wanted = []
        for name in offered:
            v = self._power_value(obs, name)
            if v <= 0.0:
                continue
            amount = int(v / self.config.TE_SALVAGE * effective_shade)
            amount = min(amount, int(obs.te_theirs) + 1)
            if amount > 0:
                wanted.append((v, name, amount))

        out = {}
        for _, name, amount in sorted(wanted, key=lambda t: -t[0]):
            take = min(amount, budget)
            if take <= 0:
                break
            out[name] = take
            budget -= take
        return out

# ── EXPERIMENT 3: Higher SHADE (0.40) to bank more salvage across the board ──
class Bot_Shade40(BASE_BOT_CLS):
    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}
        wanted = []
        for name in offered:
            v = self._power_value(obs, name)
            if v <= 0.0:
                continue
            amount = int(v / self.config.TE_SALVAGE * 0.40)
            amount = min(amount, int(obs.te_theirs) + 1)
            if amount > 0:
                wanted.append((v, name, amount))
        out = {}
        for _, name, amount in sorted(wanted, key=lambda t: -t[0]):
            take = min(amount, budget)
            if take <= 0:
                break
            out[name] = take
            budget -= take
        return out

# ── EXPERIMENT 4: Lower SHADE (0.20) ──
class Bot_Shade20(BASE_BOT_CLS):
    def bid(self, obs, offered):
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}
        wanted = []
        for name in offered:
            v = self._power_value(obs, name)
            if v <= 0.0:
                continue
            amount = int(v / self.config.TE_SALVAGE * 0.20)
            amount = min(amount, int(obs.te_theirs) + 1)
            if amount > 0:
                wanted.append((v, name, amount))
        out = {}
        for _, name, amount in sorted(wanted, key=lambda t: -t[0]):
            take = min(amount, budget)
            if take <= 0:
                break
            out[name] = take
            budget -= take
        return out

if __name__ == "__main__":
    score_variant(Bot_ZeroStealth, "Zero STEALTH_ROCK Blend (Pure Measured Surface)")
    score_variant(Bot_DynamicShade, "Dynamic Opponent-Aware Shading")
    score_variant(Bot_Shade40, "SHADE = 0.40")
    score_variant(Bot_Shade20, "SHADE = 0.20")
