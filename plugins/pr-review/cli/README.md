# pr-review CLI

The Python implementation of `pr-review`. See `../ARCHITECTURE.md` for the full design.

## Layout

```
cli/
├── pyproject.toml          # installable; exposes `pr-review` console script
└── pr_review/              # the Python package
    ├── __init__.py
    ├── __main__.py         # supports `python -m pr_review`
    └── cli.py              # argparse + subcommand handlers
```

Modules to be added in subsequent slices: `daemon.py`, `state.py`, `diff_parser.py`, `publisher.py`, `static/` (browser UI).

## Local development install

From this directory:

```bash
pip install -e .
```

Editable install — changes to source are picked up on the next invocation without reinstalling. Exposes `pr-review` on `PATH`.

You can also run without installing:

```bash
python -m pr_review <subcommand> [args...]
```

## Status

Only the argparse skeleton exists today. All subcommand handlers are stubs that print `not yet implemented` and exit with code 2. The next implementation slice fills in `init` (fetch diff via `gh`, persist initial state, start daemon).
