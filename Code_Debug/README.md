# Code Bug Fix Agent

A dependency-free Python agent that analyzes source code, applies explicitly safe fixes, imports Python modules, and runs a qualification command. SQL and Java are available as adapter targets so language-specific linters and compilers can be connected without changing the orchestration API.

## Run

```powershell
python bug_fix_agent.py path\to\project
python bug_fix_agent.py path\to\project --apply --test-command pytest -q
python bug_fix_agent.py path\to\query.sql --language sql --test-command sqlfluff lint path\to\query.sql
python bug_fix_agent.py path\to\src --language java --test-command mvn test
```

The default Python test command is `python -m unittest discover`. Use `--json` for CI integration. The process exits with code `0` only when tests pass, Python imports succeed, and no unfixed error findings remain. Warnings and unsupported-language tooling notices remain visible in the report.

## Current checks

Python checks include syntax errors, mutable default arguments, bare `except`, assertions used for runtime validation, identity comparisons against non-`None` constants, and `eval`. The only automatic rewrite currently enabled is converting `is`/`is not` value comparisons to `==`/`!=`; use `--apply` deliberately and review the resulting diff.

## Extending languages

Implement `LanguageAdapter.analyze()` and optionally `apply_safe_fixes()` for a new language, then register it in `ADAPTERS`. Keep compilation, linting, and integration testing in `--test-command` so the agent never claims production readiness without an executable verification step.
