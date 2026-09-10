# Record mode updates the minimum required files plus fact-triggered records

We decided that record mode must always update `30-records/progress-log.md` and `30-records/current-status.md`, while all other records are updated only when supported by facts from the task. Validation goes to `validation-log.md`, risks to `risk-log.md`, stable decisions to `decision-log.md`, known bugs to `pending-fixes.md`, and deep module reading to `15-modules/`. This avoids noisy documentation churn while keeping the project workflow recoverable.
