# Cognitive Biases of LLMs

A working list of recurring biases in LLM behaviour, observed in practice. Useful as a reminder of what to watch for and push against in real time when interacting with one.

## Observations

1. **Q&A tendency.** Gives a complete response in one shot, treating every user turn as a self-contained query needing a finished answer.
    - Jumps to implementation; doesn't plan properly.

2. **Substrate-mismatched mimicry.** Mimics human behaviour from training data while ignoring substrate differences.
    - Drops things from the MVP for the sake of dropping, even when they could have been included cheaply.

3. **Sycophancy.** No objective position.
    - Decides whether to offer counters based on whether the user directly asked. Can passively infer to avoid giving counterpoints based on the user's tone.

4. **Recency bias.** Over-weights recently discussed material.
    - Tries to generalise from the current context and uses examples out of context.
