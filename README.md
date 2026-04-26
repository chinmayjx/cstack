# cstack

Chinmay's personal Claude Code stack — skills and tools for everyday engineering work.

## Layout

```
cstack/
├── .claude-plugin/
│   └── marketplace.json     # registers cstack as a Claude Code marketplace
├── plugins/
│   └── <plugin-name>/
│       ├── .claude-plugin/plugin.json
│       └── skills/
│           └── <skill-name>/SKILL.md
└── install.sh               # pre-flight checks; prints install commands
```

Each plugin lives in `plugins/<plugin-name>/` and is referenced from `marketplace.json`. Skills exposed by a plugin are invoked as `/<plugin-name>:<skill-name>`.

## Install

cstack registers as a **local Claude Code marketplace**. Marketplace registration and plugin install are slash commands inside Claude Code (they cannot be triggered from a shell), so `install.sh` only does pre-flight checks and prints the exact slash commands to run.

```bash
./install.sh
```

Then, once inside any Claude Code session, register the marketplace:

```
/plugin marketplace add /Users/chinmay.jain/Documents/cstack
```

After that, install any plugin listed in `marketplace.json` (the `plugins` array):

```
/plugin install <plugin-name>@cstack
```

Verify with the plugin's own skill, e.g.:

```
/<plugin-name>:<skill-name>
```

## Updating during development

After editing any `SKILL.md` or `plugin.json`:

```
/reload-plugins
```

The next prompt picks up the changes — no session restart needed.

## Adding a new plugin

1. Create `plugins/<new-plugin>/.claude-plugin/plugin.json` with `name` and `description`.
2. Create one or more `plugins/<new-plugin>/skills/<skill-name>/SKILL.md` with frontmatter (`name`, `description`, `user-invocable`).
3. Add an entry to the `plugins` array in `.claude-plugin/marketplace.json` pointing to `./plugins/<new-plugin>`.
4. `/plugin install <new-plugin>@cstack` to install, then `/reload-plugins` to pick it up.

## Removing a plugin

1. `/plugin uninstall <plugin-name>@cstack` to remove from your machine's installed state.
2. Delete `plugins/<plugin-name>/`.
3. Remove the entry from `marketplace.json`'s `plugins` array.

The marketplace's `plugins` array is the source of truth for what's *available* — keep it consistent with the filesystem.
