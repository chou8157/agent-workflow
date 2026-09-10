# Use explicit rule strength levels in templates

We decided that workflow templates should distinguish between `must`, `default`, `recommended`, and `forbidden` rules. Safety, permissions, Git operations, external side effects, and validation baselines should use strong language, while normal process guidance should be marked as defaults or recommendations. This prevents agents from treating every sentence as an equally rigid command.
