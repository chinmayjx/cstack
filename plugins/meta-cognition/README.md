# meta-cognition

Skills for deliberate reasoning frameworks — invoked when the user wants Claude to think in a particular structured mode rather than the default conversational one.

## Layout

```
meta-cognition/
├── .claude-plugin/plugin.json
├── philosophy/                # markdown files describing the reasoning frameworks
└── skills/                    # skill definitions (none yet)
```

## philosophy/

Holds the user's own writeups of how each reasoning framework should work — what it is, when to apply it, what good output looks like, what failure modes to watch for. These are reference material, authored by the user. Skills under `skills/` will reference them.

## Status

Scaffolded. No skills yet.
