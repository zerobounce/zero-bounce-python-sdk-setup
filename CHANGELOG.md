# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Behaviour change:** a zero, negative or non-`timedelta` `timeout` is refused at construction (`ZeroBounce` and `ZeroBounceWarmup`) with `ZBClientException`; before, every later call failed with a urllib3 `ValueError`.
- **Behaviour change:** `validate(timeout=...)` and `validate_batch(timeout=...)` accept whole seconds only (3-60, 10-120); `3.5` and `"10"` raise `ZBClientException` instead of being sent or raising `TypeError`.
- The source distribution now carries the whole offline test set (`tests/__init__.py`, `tests/zero_bounce_test_case.py`, `tests/fixtures/strict-json-corpus.tsv` and every `tests/test_*.py`), so `pytest` runs from the unpacked sdist. Up to 3.0.0 the fixture and the test base class were missing and the suites could not run there. The opt-in live suite stays out.
- Trove classifiers list Python 3.15, which CI already tests. The build backend requirement has upper bounds (`setuptools>=77.0.3,<85`, `wheel>=0.45,<1`).
- Release pipeline (no change for callers): the publish workflow takes only `v`-prefixed tags and checks out the validated commit in every job, runs one publish at a time, builds with hash-pinned tools from `requirements-build.txt`, and only the publishing job uses the `release` environment. The test image base is pinned by digest.

### Fixed

- **Behaviour change:** a download whose body is any JSON object or array (also after a UTF-8 BOM) or whose content type is `application/json` or `*+json` (e.g. `application/problem+json`) is now an error with its HTTP status and saves nothing, on plain and streamed `get_file` calls (all products) and Warmup CSV downloads. Before, only objects with a success/message/error key were caught, `[...]` was saved by the streamed path, and a BOM hid JSON from the check.
- An existing download file keeps its permissions (a 0600 file no longer becomes 0644). Same for Warmup.
- A symbolic link as `download_path` is written through: the file behind it is replaced and the link stays (before, the link was replaced by a regular file). A link whose target directory is missing is refused before sending.
- **Behaviour change:** an empty path, a path ending in a separator and a directory as `download_path` raise `ZBClientException` before the request is sent (before: the request was sent, then FileNotFoundError/IsADirectoryError; a trailing separator left an empty directory behind). Directories created for a download that then fails are removed. Warmup uses the same writer and checks (`download_path=None` still means no file).
- Requests use a (connect 30 s, read 120 s) timeout pair instead of one 120 s value; a custom `timeout` is the read timeout and caps the connect timeout.
- **Behaviour change:** a message-only answer (`message`, `Message`, `error`, `error_message`, `Error`, `detail`, or `{}`) on HTTP 200 used to come back as a result on file jobs, file status, delete, scoring, S3/SFTP export, list evaluator, batch, activity, score, API usage and the Inbox Placement calls. It now raises `ZBApiException` with status 200 on every typed call. Only validate's greylist answer `{"Message": "..."}` stays a result (a lowercase `{"message": ...}` on validate is now an error), and the raw-JSON filter calls keep theirs.
- **Behaviour change:** `success` values a strict boolean reads as false (`"0"`, `0`, `"False "`, `" false"`) used to be results on the raw calls; they are now errors, like `false`.
- An `error` that is an object (`{"error":{"code":1}}`) no longer puts a Python repr in the message; it reads "ZeroBounce returned an error with no message text."
- `validate(ip_address="")` and `send_file(return_url="")` (and the other send calls) no longer send an empty parameter; blank optional values are left out.
- Missing, blank or wrong-type arguments (`None`, `""`, `"  "`, `5`) now raise `ZBClientException` before anything is sent, on every public method, instead of sending a request or raising `AttributeError`/`TypeError`. This includes `validate`/`get_activity`/`score_email` emails, file ids, file names and paths, columns, filter values, Inbox Placement names and webhook URLs.
- `get_api_usage` raises `ZBClientException` for a reversed or non-date range.
- Field types are part of the response shape. On every typed `ZeroBounce` call a field that arrives with a JSON type its model does not document (such as `{"Credits": true}`, `{"Credits": 5.5}`, `"status": 5`, `"score": 5.5` or an object where a string is expected), and a required field that is missing or `null`, raises `ZBApiException` with the HTTP status (200) and a message naming the field. The required fields are `get_credits` `Credits`, which must be an integer sent as a JSON string (`"-1"`, `"12345"`, as the live API sends it) or as a JSON number (`2375323`, as zerobounce.net's example shows), and is returned as sent (`"abc"`, `"5.0"`, `5.5` and `true` are errors), and `validate` (and each `validate_batch` row, which must be a JSON object) `address` and `status`; the greylist answer `{"Message": "..."}` is still a result. `null` is accepted for every optional field and returned as `None`, including `email_batch`, `errors` and `other_domain_formats`. Up to 3.0.0 a wrong-typed field was returned as is (`credits` could be `True`, a list or `None`), and a missing `Credits` gave `credits=None`. Every documented example response still parses. Warmup and the raw-JSON calls are unchanged.
- A 2xx body that is strict JSON but the wrong shape for the call (`0`, `"x"`, `null`, `true`, `[]` where an object is expected, an object where `list_filters` expects an array, or a field of the wrong type such as `"email_batch": 5`) raises `ZBApiException` with `status_code` 200 on every typed `ZeroBounce` call. Up to 3.0.0 it was returned as a result with default fields, or raised a raw `TypeError` / `AttributeError` from inside the SDK. `list_s3files` accepts the documented `{"success": true, "files": [...]}` and a bare array.
- A 2xx body nested deeper than Python's JSON parser can recurse (such as 200000 `[`) raises `ZBApiException` with `status_code` 200 on every `ZeroBounce` and `ZeroBounceWarmup` call, downloads included. Up to 3.0.0 it raised `RecursionError`.
- A streamed result-file download whose JSON body is larger than the 2 MiB error read limit raises `ZBApiException` with the response's status and saves nothing, under any content type. Up to 3.0.0 a JSON error body over the limit under a CSV content type was saved as the result file.
- A blank 2xx body (spaces, tabs or newlines only) on a `ZeroBounceWarmup` JSON call or on `delete_inbox_placement_test` raises `ZBApiException` with `status_code` 200: it is not JSON. Only a 204 or a 200 with no body at all is the documented empty success (`None`). Up to 3.0.0 a blank body was returned as `None` too.
- `get_file` and the other result-file downloads without `stream=True` write to a temporary file in the same folder and move it into place only when the write succeeds, as streamed downloads do. When writing fails (for example on a full disk, over a file size limit or in a read-only folder) they raise, leave no partial file, and leave a file already at `download_path` as it was. Up to 3.0.0 the file at `download_path` was truncated first and the truncated file stayed behind, where it could be read as the result. Result files and Warmup CSVs are created with the usual mode for a new file (`0666` less the umask); streamed downloads were `0600` up to 3.0.0.
- `ZeroBounceWarmup.download_seeds` and `download_statistics` with a `download_path` write to a temporary file in the same folder and move it into place only when the write succeeds. When writing fails (for example on a full disk) they raise, leave no partial file, and leave a file already at `download_path` as it was. Up to 3.0.0 the file at `download_path` was truncated first and the truncated CSV stayed behind.
- `ZeroBounceWarmup.download_seeds` and `download_statistics` raise `ZBApiException` (`status_code` 200) for a JSON body under a CSV content type (such as `text/csv` with `{"error": "..."}`) and write nothing. Up to 3.0.0 only a JSON content type was rejected, so that body was returned and saved as the CSV.
- `send_file`, `send_file_stream`, `scoring_send_file` and `scoring_send_file_stream` send `remove_duplicate` only when the caller sets it; the default is now `None` (the API then removes duplicates, as before). Up to 3.0.0 they always sent `remove_duplicate=true`. Passing `True` or `False` works as before.
- `ZeroBounceWarmup.add_sending_account` parses `managed_sending["weekdays_only"]` strictly, as `ignore_conflict`: `True`/`False`, `"true"`/`"false"` (any case) and `1`/`0` are sent as a JSON boolean, and anything else raises `ZBClientException("Invalid parameter: weekdays_only must be true or false")` before a request is sent. Up to 3.0.0 the value was sent as given, so `"false"` went out as a string.
- `delete_inbox_placement_test` returns `None` when the API answers with an empty 2xx (204 No Content), as the Go SDK does. Up to 3.0.0 it raised `ZBApiException` ("Empty response"). A JSON answer is returned as before; the other Inbox Placement calls still treat an empty body as an error.
- `ZeroBounceWarmup` errors reported on a 200 carry `status_code` 200: an HTML page (such as a proxy's "Access denied" page), a body that is not valid JSON, and a JSON body or empty body from `download_seeds` or `download_statistics`. Up to 3.0.0 their `status_code` was `None`.
- `ZeroBounceWarmup.add_sending_account` parses `ignore_conflict` strictly, as `ZeroBounce` parses its boolean options: `True`/`False`, `"true"`/`"false"` (any case) and `1`/`0` are accepted, and anything else raises `ZBClientException("Invalid parameter: ignore_conflict must be true or false")` before a request is sent. Up to 3.0.0 the value went through `bool()`, so `ignore_conflict="false"` sent `true`.
- A 2xx body that is not strict JSON, because it holds `NaN`, `Infinity` or `-Infinity` (alone or as a value, such as `{"Credits": NaN}`), raises `ZBApiException` with `status_code` 200 on every `ZeroBounce` and `ZeroBounceWarmup` JSON call, as other bodies that are not valid JSON do. Up to 3.0.0 Python's lenient `json` parser accepted them: a JSON object holding them was returned as a result (with a `float('nan')` field), and a bare `NaN` raised `TypeError` or `AttributeError` from inside the SDK or was returned as `nan`.

- The email finder and domain search answers (`guess_format`, `find_domain`, `find_email_format`) no longer raise from the response class when a full result carries a `message` key beside its fields: the result is returned. A body made only of message keys is a rejected request: it raises `ZBApiException` with status 200, the API key masked, and the text of the first non-blank message, or "Request failed" when the message is null or blank. Up to 3.0.0 the class raised for any `message` key with no status and no masking, so a key echoed in the message came back unmasked, and `"message": null` raised the error text `None`.

- A file job's `message` that is a list of strings (`send_file`, `file_status`, `delete_file` and the other file calls) reads as one string, the strings joined with a newline. Up to 3.0.0 only the first string was kept.
- `null` in `validate_batch()`'s `email_batch` and `errors`, and in `guess_format()`'s and `find_domain()`'s `other_domain_formats`, is returned as `None`, as every other optional field is. Up to 3.0.0 it raised a `TypeError`.

### Security

- **Behaviour change:** The SDK refuses to send (`ZBClientException`, nothing is sent) while `urllib3.connectionpool` (or `urllib3`, `urllib3.connection`, `urllib3.poolmanager`, `urllib3.response`, `urllib3.util.retry`, `requests`, `http.client`) is enabled for DEBUG, or `http.client.HTTPConnection.debuglevel` is above 0. Before, `urllib3` wrote `GET /v2/getcredits?api_key=<key>` to the log at DEBUG. Applies to both clients; documented in the README Security section.
- Error text and logs no longer leak the API key, the Warmup key or the SMTP password when the server echoes it in another letter case (an upper-cased key) or as HTML entities (`&#39;`, `&#x27;`, `&amp;`, `&lt;`, `&gt;`, `&quot;`) or backslash-escaped quotes (`\'`, `\"`). Redaction is now case-insensitive, and the "any decoded view still holds the secret" check also decodes HTML entities and backslash-escaped quotes.
- **Behaviour change:** `ZeroBounce(api_key)` and `ZeroBounceWarmup(api_key)` refuse a key holding whitespace of any kind (including NBSP, U+0085, U+2028), control or Unicode format characters (U+200B, U+FEFF, U+180E, U+2060) anywhere in it, and any non-ASCII character. Before, only surrounding whitespace and control characters below U+0020 were refused, so such keys were accepted and failed (or leaked) at send time. Messages: `api_key has whitespace, control or invisible characters` and `api_key has characters that cannot be sent in an HTTP header` (the old `api_key has surrounding whitespace or control characters` is gone), same as Android and C#.
- A `UnicodeEncodeError` from building a request header (its `object` holds the key) is now raised as a `ZBClientException` with a fixed message and no `__context__`.
- **Behaviour change:** Base URLs are parsed, not prefix-checked: both clients require `https`, a valid host (letters, digits, hyphens, dots, or a bracketed IPv6 address), no userinfo, no whitespace, control or format characters, no backslash and a valid port. `https://api.zerobounce.net@evil.example/v2` (which sent the key to evil.example), `https://exa mple.com`, `https://`, `https:///v2` and `https://[::1/v2` (a bare `ValueError` before) now raise `ZBClientException`. The check runs on construction and again on every send, so a reassigned `_base_url` or `*_BASE_URL` attribute is covered.
- `ZeroBounceWarmup` re-checks its root URL on every send: a reassigned `_root` of `http://...` no longer sends the `API-Key` header in clear text.
- Redaction is closed under encoding. After the known spellings of the API key, the Warmup key and the SMTP `username` and `password` are masked, every error message (from a response body or a transport error) is decoded up to four layers deep (the SDK's own request encoding plus three echo layers), in any order (URL-decoding, `+` as a space, JSON unescaping including `\/` and `\uXXXX`); if any decoded view still holds a secret, the message is replaced by "ZeroBounce returned an error; the response body was omitted because it contained a credential." (`CREDENTIAL_OMITTED_MESSAGE`). Up to 3.0.0 a key URL-encoded twice (a server echoing a URL-encoded copy of a form body) came back unmasked, for example from `validate_s3file`, `export_sftpfile` and `add_filter`.
- The API key, the Warmup key and the SMTP `username` and `password` of `test_smtp_configuration` are also masked in their JSON-escaped forms (`"` as `\"`, `/` as `\/`, non-ASCII as `\uXXXX`) and URL-encoded with `/` kept, in every error built from a response body. Up to 3.0.0 a key or password containing `"` came back unmasked when the body quoted it as JSON.
- The same secrets are also masked in the URL-encoded form of their JSON-escaped text (spaces as `+` and as `%20`, `/` as is or as `\/`, non-ASCII as is or as `\uXXXX`), which a server echoing a URL-encoded copy of a JSON request body returns, and JSON-escaped twice (a JSON error body quoting the JSON request body). Up to 3.0.0 a secret containing `"`, `/` or `\` came back unmasked in those forms.
- `ZeroBounce` and `ZeroBounceWarmup` refuse to be pickled (and so to be copied with `copy.copy` / `copy.deepcopy`): they raise `TypeError` without the key. Up to 3.0.0 `pickle.dumps(client)` wrote the API key into the pickle.
- `validate_batch` redacts the API key in its account-level error (an `"email_address": "all"` entry such as "Invalid API key <key>"), as every other error is redacted. 3.0.0 raised that text unchanged.
- A body that is not valid JSON no longer keeps the JSON parser's error, which quotes the body (and any key in it), as the `__context__` of the `ZBApiException` raised for it, on `ZeroBounce` and `ZeroBounceWarmup`. Up to 3.0.0 the error was raised with `from None`, which hides the original from tracebacks but leaves it on `__context__`.

- The API key is no longer a plain attribute of `ZeroBounce` and `ZeroBounceWarmup`: it is held in a masked holder, so `vars()`, `__dict__` and any dump of a client show `***`. Up to 3.0.0 `vars(client)` showed `_api_key` with the key in it.

## [3.0.1] - 2026-11-11 (tagged, never published)

Tag `v3.0.1` exists but no publish run or GitHub release was made and PyPI's latest is 3.0.0, so its changes first reach PyPI with the next release.

### Fixed

- `validate_batch` with an account-level error (an `"email_address": "all"` entry, such as "Invalid API Key or your account ran out of credits") raises `ZBApiException` with `status_code` 200, like the other calls and the other SDKs. 3.0.0 raised it with `status_code` `None`.
- `ZBValidateResponse.mx_found`, `free_email` and `catchall_domain` (also on `validate_batch` results) are `True`, `False` or `None`, as in the PHP SDK. A value that is not a boolean, such as `"unknown"`, is now `None`; 3.0.0 kept the string, which is truthy. `"1"`/`"0"` and `1`/`0` are now read as `True`/`False`.
- `ZBGetActivityResponse.found` is parsed the same way: `"false"` from the API is `False` (3.0.0 kept the string `"false"`, which is truthy), and a value that is not a boolean is `None`.

## [3.0.0] - 2026-11-11

### Breaking

- **Breaking:** boolean request options are parsed strictly. `True`/`False`, `"true"`/`"false"` (any case) and `1`/`0` are accepted; anything else raises `ZBClientException("Invalid parameter: <name> must be true or false")` before a request is sent. Up to 2.4.0 `validate(..., activity_data="false")` sent `true`, and the S3/SFTP jobs and file uploads passed any value through to the API unchecked. Affects `validate` (`activity_data`, `verify_plus`, `domain_info`, `greylist_processing`), `validate_batch`, `send_file`/`scoring_send_file` and their `_stream` variants (`has_header_row`, `remove_duplicate`, `allow_phase_2`), `ZBGetFileOptions.activity_data`, the email finder and domain search uploads (`has_header_row`), and every S3/SFTP job (`has_header_row`, `remove_duplicates`).

### Fixed

- A 2xx `{"error_message": "..."}` with no `success` field raises `ZBApiException`. 2.4.0 returned it as the result (`get_credits()` gave `credits=None`).
- `find_email_format` and `find_domain` (GET and POST) raise for a body made only of message fields, including `{"detail": ...}` and `{"error_message": ...}`; 2.4.0 raised only for `Message`/`message` and returned the others as results.
- The per-API `*_BASE_URL` attributes (`BULK_BASE_URL`, `BULK_ROOT_URL`, `SCORING_BASE_URL`, `EMAIL_FINDER_BASE_URL`, `DOMAIN_SEARCH_BASE_URL`, `LIST_EVALUATOR_BASE_URL`, `INBOX_PLACEMENT_BASE_URL`) lose trailing slashes where they are read, so `BULK_BASE_URL = "https://host/v2/"` no longer requests `/v2//filestatus`.

### Changed

- `ZBApiException.status_code` is the HTTP status (usually 200) for errors the API reports on a 2xx response: a dead key's `error`/`Error`/`error_message`, `"success": false`, a message-only finder body, a Cloudflare JSON page and a body that is not JSON. It was `None` for these.
- `ZBValidateResponse` (and the `validate_batch` elements) gain `raw_status` and `raw_sub_status`, the API's text, so a value this version does not know (which still makes `status`/`sub_status` `None`) is not lost.
- The license file is named `LICENSE` (it was `LICENSE.txt`); the wheel and sdist ship it under that name.

## [2.4.0] - 2026-11-11

### Breaking

- Requires Python 3.10 or newer (`requires-python = ">=3.10"`; 2.3.0 allowed 3.7). The `requests` and `urllib3` releases that fix their current advisories need Python 3.10: `requests` 2.33.0 (CVE-2026-25645) and `urllib3` 2.7.0 and 2.8.0 (CVE-2026-44431, CVE-2026-44432, CVE-2026-97687, CVE-2026-97688, CVE-2026-97689). On 3.9 and older pip can only resolve `requests` 2.32.5 and `urllib3` 2.6.3 or older, which have those advisories. Python 3.7, 3.8 and 3.9 are also past end of life. On those versions pip keeps installing 2.3.0.

### Changed

- The dependency floors apply on every supported Python: `requests >= 2.33.0`, `urllib3 >= 2.8.0`, `idna >= 3.15`, `certifi >= 2026.10.19`, and `pytest >= 9.0.3` for the `test` extra. The floors for Python 3.9 and older are gone.
- Classifiers name Python 3.10 to 3.14.

### Fixed

- Building from source declares `setuptools >= 77.0.3`. The `license = "MIT"` expression needs setuptools 77, and setuptools 61 to 76, which 2.3.0 allowed, reject it.

### Security

- The publish workflow uses `pypa/gh-action-pypi-publish` v1.14.3, pinned by commit, instead of v1.14.2. v1.14.2 and older bundle the emSign root CAs, whose intermediate CA keys were compromised, in the `certifi` trust store that Sigstore uses for Trusted Publishing and attestations (GHSA-5xjx-3w67-w9x9, critical).

## [2.3.0] - 2026-10-24

### Added

- `validate` takes `timeout` (3–60 seconds), `activity_data`, `verify_plus`, and `use_post` (form-encoded `POST /validate`).
- `validate_batch` takes `timeout` (10–120 seconds; sent as a string, which the live API requires), `activity_data`, and `verify_plus`.
- `ZBValidateResponse` reads `active_in_days` and `active_first_seen`.
- `score_email` (`GET /scoring`) and `score_email(..., use_post=True)` (form-encoded `POST /scoring`).
- Bulk email finder (`send_email_finder_file`, `email_finder_file_status`, `email_finder_get_file`, `email_finder_delete_file`, plus stream upload).
- Bulk domain search (`send_domain_search_file`, `domain_search_file_status`, `domain_search_get_file`, `domain_search_delete_file`, plus stream upload).
- List evaluator (`send_list_evaluator_file`, `get_list_evaluator_result`, `send_evaluated_file`). `send_evaluated_file(file_id)` submits a finished evaluation for validation by the evaluator's `file_id`, as the live API requires (the docs describe a file upload). Uploads and results return `ZBListEvaluatorResponse` (`file_id`, `status`, `progress`, the percentages, `abuse`, `do_not_mail`, `spam_trap`).
- Filters (`add_filter`, `list_filters`, `delete_filter`). `rule` must be `allow` or `block` and `target` `email`, `domain`, `mx`, or `tld`.
- Amazon S3 bulk (`list_s3files`, `validate_s3file`, `score_s3file`, `email_finder_s3file`, `domain_search_s3file`, `export_s3file`) and SFTP/FTP bulk (`validate_sftpfile`, `score_sftpfile`, `email_finder_sftpfile`, `domain_search_sftpfile`, `export_sftpfile`). Each job sends `file_name`, `has_header_row`, `remove_duplicates`, and `return_url`; `file_name`, `has_header_row`, and `return_url` are required because the live API rejects jobs without them. The export bucket and path are optional; without them your account settings are used.
- `validate` takes `domain_info` (website availability and WHOIS), `greylist_processing`, and `callback_url` (requires `greylist_processing=True`). `ZBValidateResponse` reads `domain_website_exists` and `domain_registrant_company_name`, and `message` while a greylist retry is still in progress.
- Inbox Placement Tester (`get_inbox_placement_providers`, `get_inbox_placement_test_types`, `create_inbox_placement_test`, `get_inbox_placement_test`, `list_inbox_placement_tests`, `delete_inbox_placement_test`, `get_inbox_placement_webhook`, `set_inbox_placement_webhook`) on `bulkapi.zerobounce.net/api/ipt`. Its `detail` error messages raise `ZBApiException` with that text.
- `get_credits`, `get_api_usage`, `get_activity`, `find_email_format`, and `find_domain` take `use_post=True` (form-encoded `POST`, which the API accepts since September 2026).
- `ZBValidateSubStatus.ai_agent_mailbox`, documented for `valid` and `catch-all` results.
- `ZBGetActivityResponse.active_first_seen`, and `ZBGetApiUsageResponse` counts for `leading_period_removed` and `alias_address`.
- `ZeroBounceWarmup`, a client for the Warmup API (https://www.zerobounce.net/docs/warmup-api) with a method for each of its 26 endpoints. `check_domain_dmarc` takes an email address, as the live API requires. It sends a Warmup API key in the `API-Key` header to `https://warmup-api.zerobounce.net` (or the base URL you pass), checks the documented ranges before sending, returns `None` for 204 and empty successes, and returns CSV text for the two downloads.
- `get_file`, `scoring_get_file`, `email_finder_get_file`, and `domain_search_get_file` take `stream=True` to write a result file in chunks instead of reading it into memory first. The file appears at `download_path` only once complete, so a failed download leaves an existing file untouched and no partial file behind. Without the flag, downloads behave as before.
- A `UserWarning`, once per client, when an EU or US `base_url` is set but a request goes to `bulkapi.zerobounce.net` (bulk, scoring and finder files, the list evaluator, S3/SFTP, the Inbox Placement Tester): ZeroBounce documents no regional bulk host.
- `ZBApiException.status_code`: the HTTP status of a failed response, from both clients (for example 429 from the Warmup API, 403 when Cloudflare blocks a request).
- `LIST_EVALUATOR_BASE_URL` and `INBOX_PLACEMENT_BASE_URL` set where the list evaluator and Inbox Placement Tester requests go, like `BULK_BASE_URL` for the other bulk files.

### Changed

- Dependency floors are the oldest releases without known advisories (OSV) on each Python version: `requests >= 2.33.0`, `urllib3 >= 2.8.0` and `idna >= 3.15` on Python 3.10+; `requests >= 2.32.4` and `idna >= 3.15` on 3.8 and 3.9; `requests >= 2.31.0` on 3.7; `certifi >= 2026.10.19` everywhere (it removes CA roots with compromised intermediates). Python 3.9 and older cannot install the fixed `requests` 2.33 and `urllib3` 2.7+.
- The Inbox Placement Tester methods send the key in the documented `Authorization: Bearer` header instead of the URL.
- `find_email_format`'s `first_name` is optional, as documented; it is sent only when set.
- `send_email_finder_file` needs `first_name_column` or `full_name_column`, as documented, and raises `ZBClientException` without one.
- A custom `base_url` must be an `https://` URL.
- API requests time out after 120 seconds unless the caller passes `timeout`.
- API requests do not follow redirects.

### Fixed

- A 403 HTML "Access denied" page (about 1.4 MB from the live API on `get_file`) is raised as a short `ZBApiException`. An HTML page with status 200 is an error as well, including `get_file`, `email_finder_get_file`, and `domain_search_get_file`, instead of a saved CSV.
- Empty and non-JSON bodies are a short `ZBApiException`. The message is no longer a chained `JSONDecodeError`, and a doubled `Error: Error:` / `[Error]: [Error]:` prefix is collapsed to one.
- `validate_batch` raises `ZBApiException` for an account-level failure (HTTP 200, error for address `all`, such as an invalid API key or no credits). An error for one address stays on the successful result.
- `send_file`, `scoring_send_file`, bulk email finder, domain search, and S3 uploads send `has_header_row`, `remove_duplicate`, and `remove_duplicates` as `true` or `false`. `has_header_row=False` is sent.
- `send_email_finder_file`, `send_domain_search_file`, and `send_list_evaluator_file` send column `0`. They previously treated `0` as empty and rejected it before the request.
- `find_email_format` raises `ZBApiException` when the API returns a `Message` error, the same way `find_domain` and `guess_format` already did.
- Importing the SDK works on Python 3.7 to 3.9 again. `ZeroBounce.__init__` was annotated with `timedelta | None`, which raised `TypeError` at import on those versions.
- `find_domain` and `guess_format` raise `ZBApiException` for a lowercase `message` error instead of `KeyError`.
- A validation error body `{"detail": [{"loc": ..., "msg": ...}]}` raises with the field and message instead of the raw JSON.
- An error body that is a JSON list of messages (`["In-progress tests cannot be deleted."]`) raises with the first message instead of the raw JSON.
- An unknown `email_confidence` or `confidence` value is `None` with a warning instead of a `ValueError`.
- `ZBValidateResponse` reads `free_email`, `mx_found`, and `catchall_domain` sent as the strings `"true"` / `"false"` as booleans (the documented samples send `mx_found` as a string).
- `processed_at` without fractional seconds, and `get_api_usage` dates in the documented `yyyy/mm/dd` form, parse instead of raising `ValueError`. A date in another format is kept as the original string, with a warning.

### Security

- A network error no longer keeps the original, unredacted exception (with the API key in its URL or headers) as its `__context__`. The redacted copy is raised on its own.
- `ZeroBounce` and `ZeroBounceWarmup` reject a key with surrounding whitespace or control characters (for example one read from a file with its newline), which the HTTP library would otherwise quote unredacted in its error. Redaction also covers the escaped form of a key.
- Requests to a base URL that is not `https://` are refused before sending, including the reassignable `BULK_BASE_URL`, `SCORING_BASE_URL`, `EMAIL_FINDER_BASE_URL`, `DOMAIN_SEARCH_BASE_URL`, `LIST_EVALUATOR_BASE_URL`, `INBOX_PLACEMENT_BASE_URL` and `BULK_ROOT_URL`.
- IDs placed in a URL path are rejected when they are `.` or `..`.
- `ZeroBounceWarmup.test_smtp_configuration` masks the SMTP username and password in every error message.
- Error messages no longer include the raw HTML access-denied page. The live `get_file` page is about 1.4 MB and contains the API key.
- Redirects are not followed, so a response cannot send the client, or the API key, to another host.

## [2.2.4] - 2026-08-14

No changes to the package; CI action updates only.

## [2.2.3] - 2026-06-17

### Fixed

- `validate_batch` posts to `api.zerobounce.net/v2/validatebatch` instead of `bulkapi.zerobounce.net`.

## [2.2.2] - 2026-06-10

### Added

- `ZBValidateResponse.catchall_domain`, read from `catchall_domain`.

## [2.2.0] - 2026-04-08

### Added

- `send_file` / `send_file_stream` `allow_phase_2`, sent as `allow_phase_2` on validation bulk sendfile only.
- `ZBGetFileOptions` for `get_file` and `scoring_get_file`, with `download_type` (`phase_1`, `phase_2`, `combined`) and `activity_data` (validation `get_file` only).
- `ZBFileStatusResponse.file_phase_2_status`.

### Fixed

- `get_file` raises `ZBApiException` when the body is a JSON error, including HTTP 200 with `"success": false`, instead of saving that body as the results file.

## [2.1.11] - 2026-03-03

Published to PyPI with no changelog notes.

## [2.1.10] - 2026-03-03

### Changed

- License the project under MIT.

## [2.1.0] - 2026-03-03

### Added

- `ZeroBounce(..., timeout=timedelta)` to set the HTTP timeout.
- `send_file_stream` and `scoring_send_file_stream`.

### Fixed

- `get_credits` and `validate_batch` tolerate a response that omits `Credits`, `email_batch`, or `errors`.

## [2.0.2] - 2026-01-26

Published to PyPI with no changelog notes.

## [2.0.1] - 2026-01-26

### Fixed

- `ZBValidateSubStatus.gold` and unknown status values are recognized again. The 2.0.0 tag did not include them.

## [2.0.0] - 2025-10-29

### Removed

- `ZBValidateSubStatus.gold` and the fallback that kept an unknown status from raising. Restored in 2.0.1.

## [1.1.3] - 2026-01-26 (tagged, never published)

### Added

- `find_email_format` and `find_domain`.
- `ZeroBounce(api_key, base_url)` with `ZBApiUrl` (`API_DEFAULT_URL`, `API_USA_URL`, `API_EU_URL`) or an https URL string.
- `ZBValidateSubStatus.gold` and `ZBValidateSubStatus.role_based_accept_all`.

### Changed

- An unknown status, sub-status, or confidence value warns and becomes `None` instead of raising.

### Deprecated

- `guess_format`. Use `find_email_format` or `find_domain`.

## [1.1.2] - 2025-06-23

### Added

- `ZBValidateSubStatus.accept_all`.

## [1.1.1] - 2024-12-20

### Fixed

- API error payloads raise `ZBApiException` with the error text.

## [1.1.0] - 2023-09-12

### Added

- Initial release: `get_credits`, `get_api_usage`, `get_activity`, `validate`, `validate_batch`, bulk and AI-scoring file methods, and `guess_format`.

## [1.0.0] - 2023-04-07

Published to PyPI with no changelog notes.

[Unreleased]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v3.0.0...HEAD
[3.0.1]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.4.0...v3.0.0
[2.4.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.2.4...v2.3.0
[2.2.4]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.2.3...v2.2.4
[2.2.3]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.2.0...v2.2.2
[2.2.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.1.10...v2.2.0
[2.1.11]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.1.10...v2.1.11
[2.1.10]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.1.0...v2.1.10
[2.1.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.0.1...v2.1.0
[2.0.2]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v1.1.3...v2.0.0
[1.1.3]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/releases/tag/v1.1.0
[1.0.0]: https://pypi.org/project/zerobouncesdk/1.0.0/
