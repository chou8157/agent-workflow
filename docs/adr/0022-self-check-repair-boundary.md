# Auto-repair only low-risk workflow self-check failures

We decided that workflow self-checks may automatically repair low-risk structural gaps such as missing directories or empty template files. Conflicts in `AGENTS.md`, contradictory rules, major rewrites, or large structure migrations must be reported and confirmed by the user before changes are made. Unknown facts should be recorded as unknowns, not silently promoted to project truth.
