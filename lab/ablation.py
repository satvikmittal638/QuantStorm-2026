"""Measure a power's marginal value with a free-grant clone experiment.

The subject plays an exact clone of itself.  On one chosen round, seat A is
given a specified power for zero TE and that round's ordinary auction is
replaced.  Direct and mirror legs use the same coin vector, so the residual
PnL is the power's isolated value to the subject -- not a noisy comparison of
two different strategies.

This is local research infrastructure only; it never alters the organisers'
engine or any submission file.

    python3 lab/ablation.py --power FORESIGHT --round 3
    python3 lab/ablation.py --power SUBSTITUTE --round 5 --seeds 4 --n-deals 120
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from arena import CONFIG, N_DEALS, OUR_BOT, SEEDS, Result, load_bot  # noqa: E402
import engine  # noqa: E402


def free_grant_duel(
    bot, power: str, round_number: int, seeds, n_deals: int,
    holder_role: str = "any",
) -> tuple[Result, float]:
    """Return bot A's mirror-pair residual when it alone receives `power`.

    Replacing (rather than adding to) the target auction keeps the round at
    one power slot.  Both clones observe ownership through their normal
    post-auction `Obs`; the only asymmetric intervention is A's zero-TE grant.
    """
    allowed = tuple(CONFIG.POWERS.get(power, {}).get("rounds", ()))
    if round_number not in allowed:
        raise ValueError(f"{power} is not eligible in round {round_number}")

    original_auction = engine.run_auction
    role_scale = 2.0 if holder_role in ("maker", "taker") else 1.0

    def grant_auction(bots, obs_pre, offered, te, power_state, config, sym,
                      tie_flip, r, auction_log, logs, verbose):
        matches_role = (
            holder_role == "any"
            or (holder_role == "maker" and obs_pre[0].is_maker)
            or (holder_role == "taker" and not obs_pre[0].is_maker)
        )
        if r != round_number or not matches_role:
            return original_auction(
                bots, obs_pre, offered, te, power_state, config, sym,
                tie_flip, r, auction_log, logs, verbose,
            )

        power_state.acquire(0, power, r, config)
        auction_log.append({"round": r, "seat": 0, "power": power, "cost": 0})
        if verbose:
            logs.append(f"    -> ABLATION: {bots[0].name} receives {power} for 0 TE")
        return {0: {power}, 1: set()}

    engine.run_auction = grant_auction
    try:
        pairs = []
        warnings = []
        times = []
        violations = clamps = 0
        for seed in seeds:
            match = engine.play_match(
                bot, bot, CONFIG, seed=seed, n_deals=n_deals, mirror=True,
                verbose=False, bot_a_name="grant", bot_b_name="clone",
            )
            pnl = [deal.pnl[0] for deal in match.deals]
            pairs.extend(pnl[i] + pnl[i + 1] for i in range(0, len(pnl), 2))
            warnings.extend(match.bot_a_warnings)
            times.extend(match.bot_a_times)
            violations += match.bot_a_violations
            clamps += match.bot_a_clamps
        return Result(pairs, warnings, violations, clamps, times), role_scale
    finally:
        engine.run_auction = original_auction


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot", default=OUR_BOT)
    parser.add_argument("--power", required=True, choices=sorted(CONFIG.POWERS))
    parser.add_argument("--round", required=True, type=int, dest="round_number")
    parser.add_argument(
        "--holder-role", choices=("any", "maker", "taker"), default="any",
        help="grant only in mirror legs where seat A holds this role",
    )
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--n-deals", type=int, default=120)
    args = parser.parse_args()

    result, scale = free_grant_duel(
        load_bot(args.bot, "ablation_subject"), args.power, args.round_number,
        SEEDS[:args.seeds], args.n_deals, args.holder_role,
    )
    estimate = result.mean * scale
    stderr = result.stderr * scale
    role_note = "" if args.holder_role == "any" else f" as {args.holder_role}"
    print(
        f"{os.path.basename(args.bot)} | free {args.power} R{args.round_number}{role_note}: "
        f"{estimate:+.2f} +/- {stderr:.2f} ticks per treated deal"
    )
    print(
        f"health: {result.violations} violations, {result.clamps} clamps, "
        f"{len(result.warnings)} warnings, max call {result.max_ms:.3f}ms"
    )


if __name__ == "__main__":
    main()
