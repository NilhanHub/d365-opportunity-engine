# Contributing

Thanks for taking the time to improve this project.

## Before opening a change

1. Read the README and any repository-specific `AGENTS.md`, constitution, or governance files.
2. Open an issue for material behavior or architecture changes so scope and acceptance evidence are clear.
3. Work on a focused branch and keep unrelated changes out of the pull request.
4. Never include secrets, customer data, live operational artifacts, or machine-specific paths.

## Quality gate

Run the clean-install, lint/typecheck, test, and build commands documented in the README and mirrored by `.github/workflows/`. A contribution is ready when the relevant checks pass and the pull request explains the behavior, risk, verification evidence, and known limits.

Use synthetic fixtures, add regression coverage for fixes, and keep outward claims tied to repository evidence. Small documentation and test improvements are welcome; issues labelled `good first issue` or `help wanted` are intended to have bounded acceptance criteria.

## Commit and review style

Prefer concise conventional commits such as `feat:`, `fix:`, `docs:`, `test:`, or `chore:`. Reviewers may ask for a smaller scope, a threat-boundary explanation, or repeatable evidence before merging.
