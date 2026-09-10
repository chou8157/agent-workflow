# Use a single master skill

We decided to package the workflow system as one master skill rather than multiple smaller skills. A single entry point keeps the user-facing surface area small while still allowing the skill to enforce internal modes, layered documentation, and progressive disclosure. The trade-off is that the skill must be more disciplined internally, but that is preferable to fragmenting the workflow across many loosely coordinated skills.
