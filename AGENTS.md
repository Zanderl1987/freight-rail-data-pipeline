# AGENTS.md

## Bug fixes
Every time you fix a bug in this repo, add an entry to
`BUG_FIXES.md` (newest first, under the "Latest" heading — then move the
"Latest" heading to the new entry). Include symptom, root cause, fix,
verification, and enough detail (file/line, layout facts, error strings,
audit commands) to re-debug the issue from scratch.

## Backfill script
`scripts/backfill_bts_transborder_annual.py` handles BTS TransBorder annual
zips (2007-2017), which ship in four different layouts. Its failure modes and
layout quirks are documented in `BUG_FIXES.md` ("Supporting facts & reusable
checks"). Read that section before modifying the script. Never run two
backfill instances concurrently.
