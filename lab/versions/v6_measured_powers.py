# Name: Satvik Mittal
# College: IIT Kanpur
# Roll Number: 240943

"""
qs_bot.py -- Divided Oracle entry.

Three ideas carry this bot, in order of measured value.

1. THE TAKER OWNS THE LAST TURN.
   N_TURNS is 6: turn 1 is the Maker's quote, then turns alternate starting
   with the Taker, so the order is maker/taker/maker/taker/maker/TAKER. The
   Taker moves last.

   A counter is clamped INSIDE the standing range and its width is bounded
   only from above, so a width-0 counter is legal. The Taker can therefore
   counter (ask, ask) on the final turn: the negotiation ends, the last
   quoter is short by MIDPOINT_SIDE_RULE, and the fill lands at exactly
   `ask`. The cost is the 2-tick forcing fee.

   So the Taker's final-turn menu is not two options but three:

       long at ask        short at bid        short at ask, minus 2

   The third dominates the second whenever the range is wider than 2 ticks,
   which it almost always is. The Taker's payoff is
   max(v - ask, ask - v - 2, bid - v) -- roughly |ask - v| - 1. It gets to
   pick its side at the ask.

   Two consequences. Never ACCEPT_SELL on the last turn. And, because that
   option is worth more than most early trades, do not trade before the last
   turn at all unless the edge clears RIDE_THRESHOLD.

2. PRICE ON E[S], NOT ON YOUR OWN COINS.
   E[S] = k_mine + (their revealed sum). An honest Maker centres its opening
   quote on its own revealed sum, so every past contract's open_bid/open_ask
   is a clean read of the opponent -- obs.contracts carries them for the whole
   deal, not just the current round.

   Quoting on E[S] rather than on k_mine does three things at once: it prices
   better, it collects the maker obligation (which is scored against a
   BASELINE `unseen` that does not know what we actually know, so knowing more
   than baseline is paid), and it means an opponent reading our midpoint as
   our own coin sum is systematically wrong.

3. WIDTH IS A TAX, AND THE STRADDLE CURVE IS A STEP FUNCTION.
   The obligation is exactly zero-EV at every width for an honest Maker, so
   WIDTH_PREMIUM is an unconditional -0.22 per tick above the floor. But the
   straddle probability is an exact lattice sum with fixed parity, so it is
   flat over stretches of width -- and once we know more than baseline, the
   payoff for straddling can outrun the premium. The width is therefore
   solved online against config.straddle_prob rather than tabulated.
"""

from __future__ import annotations

import random
from math import comb

# -- Tunables --------------------------------------------------------
# Kept as named constants so they can be swept; every one of them is
# measured on the sparring panel rather than chosen.

#: How much of the CURRENT SPREAD an early trade must be worth before we take
#: it instead of riding to the final turn.
#:
#: This used to be a flat 2.0 ticks, swept on the panel. A constant is the
#: wrong shape. What we give up by trading early is the last-turn option, and
#: that option is worth roughly |ask - v| - 1, which is bounded by the spread
#: on the table -- so the bar should scale with the spread, not sit still.
#: Against a wide quote there is a lot of option to give up and we should hold
#: out; against a tight one there is almost none, and refusing a real edge just
#: hands the fill to an opponent who quotes tightly on purpose.
#:
#: Measured at 0.8 (5 seeds x 100 mirrored deals), against the flat 2.0:
#:   honest panel   +6.56 -> +6.94
#:   worst matchup  +0.62 -> +1.98   (the floor, which is what loses matches)
#:   board recons   +2.71 -> +3.62
#:   liars          -3.04 -> -2.85
#: Positive on every group at once, which is the evidence profile the
#: reverted belief-layer change never had.
RIDE_FRACTION = 0.8

#: Extra variance charged to a quote-derived read of the opponent, in
#: coin-units. A Maker is under no obligation to quote honestly, so a read
#: is never as good as a FORESIGHT leak of the same age.
READ_NOISE = 2.0

#: How much of a read we believe when sizing our own quote width. 1.0
#: treats the opponent as perfectly honest.
READ_TRUST = 1.0

#: Fraction of fair value to bid in a first-price auction. Shading is
#: mandatory: you pay your own bid, so bidding true value captures nothing.
SHADE = 0.30

#: What each power is worth to THIS bot, in ticks, per round. MEASURED, not
#: guessed and not copied: each cell is a free-grant ablation run in
#: lab/ -- grant the power to one seat in one round, both seats otherwise the
#: same bot, 4 seeds x 120 mirrored deals. Two identical bots net exactly
#: 0.00 over a mirrored match, so the residual IS the power's value.
#:
#: Three of these overturn what the bot previously assumed:
#:
#:   STEALTH_ROCK is worth EXACTLY ZERO in every round. It shifts forced
#:   fills, and this bot almost never reaches one (2-4% of rounds against
#:   competent opponents). The old model priced it at 0.60-1.50 and was
#:   buying it every time it appeared.
#:
#:   SUBSTITUTE RISES through the deal (+1.34 -> +2.55), because the swings
#:   it caps are biggest in round 5 when the score is nearly determined. The
#:   old model had it falling, which is backwards.
#:
#:   TRANSFORM is worth ZERO at best. Measured under every decision rule:
#:   never-fire 0.00, always-fire 0.00, and every CONDITIONAL rule strictly
#:   negative (-0.26, -1.28, +0.10 for fire-when-flat). The swap is EV-neutral
#:   by symmetry, and conditioning on our own hand only adds variance. So we
#:   do not buy it and we do not fire it.
POWER_TICKS = {
    "FORESIGHT":    {1: 1.54, 2: 1.32, 3: 2.38, 4: 3.14, 5: 1.49},
    "TRICK_ROOM":   {1: 0.42, 2: 0.31, 3: 0.09, 4: 0.00, 5: 0.00},
    "SUBSTITUTE":   {1: 1.34, 2: 1.26, 3: 1.39, 4: 1.67, 5: 2.55},
    "STEALTH_ROCK": {1: 0.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
    "TRANSFORM":    {1: 0.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
}

#: Revealed-sum magnitude at or below which a hand is "flat" -- worth
#: trading away, because it tells us nothing the prior did not.
FLAT = 1


class Bot:
    name = "QS"

    # -- lifecycle ---------------------------------------------------

    def reset(self, seat: int, config, seed: int) -> None:
        # Kept short and total on purpose: a reset() that raises forfeits
        # every remaining action in the deal, which is the most expensive
        # failure in the table.
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self.reads: dict[int, float] = {}   # round -> their revealed sum
        self.opp_bids = 0                   # powers they have won this deal

    # -- belief ------------------------------------------------------

    def _refresh(self, obs) -> None:
        """Harvest opponent opening quotes from every contract so far.

        Only the OPENING quote is a clean read; later ranges are negotiated
        objects contaminated by both sides. The reference bots latch only
        the current round's quote and so have no read at all in the rounds
        where they are the Maker -- exactly when it is worth most.
        """
        for c in obs.contracts:
            if c.maker_seat != self.seat and c.round not in self.reads:
                self.reads[c.round] = (c.open_bid + c.open_ask) / 2.0
        for e in obs.auction_log:
            pass  # tape is read in _power_value; nothing to cache here

    def _their_k(self, obs):
        """Estimate the opponent's revealed sum, with its variance.

        Two independent sources, combined by inverse variance:

          FORESIGHT -- we are shown min(16, 4r) of their 4r revealed coins.
            The ones we were not shown are still mean-zero, so the raw
            sample sum is the honest estimator (scaling it up to hand size
            is unbiased but far noisier). In rounds 1-4 the leak covers
            their whole revealed hand, so this is exact.

          A QUOTE READ -- their opening midpoint at some earlier round r0.
            Their sum has drifted by the 4*(r - r0) coins revealed since,
            and the quote itself may be dishonest.

        Returns (estimate, variance), or None when we have neither.
        """
        parts = []

        n = len(obs.foresight)
        if n:
            parts.append((float(sum(obs.foresight)), float(4 * obs.round - n)))

        if self.reads:
            r0 = max(self.reads)
            parts.append((self.reads[r0], 4.0 * (obs.round - r0) + READ_NOISE))

        if not parts:
            return None

        for est, var in parts:
            if var <= 0.0:
                return est, 0.0          # exact; nothing else can improve it

        wsum = sum(1.0 / var for _, var in parts)
        est = sum(e / var for e, var in parts) / wsum
        return est, 1.0 / wsum

    def _est(self, obs) -> float:
        """E[S] given everything we know. Their unrevealed coins are
        mean-zero, and so are ours, so they drop out."""
        tk = self._their_k(obs)
        return float(obs.k_mine) + (tk[0] if tk else 0.0)

    def _unseen(self, obs) -> int:
        """Coins whose sum we genuinely cannot pin down.

        Ours that are still hidden, plus theirs that our best source does
        not cover. This is what our TRUE straddle rate is a function of --
        the obligation prices us at the baseline instead, and pays us the
        difference.
        """
        cfg = self.config
        mine_left = cfg.N_PRIVATE - cfg.REVEAL_PER_ROUND * obs.round
        theirs = cfg.N_PRIVATE

        n = len(obs.foresight)
        if n:
            theirs = min(theirs, cfg.N_PRIVATE - n)
        if self.reads:
            r0 = max(self.reads)
            known = READ_TRUST * cfg.REVEAL_PER_ROUND * r0
            theirs = min(theirs, cfg.N_PRIVATE - known)

        return max(0, int(round(mine_left + theirs)))

    def _shift(self, obs) -> int:
        """Net tick shift on a forced fill, from our point of view.

        engine.shift_sources does this, but `engine` is not an importable
        module for a submission, so it is reimplemented from config.POWERS.
        Each holder's shift moves the price in their own favour, so opposing
        holders cancel and the sign works out the same whichever side of the
        fill we end up on.
        """
        total = 0
        for name in ("TRICK_ROOM", "STEALTH_ROCK"):
            spec = self.config.POWERS.get(name)
            if not spec:
                continue
            mag = int(spec["magnitude"])
            if name in obs.powers_mine:
                total += mag
            if name in obs.powers_theirs:
                total -= mag
        return total

    # -- quoting -----------------------------------------------------

    def _cover(self, m: int, a: int, b: int) -> float:
        """P(a <= Y <= b) for Y a sum of `m` fair +-1 coins.

        Y has the parity of m, so half the integers in [a, b] carry no mass at
        all -- which is the whole reason the alignment of a quote matters and
        the reason this is computed exactly rather than from a normal
        approximation.
        """
        if m <= 0:
            return 1.0 if a <= 0 <= b else 0.0
        total = 0
        for j in range(a, b + 1):
            if (j - m) % 2:
                continue                     # wrong parity: Y cannot land here
            k = (j + m) // 2
            if 0 <= k <= m:
                total += comb(m, k)
        return total / (1 << m)

    def _best_width(self, obs) -> int:
        """Solve the opening width against the obligation, online.

        EV(w) = MAKER_OBLIGATION * (p_true(w) - p_baseline(w))
                - WIDTH_PREMIUM * (w - floor)

        p_baseline is what the engine charges us at; p_true is what our
        actual information achieves. For a Maker who knows only its own
        coins the two are equal and the floor wins by default. With a read
        or a leak the difference can outrun the premium -- in round 5 with
        a read it does, and the answer stops being the floor.
        """
        cfg = self.config
        r, floor, cap = obs.round, obs.final_cap, obs.spread_cap
        unseen = self._unseen(obs)

        best_w, best_ev = floor, None
        for w in range(floor, cap + 1):
            try:
                p_base = cfg.straddle_prob(r, w)
                p_true = cfg.straddle_prob(r, w, unseen=unseen)
            except Exception:
                return floor
            ev = (cfg.MAKER_OBLIGATION * (p_true - p_base)
                  - cfg.WIDTH_PREMIUM * (w - floor))
            if best_ev is None or ev > best_ev:
                best_ev, best_w = ev, w
        return best_w

    def quote(self, obs):
        """Solve width and alignment together against the obligation.

        The obligation pays MAKER_OBLIGATION * (our true straddle rate - the
        rate the engine PRICES us at) minus the width premium. The engine
        prices us at config.straddle_prob(r, w), which assumes a canonically
        aligned quote and a Maker who knows only its own coins. We are neither
        -- we align to the parity of S and we have a read -- so the true rate
        is computed here and the width is chosen against the real difference.

        Solving alignment and width jointly rather than aligning after the
        fact is worth doing: the parity gain is bigger at some widths than
        others, so it changes which width wins.
        """
        self._refresh(obs)
        cfg = self.config
        v = int(round(self._est(obs)))
        r, floor, cap = obs.round, obs.final_cap, obs.spread_cap
        unseen = self._unseen(obs)

        best_ev, best_lo, best_w = None, v - floor // 2, floor
        for w in range(floor, cap + 1):
            lo = v - w // 2
            if lo % 2:
                lo += 1                      # S is always even; see _cover
            try:
                priced = cfg.straddle_prob(r, w)
            except Exception:
                continue
            true_p = self._cover(unseen, lo - v, lo - v + w)
            ev = (cfg.MAKER_OBLIGATION * (true_p - priced)
                  - cfg.WIDTH_PREMIUM * (w - floor))
            if best_ev is None or ev > best_ev:
                best_ev, best_lo, best_w = ev, lo, w

        return (best_lo, best_lo + best_w)

    # -- negotiating -------------------------------------------------

    def respond(self, obs, quote, turn: int):
        self._refresh(obs)
        bid, ask = quote

        # The current round's opening quote reaches us on turn 2 and only
        # on turn 2; after that the range has been touched by both sides.
        if turn == 2 and not obs.is_maker and obs.round not in self.reads:
            self.reads[obs.round] = (bid + ask) / 2.0

        v = self._est(obs)
        fee = self.config.FORCED_FILL_FEE

        # -- the last turn --
        # Only the Taker ever sees this, because the Taker moves last.
        if turn >= obs.n_turns:
            force_px = ask + self._shift(obs)
            options = (
                (v - ask, "ACCEPT_BUY"),
                (bid - v, "ACCEPT_SELL"),
                (force_px - v - fee, ("COUNTER", ask, ask)),
            )
            return max(options, key=lambda o: o[0])[1]

        # -- every earlier turn --
        # Ride. An early fill has to beat the option we are holding, and that
        # option is bounded by the spread still on the table, so the bar is a
        # fraction of the spread rather than a constant. SUBSTITUTE caps this
        # round's loss at 2, which makes crossing cheap, so it lowers the bar.
        bar = RIDE_FRACTION * (ask - bid)
        if "SUBSTITUTE" in obs.powers_mine:
            bar -= float(self.config.POWERS["SUBSTITUTE"]["magnitude"])

        edge_buy, edge_sell = v - ask, bid - v
        if edge_buy > bar and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > bar:
            return "ACCEPT_SELL"

        # Otherwise shrink toward our own estimate. Centring is deliberate:
        # steering the range away from our value fattens our own last-turn
        # option, but it measured badly against opponents who price well,
        # and this bot is not built to be right only against weak ones.
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        c = max(bid, min(int(round(v)), ask - w))
        return ("COUNTER", c, c + w)

    # -- the auction -------------------------------------------------

    def _power_value(self, obs, name: str) -> float:
        """What holding `name` for this round is worth to US, in ticks.

        Straight off the measured surface. An unknown power (a rotated spec)
        falls back to a deliberately timid 0.5: being wrong low costs one
        auction, being wrong high costs the budget for the rest of the deal.
        """
        row = POWER_TICKS.get(name)
        if row is None:
            return 0.5
        return row.get(obs.round, 0.0)

    def bid(self, obs, offered):
        """Blind first-price bids, allocated against a budget that is spent
        for the whole deal once it is gone.

        The budget rule is unforgiving and was tightened mid-competition: a
        vector totalling more than te_mine is no longer rescaled to fit, it
        is ZEROED, and the opponent takes the power uncontested for whatever
        they bid. So the allocation is done greedily against a running
        balance and can never exceed it by construction -- there is no
        arithmetic here that has to come out right for the bid to be legal.
        """
        budget = int(obs.te_mine)
        if not offered or budget <= 0:
            return {}

        # Price every offered power first, then spend on the best ones.
        wanted: list[tuple[float, str, int]] = []
        for name in offered:
            v = self._power_value(obs, name)
            if v <= 0.0:
                continue

            # A tick is worth 1 / TE_SALVAGE energy, so that is the exchange
            # rate between the auction and the salvage at the end of the
            # deal. Shade it: this is first price and we pay our own bid.
            amount = int(v / self.config.TE_SALVAGE * SHADE)

            # Never offer more than can possibly be needed. They cannot
            # outbid their own remaining balance, and te_theirs is exact.
            amount = min(amount, int(obs.te_theirs) + 1)
            if amount > 0:
                wanted.append((v, name, amount))

        # Spend in descending value order against the running balance. If
        # the budget runs short the cheap power is dropped rather than every
        # bid being shaved -- a shaved bid loses the auction anyway, and pays
        # for the privilege.
        out: dict[str, int] = {}
        for _, name, amount in sorted(wanted, key=lambda t: -t[0]):
            take = min(amount, budget)
            if take <= 0:
                break
            out[name] = take
            budget -= take

        return out

    # -- transform ---------------------------------------------------

    def use_transform(self, obs) -> bool:
        """Decline, always.

        Measured, not assumed. Granting TRANSFORM free to one seat and
        mirroring the match: never-fire scores 0.00, always-fire scores 0.00,
        and every conditional rule scores NEGATIVE -- fire-when-flat runs
        -0.26/-1.28/+0.10 across rounds 1-3, and a relative-hand-strength rule
        is worse still. The swap is EV-neutral by symmetry, so conditioning on
        our own hand adds variance and nothing else.

        The power is consumed either way, so declining is still the defence
        that stops the opponent buying it -- we simply never pay for it.
        """
        return False
