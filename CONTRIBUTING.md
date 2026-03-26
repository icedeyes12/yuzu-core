# Contributing to yuzu-companion

Thank you for your interest in contributing! Please read the following guidelines before submitting a pull request.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/icedeyes12/yuzu-companion.git
cd yuzu-companion

# Install dependencies
pip install -r requirements.txt

# Run the bot
python main.py
```

## Branch Strategy

- `master` — stable release branch
- `memory/embedding-system` — active development for the vector memory system
- Feature branches follow the pattern: `feat/<short-description>`

## Code Quality

All code must pass Ruff linting before merging:

```bash
ruff check .
```

Run with auto-fix:

```bash
ruff check --fix .
```

## Submitting Changes

1. Fork the repository and create a feature branch from `master`
2. Make your changes — keep commits atomic and well-described
3. Run `ruff check .` to ensure no lint errors
4. Open a Pull Request against `master` with a clear description of what changed and why
5. Link any related issues in the PR description

## Reporting Bugs

Use the [Issue Tracker](../../issues) with the Bug Report template. Include:

- Bot version / commit hash
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs (remove any sensitive data)

## Security

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities. **Do not** open public issues for security bugs.
