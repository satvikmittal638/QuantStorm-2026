"""deep_research.py — Mass simulation, log mining, dumb bot stress tests,
and component isolation for QuantStorm 2026.
"""

from __future__ import annotations

import collections
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
from arena import load_bot, resolve
from opponents import PANEL, _Base, adaptive_POWER_VALUES

CONFIG = GameConfig()
OUR_BOT_CLS = load_bot("lab/bot/qs_bot.py", "our_qs_bot")

# ── 1. The DUMB BOTS / EXTREME PERSONALITIES ──────────────────────────

class Coward(_Base):
    """Always quotes the maximum possible width every round."""
    name = "TheCoward"
    width_mode = "cap"
    bid_mode = "none"

class Maniac(_Base):
    """Dumps entire TE budget in Round 1 on whatever is offered."""
    name = "TheManiac"
    width_mode = "floor"
    
    def bid(self, obs, offered):
        if not offered or obs.te_mine <= 0:
            return {}
        return {offered[0]: obs.te_mine}

class StubbornMule(_Base):
    """Never accepts an offer early, rides every round and forces Turn 6."""
    name = "TheStubbornMule"
    width_mode = "floor"
    bid_mode = "snipe"
    ride = True
    use_t6 = True
    
    def respond(self, obs, quote, turn):
        bid, ask = quote
        if turn == obs.n_turns:
            return ("COUNTER", ask, ask)
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        c = (bid + ask) // 2
        return ("COUNTER", max(bid, min(c, ask - w)), min(ask, max(bid + w, c + w)))

DUMB_BOTS = [
    ("TheCoward", Coward),
    ("TheManiac", Maniac),
    ("TheStubbornMule", StubbornMule),
]


# ── 2. MASS SIMULATION & LOG MINING ───────────────────────────────────

def run_mass_simulation(n_deals_per_seed=60, seeds=(7, 11, 23, 41, 97)):
    """Simulate matches against diverse opponents and dissect every tick of PnL."""
    print("=" * 80)
    print("MASS SIMULATION & LOG MINING ENGINE")
    print("=" * 80)
    
    opponents = PANEL + DUMB_BOTS
    
    stats_by_opp = {}
    stats_by_round = collections.defaultdict(lambda: {
        'count': 0, 'pnl': 0.0, 'contract_pnl': 0.0, 'obligation_pnl': 0.0,
        'forcing_pnl': 0.0, 'substitute_pnl': 0.0,
        'fill_types': collections.Counter()
    })
    
    # Detailed log mining on losses and wins
    big_loss_deals = []
    big_win_deals = []

    for opp_name, opp_cls in opponents:
        opp_pnl = 0.0
        contract_pnl = 0.0
        ob_pnl = 0.0
        forcing_pnl = 0.0
        salvage_pnl = 0.0
        deals_count = 0
        
        for sd in seeds:
            m = play_match(OUR_BOT_CLS, opp_cls, CONFIG, seed=sd, n_deals=n_deals_per_seed, mirror=True)
            for deal in m.deals:
                deals_count += 1
                p0 = deal.pnl[0]
                opp_pnl += p0
                
                # Salvage
                te0, te1 = deal.te_left
                salv = CONFIG.TE_SALVAGE * (te0 - te1)
                salvage_pnl += salv
                
                # Contracts
                for r_idx, c in enumerate(deal.contracts):
                    r_num = c.round
                    
                    # Contract PnL
                    if c.long_seat == 0:
                        cpnl = float(deal.score - c.price)
                    else:
                        cpnl = float(c.price - deal.score)
                    contract_pnl += cpnl
                    
                    # Forcing fee
                    ff = 0.0
                    if c.forced:
                        if c.forcer == 0:
                            ff = -float(CONFIG.FORCED_FILL_FEE)
                        elif c.forcer == 1:
                            ff = float(CONFIG.FORCED_FILL_FEE)
                    forcing_pnl += ff
                    
                    # Obligation
                    ob = 0.0
                    floor = CONFIG.final_cap(r_num)
                    p_w = CONFIG.straddle_prob(r_num, c.open_ask - c.open_bid)
                    if c.maker_seat == 0:
                        hit = (c.open_bid <= deal.score <= c.open_ask)
                        if hit:
                            ob += CONFIG.MAKER_OBLIGATION * (1.0 - p_w)
                        else:
                            ob -= CONFIG.MAKER_OBLIGATION * p_w
                        ob -= CONFIG.WIDTH_PREMIUM * ((c.open_ask - c.open_bid) - floor)
                    else:
                        hit = (c.open_bid <= deal.score <= c.open_ask)
                        if hit:
                            ob -= CONFIG.MAKER_OBLIGATION * (1.0 - p_w)
                        else:
                            ob += CONFIG.MAKER_OBLIGATION * p_w
                        ob += CONFIG.WIDTH_PREMIUM * ((c.open_ask - c.open_bid) - floor)
                    ob_pnl += ob
                    
                    # Round stats
                    sr = stats_by_round[r_num]
                    sr['count'] += 1
                    sr['pnl'] += (cpnl + ff + ob)
                    sr['contract_pnl'] += cpnl
                    sr['obligation_pnl'] += ob
                    sr['forcing_pnl'] += ff
                    sr['fill_types']['forced' if c.forced else 'agreed'] += 1
                    
        stats_by_opp[opp_name] = {
            'mean': opp_pnl / deals_count,
            'contract': contract_pnl / deals_count,
            'obligation': ob_pnl / deals_count,
            'forcing': forcing_pnl / deals_count,
            'salvage': salvage_pnl / deals_count,
            'deals': deals_count
        }

    print("\n[1] FULL SETTLEMENT DECOMPOSITION BY OPPONENT (ticks/deal):")
    print(f"{'Opponent':<20} | {'Total':>7} | {'Contract':>8} | {'Oblig':>7} | {'Forcing':>7} | {'Salvage':>7}")
    print("-" * 75)
    for opp_name, s in stats_by_opp.items():
        print(f"{opp_name:<20} | {s['mean']:+7.2f} | {s['contract']:+8.2f} | {s['obligation']:+7.2f} | {s['forcing']:+7.2f} | {s['salvage']:+7.2f}")

    print("\n[2] ROUND-BY-ROUND BREAKDOWN (averaged across ALL matchups):")
    print(f"{'Round':<6} | {'Total Deals':>11} | {'Total PnL':>10} | {'Contract PnL':>12} | {'Oblig PnL':>10} | {'Forcing PnL':>11} | {'Forced %':>8}")
    print("-" * 85)
    for r in range(1, 6):
        sr = stats_by_round[r]
        cnt = sr['count']
        forced_pct = (sr['fill_types']['forced'] / cnt) * 100 if cnt else 0
        print(f"R{r:<5} | {cnt:>11} | {sr['pnl']/cnt:+10.2f} | {sr['contract_pnl']/cnt:+12.2f} | {sr['obligation_pnl']/cnt:+10.2f} | {sr['forcing_pnl']/cnt:+11.2f} | {forced_pct:>7.1f}%")

if __name__ == "__main__":
    run_mass_simulation(n_deals_per_seed=60)
