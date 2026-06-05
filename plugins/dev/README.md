# dev

Engineering productivity skills.

## Skills

- **`/dev:pr-review <pr-number-or-url>`** — collaborative PR review. Fetches the PR diff, drafts comments in chat, posts as a pending GitHub review on explicit user approval, supports surgical edits via the GitHub API afterwards.

More skills planned (documentation generation, commit message formatting, etc.) — they'll live alongside this one in `skills/`.

## Layout

```
dev/
├── .claude-plugin/plugin.json
└── skills/
    └── <skill-name>/
        ├── SKILL.md
        └── (any helper scripts the skill invokes via ${CLAUDE_SKILL_DIR}/...)
```
