# Contributing to Zero Bounce Python SDK

Thank you for your interest in contributing. This document explains how to get set up and submit changes.

## Code of Conduct

By participating in this project, you agree to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

See the [README](README.md) for setup, linting and tests (`ruff check src tests`, `python -m compileall -q src tests`, `python -m pytest`). [AGENTS.md](AGENTS.md) describes the layout and the conventions changes must follow.

## How to Contribute

### Reporting Bugs

Open an [issue](https://github.com/zerobounce/zero-bounce-python-sdk-setup/issues) and include:

* Environment details (Python version, OS)
* Steps to reproduce
* Expected vs actual behavior
* Relevant code or error messages

### Suggesting Changes

* Check existing issues and pull requests first.
* Open an issue to discuss larger changes or API design before coding.

### Submitting Changes

1. **Fork** the repository and create a branch from `master`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** and add or update tests where relevant. Tests must not call the live API. Only add methods for endpoints documented at https://www.zerobounce.net/docs/.

3. **Add a CHANGELOG entry** under `## [Unreleased]` for anything users will notice.

4. **Run the lint and test commands** (see README) before submitting.

5. **Commit** with a [Conventional Commits](https://www.conventionalcommits.org/) message (e.g. `feat: add X`, `fix: Y`, `docs: Z`).

6. **Push** your branch and open a **Pull Request** against `master`.

7. In the PR description, briefly explain what changed and why. Link any related issues.

Maintainers will review and may request changes. Once approved, your PR can be merged.

## Questions

* [Zero Bounce API docs](https://www.zerobounce.net/docs/)
* [Project homepage](https://zerobounce.net)
* Contact: **integrations@zerobounce.net**

Thanks for contributing.
