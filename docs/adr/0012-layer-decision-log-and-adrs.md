# Separate lightweight decision logs from ADRs

We decided to keep `.agent-workflow/30-records/decision-log.md` for everyday lightweight decisions and reserve ADRs for decisions that are hard to reverse, surprising without context, and based on real trade-offs. This keeps routine project history easy to maintain while still preserving architectural context when future readers would otherwise wonder why a choice was made.
