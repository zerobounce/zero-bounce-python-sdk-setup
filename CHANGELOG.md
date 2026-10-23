# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `validate` takes `timeout` (3–60 seconds), `activity_data`, `verify_plus`, and `use_post` (form-encoded `POST /validate`).
- `validate_batch` takes `timeout` (10–120 seconds), `activity_data`, and `verify_plus`.
- `ZBValidateResponse` reads `active_in_days` and `active_first_seen`.
- `score_email` (`GET /scoring`) and `score_email(..., use_post=True)` (form-encoded `POST /scoring`).
- Bulk email finder (`send_email_finder_file`, `email_finder_file_status`, `email_finder_get_file`, `email_finder_delete_file`, plus stream upload).
- Bulk domain search (`send_domain_search_file`, `domain_search_file_status`, `domain_search_get_file`, `domain_search_delete_file`, plus stream upload).
- List evaluator (`send_list_evaluator_file`, `get_list_evaluator_result`, `send_evaluated_file`).
- Filters (`add_filter`, `list_filters`, `delete_filter`).
- Amazon S3 bulk (`list_s3files`, `validate_s3file`, `score_s3file`, `email_finder_s3file`, `domain_search_s3file`, `export_s3file`) and SFTP/FTP bulk (`validate_sftpfile`, `score_sftpfile`, `email_finder_sftpfile`, `domain_search_sftpfile`, `export_sftpfile`). The export bucket and path are optional; without them your account settings are used.
- `validate` takes `domain_info` (website availability and WHOIS), `greylist_processing`, and `callback_url` (requires `greylist_processing=True`). `ZBValidateResponse` reads `domain_website_exists` and `domain_registrant_company_name`, and `message` while a greylist retry is still in progress.
- Inbox Placement Tester (`get_inbox_placement_providers`, `get_inbox_placement_test_types`, `create_inbox_placement_test`, `get_inbox_placement_test`, `list_inbox_placement_tests`, `delete_inbox_placement_test`, `get_inbox_placement_webhook`, `set_inbox_placement_webhook`) on `bulkapi.zerobounce.net/api/ipt`. Its `detail` error messages raise `ZBApiException` with that text.
- `LIST_EVALUATOR_BASE_URL` and `INBOX_PLACEMENT_BASE_URL` set where the list evaluator and Inbox Placement Tester requests go, like `BULK_BASE_URL` for the other bulk files.

### Changed

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

### Security

- Error messages no longer include the raw HTML access-denied page. The live `get_file` page is about 1.4 MB and contains the API key.
- Redirects are not followed, so a response cannot send the client, or the API key, to another host.

## [2.2.3] - 2026-06-18

### Fixed

- `validate_batch` posts to `api.zerobounce.net/v2/validatebatch` instead of `bulkapi.zerobounce.net`.

## [2.2.2] - 2026-06-10

### Added

- `ZBValidateResponse.catchall_domain`, read from `catchall_domain`.

## [2.2.0] - 2026-04-05

### Added

- `send_file` / `send_file_stream` `allow_phase_2`, sent as `allow_phase_2` on validation bulk sendfile only.
- `ZBGetFileOptions` for `get_file` and `scoring_get_file`, with `download_type` (`phase_1`, `phase_2`, `combined`) and `activity_data` (validation `get_file` only).
- `ZBFileStatusResponse.file_phase_2_status`.

### Fixed

- `get_file` raises `ZBApiException` when the body is a JSON error, including HTTP 200 with `"success": false`, instead of saving that body as the results file.

## [2.1.10] - 2026-03-03

### Changed

- License the project under MIT.

## [2.1.0] - 2026-03-03

### Added

- `ZeroBounce(..., timeout=timedelta)` to set the HTTP timeout.
- `send_file_stream` and `scoring_send_file_stream`.

### Fixed

- `get_credits` and `validate_batch` tolerate a response that omits `Credits`, `email_batch`, or `errors`.

## [2.0.1] - 2026-01-26

### Fixed

- `ZBValidateSubStatus.gold` and unknown status values are recognized again. The 2.0.0 tag did not include them.

## [2.0.0] - 2026-01-26

### Removed

- `ZBValidateSubStatus.gold` and the fallback that kept an unknown status from raising. Restored in 2.0.1.

## [1.1.3] - 2026-01-26

### Added

- `find_email_format` and `find_domain`.
- `ZeroBounce(api_key, base_url)` with `ZBApiUrl` (`API_DEFAULT_URL`, `API_USA_URL`, `API_EU_URL`) or an https URL string.
- `ZBValidateSubStatus.gold` and `ZBValidateSubStatus.role_based_accept_all`.

### Changed

- An unknown status, sub-status, or confidence value warns and becomes `None` instead of raising.

### Deprecated

- `guess_format`. Use `find_email_format` or `find_domain`.

## [1.1.2] - 2025-08-07

### Added

- `ZBValidateSubStatus.accept_all`.

## [1.1.1] - 2024-12-20

### Fixed

- API error payloads raise `ZBApiException` with the error text.

## [1.1.0] - 2023-09-12

### Added

- Initial release: `get_credits`, `get_api_usage`, `get_activity`, `validate`, `validate_batch`, bulk and AI-scoring file methods, and `guess_format`.

[Unreleased]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.2.4...HEAD
[2.2.3]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.2.0...v2.2.2
[2.2.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.1.10...v2.2.0
[2.1.10]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.1.0...v2.1.10
[2.1.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v1.1.3...v2.0.0
[1.1.3]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/zerobounce/zero-bounce-python-sdk-setup/releases/tag/v1.1.0
