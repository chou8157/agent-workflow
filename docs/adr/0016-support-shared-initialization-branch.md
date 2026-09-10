# Support shared workflow initialization as a separate branch

We decided that the master skill should support creating a shared workflow directory for cross-project or multi-repo chains, but only through a distinct shared initialization branch. Ordinary project initialization should not generate shared-contract structures by default, because project governance and chain governance have different boundaries and update rules.
