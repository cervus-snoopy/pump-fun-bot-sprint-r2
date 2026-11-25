[![make.fun](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![rank](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/cervus-snoopy/pump-fun-bot-sprint-r2/rank.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![reward](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/cervus-snoopy/pump-fun-bot-sprint-r2/reward.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)

# Pump.fun Bot Sprint R2 — Late-Curve Completion Rider (v4)

A deterministic replay bot for the `pumpfun-replay/v2` harness. It trades the
late-curve leg of pump.fun coins: enter when real quote reserves cross 30 SOL
(tier 1, 0.10 SOL) or 20 SOL (tier 2, 0.05 SOL), only when the coin looks
organic — fewer than 60 unique buyers so far and the creator net-bought under
0.2 SOL. Stops are anchored to the **fill price** (quote paid / tokens
received), not the decision price: hard stop −10%, wide trailing stop (arm
+30%, exit on −20% from peak), stale exit after 8,000 slots. Sell orders use
wide 5,000 bps slippage so exits actually fill in a crash. Integer math only,
no clock, no randomness; the action log is byte-identical across runs.

## Honest dev results (kit v2 window, 24h, 1,222 coins, 35 completions)

| version | net PnL | fills | coins | win rate | guardrails |
|---|---|---|---|---|---|
| v1 (decision-price stops) | −0.061 SOL | 5 | 5 | 0% | FAIL (<20 coins) |
| v2 (+ trail, fill-anchored) | −0.270 SOL | 61 | 28 | 18.8% | pass |
| v3 (no trail) | −0.729 SOL | 33 | 18 | 0% | FAIL |
| **v4 (wide trail, 5,000 bps sells, buyers-only filter)** | **−0.880 SOL** | **145** | **66** | **21.1%** | pass |

**Verdict: NOT LAYAK — do not submit.** Every version loses on the kit v2 dev
window, and fill-based backtests of six further angles (rq 5–60 thresholds,
second-wind scalp, creator-exit, early buys, dip-bounce) all come out
negative on this window. Two structural findings explain why:

1. **28 of 35 completions are atomic one-slot pumps** (creator + 6 wallets,
   fixed ladder 0.1 → 85 SOL real quote in a single slot, create → first buy
   = 0 slots). No reactive bot can buy before them; a fill 2 slots later
   lands after completion and is rejected.
2. **The 7 slow completers are drowned out** by ~70 non-completer runners
   that pump to 30+ SOL real quote and then crash to ~0.15×. The buyers<60
   filter selects the atomic pumps (7 buyers), not the slow organic
   completers (250–1,000 buyers).

The field leaders' +1.07 / +0.815 SOL titles were scored on the **kit v1
window** (a different dataset, submitted 22:10–22:12 UTC 24 Nov, before the
v2 kit); they are not a v2-window benchmark. The final grading window is 6h
of new chain data after entries close (28 Nov 15:00 WIB).

## Run

```sh
node <kit>/cli/makefun.mjs grade-local --kit <kit> --bot . --driver process
```

## License

MIT. The `vendor/makefun_bot.py` SDK is copied byte-identical from the
official kit.
