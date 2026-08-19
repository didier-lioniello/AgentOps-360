# Contributing

Thanks for helping improve this reference implementation.

## Local checks

Use Python 3.11 or 3.12:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install "ruff==0.16.3" "pip-audit==2.10.1"
ruff check .
ruff format --check .
python -m pytest
pip-audit --requirement requirements.txt --no-deps
bash -n examples/curl/register_and_invoke.sh
```

The unit test suite does not require PostgreSQL, Redis, Docker, or an API key. Changes to database
or worker behavior should add focused integration coverage where practical.

## Dependency updates

`requirements.in` contains the direct dependencies. `requirements.txt` is the compiled, fully
pinned install input. Regenerate it on Python 3.11, the lowest supported version:

```bash
python3.11 -m venv .venv-lock
source .venv-lock/bin/activate
python -m pip install --upgrade pip
python -m pip install "pip-tools==7.6.1"
CUSTOM_COMPILE_COMMAND="pip-compile --resolver=backtracking --strip-extras --output-file=requirements.txt requirements.in" \
  pip-compile --resolver=backtracking --strip-extras --output-file=requirements.txt requirements.in
```

Review and commit `requirements.in` and `requirements.txt` together. The CI lock check recompiles
the file on Python 3.11, fails if the generated result differs, and audits every pinned package.

## Pull requests

- Keep changes focused and explain the user-visible or security impact.
- Add or update tests for behavior changes.
- Keep Ruff lint/format checks and the Python 3.11/3.12 test matrix green.
- Update the README when setup, configuration, or known limitations change.
- Never commit `.env` files, tokens, model inputs, production data, or private product details.

For vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
