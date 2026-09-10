# Validation logs must record real validation only

We decided that `validation-log.md` may only record tests, commands, or manual checks that actually happened. If validation was not run, the record should say why and list recommended follow-up checks. The workflow must not treat subjective confidence or "looks fine" as a passed validation.
