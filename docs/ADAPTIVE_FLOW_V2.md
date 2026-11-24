# Adaptive Flow Intelligence V2

Research-only integration. Existing production decision, Telegram filter, and V1 selection remain unchanged. No automatic trading or deployment of a model from exploratory results.

- M00: existing flow + position control; M01: signed raw flow magnitude percentile.
- M02: AUM-normalized percentile, using each period's own beginning AUM; M03/04/05: standard, MAD, and exponentially weighted Z-scores.
- M06: adjacent-period normalized-flow acceleration, M07: within-period directional persistence, M08: COT change anomaly with normalized-flow strength, M09: same-date cross-ETF normalized-flow relative rank, M10: flow-volatility regime threshold, M12: predefined majority ensemble.
- M11: positive-flow-weighted adjusted close proxy, **not investor cost basis**. Price-dependent shadow comparator only; never eligible for the early decision engine.
- Missing values stay null, not WAIT. Each model has coverage, active count, hit rate, directional SGOV score and 10/30/50 bp cost sensitivity. Costs are assumptions, not measured execution.
- Current-vintage historical replay assumes a seven calendar day observation lag; revision and actual release timestamps are unverified. It never validates or promotes a method. No fake historical live signals. COT/cross-asset/cost proxy lacking matched historical inputs are unavailable in replay.
- Prospective observations freeze models at scan time; duplicate source dates and overlapping holding windows excluded. The candidate is selected on the first 30 chronological independent periods, compared with control on the next 20, confirmed on the next 20; no retrospective replacement after failed holdout. RESEARCH_ACCEPT is shadow research evidence only, not production or live acceptance. Dependence across assets, multiple testing, execution and actual release-clock audit still require independent review before production promotion.
- Daily workflow evaluates V2 alongside V1. ADAPTIVE.md and history/adaptive_results.json report the result; history/adaptive_replay.json is a bounded, replaceable exploratory snapshot, not the immutable prospective archive.
- Fund AUM values use the provider chart's existing scale convention. Independent AUM unit and source verification, independent backup ETF flow provider, SGOV/TBF3, commodity inventory/term structure and crypto funding remain open. AUM-normalized models cannot be promoted on this implementation alone.
