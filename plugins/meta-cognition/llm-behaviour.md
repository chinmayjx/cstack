# LLM Behaviour Observations

Patterns observed about Claude's default behaviours, worth pushing against when interacting with it. Dump.

- **MVP-shortcut tendency.** Defaults to "MVP = simpler shortcut" even when the proper version costs essentially the same effort. The shortcut version often introduces architectural debt (e.g., agent writing YAML to a known path vs. CLI owning state; LLM polling for sync vs. a hook). Right rule: if the proper version costs ~5 minutes more, do it properly.

- **Dump-the-artifact pattern.** When given a co-creation task ("I will first do the detailing here," "I want to observe this process"), produces finished deliverables in one shot instead of building incrementally with the user. Misreads delegation-of-direction as license-to-execute. Auto mode amplifies this if not actively countered.

- **Cognitive layer collapse.** Skips abstraction layers. Jumps from a flat conversation to implementation-level output without traversing user → product → architecture in between. Conflates "produce the deliverable efficiently" with "compress the layers." Real efficiency is layered output, each layer with bounded breadth (≤5 components).

- **Reads reflection as instruction.** When the user reflects on a decision ("I realised that the file is going to be architecture, and architecture can become a misnomer"), Claude infers an implicit "go do it" and executes. Can violate even an explicit "don't make any changes" on the very next turn if the message contains a decision-shaped statement.

- **Todo-list rigidity.** Creates todo lists with limited initial understanding, then becomes constrained by them. Treats the list as a contract instead of a hypothesis to revise as execution surfaces new information. Doesn't update the list mid-execution.

- **Treats verbosity as waste.** Compresses solutions into few tokens, thinking that's efficient. Real cost: the user has to either trust the compressed output or re-derive the upper layers themselves. Layered, longer output is *cheaper* in real terms because it carries the structure the user can read at the right level.

- **Counterpoint-for-the-sake-of-it.** When asked for genuine pushback, generates filler counterpoints rather than acknowledging when there isn't one. The honest "no counterpoint" is more useful than a manufactured one.

- **Pattern-matching to the meta-default.** Most failures above share a root: defaulting to a generic action ("produce the deliverable," "use the simpler version," "execute on signal") instead of attending to what the user actually wants in this specific interaction. The fix is not a new default but slowing down enough to attend.
