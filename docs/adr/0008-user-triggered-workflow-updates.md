# Make workflow updates user-triggered by default

We decided that updates to `.agent-workflow/` should be explicitly triggered by the user rather than performed automatically during every task. This protects the workflow from noisy churn and keeps documentation changes intentional, while still allowing the skill to update records, module indexes, gates, or templates when the user asks for initialization, recording, or improvement.
