# Dashboard source health

The 25 November exports show ETFdb HTTP 403 for all 12 funds. ETFIQ observations also failed the existing freshness check. These are source availability failures, not zero flows. A successful software test does not establish live source recovery.

The dashboard now renders missing cells as an em dash while preserving numeric types and nulls in CSV exports. The adjacent explanation columns identify missing period coverage, beginning AUM, insufficient reference periods and absent validated method samples. Alternative-provider exceptions are visible in the exported table.

CFTC changes now use the selected horizon rather than repeating the weekly change for every horizon. Unavailable primary sources show a disabled method rather than implying an active default method.

ETFIQ data that pass identity, unit, calendar and continuity validation but lag more than one session can be retained for at most seven calendar days as STALE_REFERENCE. This reference is never selected as fresh, counted as available, or used in production decisions. Future, off-calendar, invalid and older data remain rejected. No source histories are spliced and no missing observation becomes zero.

Alternative horizon flow/AUM is calculated only when the source supplies positive beginning AUM on the exact applicable calendar session. Missing AUM remains unavailable; current AUM cannot substitute for historical AUM.

Unresolved upstream limitations: ETFdb access denial, ETFIQ publication lag, missing TBF3 positions and insufficient forward-test history. Production health and live continuity checks must continue to report these failures. Existing recorded reports are not rewritten. New reference fields appear after the next collector run.
