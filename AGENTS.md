# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

`zero-bounce-python-sdk-setup` is the ZeroBounce Python SDK, published to PyPI as `zerobouncesdk`. Callers construct a `ZeroBounce` with an API key and call methods that return response objects or raise `ZBApiException` / `ZBClientException`. HTTP goes through the `requests` library inside `src/zerobouncesdk/zerobouncesdk.py`.

## Layout

- `src/zerobouncesdk/zerobouncesdk.py`: the client. `_get`, `_post`, `_post_form`, and `_request_json` are the HTTP entry points.
- `src/zerobouncesdk/zb_warmup.py`: `ZeroBounceWarmup`, the Warmup API client. It has its own host and key, authenticates with an `API-Key` header, and reuses the error helpers in `zerobouncesdk.py`. Keep Warmup methods there, not on `ZeroBounce`.
- `src/zerobouncesdk/zb_*.py`: response models, enums, and options.
- `tests/zero_bounce_test_case.py`: scripted unit tests. They patch `zerobouncesdk.zerobouncesdk.requests`.
- `tests/test_offline_edges.py` and `tests/test_warmup_offline.py`: more offline suites on the same principle (error bodies, redaction, every optional field; the Warmup API).
- `tests/test_offline_api.py`: offline suite. It patches `requests.sessions.Session.send`, so the real `requests` client builds the URL and body and the fake answers without the network.
- `tests/zero_bounce_integration_test.py`: live API tests. `pytest` does not collect this file. Run it with `python -m unittest tests.zero_bounce_integration_test` when `ZEROBOUNCE_API_KEY` is set.
- `pyproject.toml`: the only version field, `version = "x.y.z"`. `setup.py` calls `setup()` and reads that file.

## Commands

```bash
pip install -e ".[test]"
pip install ruff
ruff check src tests                # undefined names and syntax errors only
python -m compileall -q src tests
python -m pytest                    # unit tests and tests/test_offline_api.py
```

`ruff check` plus `compileall` is the lint step. There is no typechecker. The Ruff selection in `pyproject.toml` is `E9`, `F63`, `F7`, and `F82`. Do not widen it to a style ruleset that fails the existing tree.

CI (`.github/workflows/sdk_ci.yml`) runs `ruff check`, `compileall`, then `python -m pytest` with coverage.

## Conventions

- **Only endpoints documented at https://www.zerobounce.net/docs/.** Do not add a method for an endpoint that the public docs do not describe, even if it exists on the server. Integration pages count: the S3 bulk API is documented at https://www.zerobounce.net/docs/api-integrations/amazon-s3-bulk-api.
- **One `ZeroBounce` per API key.** The class is not a singleton. Do not reuse one instance across users or requests. The offline concurrency test constructs a separate client per key.
- **Column indexes are 1-based, and the SDK does not add 1.** Pass the API's index. `0` is a real value and is sent. `None` on an optional column (such as `first_name_column`) omits the field. `send_file`'s email column is required and is sent as given, including `0`. `domain_column` and the list-evaluator email column are required: `None` is rejected, `0` is sent. The bulk email finder also needs `first_name_column` or `full_name_column`.
- **Optional parameters are omitted when unset.** `timeout`, `activity_data`, `verify_plus`, and `allow_phase_2` are not sent until the caller sets them. Explicit `False` is sent as `false`. `ip_address=None` is omitted; `""` is sent.
- **Booleans on form and multipart bodies must be the strings `true` and `false`.** A Python `bool` passed to `requests` becomes `True` or `False`, and the API will not treat that as a boolean. `_form_data` converts them. JSON bodies (`validate_batch`) keep JSON booleans.
- **`allow_phase_2` is validation `send_file` only.** Scoring `send_file` and the S3 / SFTP jobs do not send it; those jobs send only their documented `file_name`, `has_header_row`, `remove_duplicates`, and `return_url`. `activity_data` on get-file is validation `get_file` only.
- **`validate_batch` uses `api.zerobounce.net`**, not `bulkapi.zerobounce.net`. It follows `base_url`.
- **Failures raise.** `ZBClientException` means the arguments were rejected and no request was sent. `ZBApiException` means the API failed. The message must be short: no raw HTML, no megabyte body, no `JSONDecodeError` / `Expecting value` text, and no `Error: Error:` prefix. An account-level `validate_batch` error (`email_address` `all`) raises. A per-address error stays on the result's `errors` list. `get_credits` with an invalid key returns `Credits` `-1`; that endpoint does not send an `error` field.
- **Downloads are buffered unless `stream=True`.** The streamed path sniffs the first 64 KB for an error body, writes to a `.part` temporary file next to `download_path`, and moves it into place only when complete. Keep both paths' error checks identical (`_raise_if_download_error`).
- **A file download is not JSON.** `get_file` saves a non-empty CSV body, including `text/csv` and `text/plain`. An empty body, an HTML page (status 200 or 403), and a JSON error are `ZBApiException`. Do not treat every `text/plain` body as an error.
- **Do not follow redirects.** Every `requests` call passes `allow_redirects=False`. A 3xx response is a `ZBApiException`. A redirect must not be fetched, because the `Location` could be another host and the next request can carry the API key.
- **Do not commit `.env`.** It is gitignored and may hold a real key. Tests must not call the live API.
- Match the surrounding style. Do not reformat unrelated code.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

- Add every user-visible change to `## [Unreleased]` in the same commit as the change.
- Group entries under these headings, in this order, omitting empty ones: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
- Write for SDK users: name the method, option, or behaviour, and say what changed. Leave out CI-only changes, internal refactors, and fixes to code that was never released.
- At 2.y.z, a breaking change bumps the major version, a new method or option bumps the minor version, and fixes alone bump the patch version.

## Releasing

Publishing and pushing tags need a maintainer's explicit approval. Do not bump the version, tag, or publish unless they asked.

1. Move `[Unreleased]` entries under `## [x.y.z] - YYYY-MM-DD`, leave an empty `[Unreleased]` section, and update the compare links at the bottom of `CHANGELOG.md`.
2. Set the same version in `pyproject.toml` (`version = "x.y.z"`). The publish workflow fails if it differs from the tag. That is the only version field. There is no runtime `__version__` and no user-agent constant. `setup.py` does not contain a version.
3. `ruff check src tests`, `python -m compileall -q src tests`, and `python -m pytest`.
4. Tag `vx.y.z` on that commit and run the Publish workflow (`.github/workflows/publish.yml`) with that tag. It publishes `zerobouncesdk` to PyPI through PyPI Trusted Publishing: the PyPI project trusts this repository, `publish.yml`, environment `release`. There is no PyPI token, and none should be added. Keep the workflow file name and environment name, or update the trusted publisher on PyPI first.
