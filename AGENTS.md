# AGENTS.md


## Session notes and task list live in a separate repo

Session notes and the task list for this project are NOT in this repo. They live in the
private `work-notes` repo, cloned as a sibling, at `work-notes/freight-rail-data-pipeline/`:

    C:\Users\zande\PycharmProjects\work-notes\freight-rail-data-pipeline\

When Zander asks to update session notes or the task list, edit the files there, not here.
This repo keeps only durable documentation (this file, `docs/`), so it can be public
without a visitor scrolling through a working log. See `work-notes/CLAUDE.md` for the
convention.

## Bug fixes
Every time you fix a bug in this repo, add an entry to
`work-notes/freight-rail-data-pipeline/BUG_FIXES.md` (newest first, under the "Latest" heading — then move the
"Latest" heading to the new entry). Include symptom, root cause, fix,
verification, and enough detail (file/line, layout facts, error strings,
audit commands) to re-debug the issue from scratch.

## Backfill script
`scripts/backfill_bts_transborder_annual.py` handles BTS TransBorder annual
zips (2007-2017), which ship in four different layouts. Its failure modes and
layout quirks are documented in `work-notes/freight-rail-data-pipeline/BUG_FIXES.md` ("Supporting facts & reusable
checks"). Read that section before modifying the script. Never run two
backfill instances concurrently.
