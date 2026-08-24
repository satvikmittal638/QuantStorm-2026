"""validate_mechanics.py — Comprehensive validation script for the Convexity & Shift Mechanics Bot.
"""

from __future__ import annotations

import math
import os
import sys

REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quantstorm-ps")
)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from engine import play_match
from game_config import GameConfig
from arena import load_bot, duel, SEEDS
from opponents import PANEL
from experiment_game_mechanics import Bot_GameMechanics

CONFIG = GameConfig()

def test_validation():
    print("Testing tournament conditions and timing...")
    # Self-play must be 0.00
    res_sp = duel(Bot_GameMechanics, Bot_GameMechanics, n_deals=100)
    print(f"Self-play (must be 0.00): {res_sp.mean:+.9f} (OK)")
    assert abs(res_sp.mean) < 1e-7, "Self-play non-zero!"
    
    # Timing
    print(f"Average latency per call : {res_sp.avg_ms * 1000:.3f} microseconds (Limit is 2000 us)")
    print(f"Max latency single call  : {res_sp.max_ms * 1000:.3f} microseconds (Limit is 50000 us)")
    print(f"Violations: {res_sp.violations}, Clamps: {res_sp.clamps}, Warnings: {len(res_sp.warnings)}")
    assert res_sp.violations == 0, "Timing violations detected!"
    assert res_sp.clamps == 0, "Clamps detected!"

if __name__ == "__main__":
    test_validation()
