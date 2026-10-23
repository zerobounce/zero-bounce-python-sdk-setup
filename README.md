## Zero Bounce Python SDK
This SDK contains methods for interacting easily with ZeroBounce API.
More information about ZeroBounce you can find in the [official documentation](https://www.zerobounce.net/docs/).


## Security

- Keep API keys on a trusted server. Do not embed them in mobile apps or browser JavaScript that untrusted users can inspect.
- Where the key travels, as each API documents it: the validation API takes an `api_key` parameter (in the query string for `GET` requests; in the body with `use_post=True` and for file uploads); the Inbox Placement Tester takes an `Authorization: Bearer` header; the Warmup API takes a separate Warmup key in an `API-Key` header, used only by `ZeroBounceWarmup`. Query strings can end up in proxy and server logs, so do not log full request URLs, and prefer `use_post=True` where a method offers it.
- Every base URL, including the per-API `*_BASE_URL` attributes, must be `https://`: the client refuses to send a request anywhere else. Do not pass end-user-controlled hosts into those settings.
- The client never follows redirects and masks the key in every exception it raises, network errors included. It rejects a key with surrounding whitespace or control characters, such as one read from a file with its trailing newline.

## INSTALLATION
```bash
pip install zerobouncesdk
```

Python 3.10 or newer is recommended: on 3.9 and older, the newest `requests` and `urllib3` releases (with their security fixes) cannot be installed.

## USAGE
Import the sdk in your file:

```python
from zerobouncesdk import ZeroBounce
```

Initialize the SDK with your API key. You can optionally specify a base URL to use a different API region or a custom endpoint:

**Default**: Uses the default ZeroBounce API endpoint
```python
from zerobouncesdk import ZeroBounce

zero_bounce = ZeroBounce("<YOUR_API_KEY>")
```

**Using predefined API regions**: Use one of the available API regions
```python
from zerobouncesdk import ZeroBounce, ZBApiUrl

# Use USA region
zero_bounce = ZeroBounce("<YOUR_API_KEY>", base_url=ZBApiUrl.API_USA_URL)

# Use EU region
zero_bounce = ZeroBounce("<YOUR_API_KEY>", base_url=ZBApiUrl.API_EU_URL)

# Use default region (explicit)
zero_bounce = ZeroBounce("<YOUR_API_KEY>", base_url=ZBApiUrl.API_DEFAULT_URL)
```

**Using a custom URL string**: Provide your own base URL
```python
zero_bounce = ZeroBounce("<YOUR_API_KEY>", base_url="https://custom-api.example.com/v2")
```

**Available API regions:**
- `ZBApiUrl.API_DEFAULT_URL` - Default ZeroBounce API (https://api.zerobounce.net/v2/)
- `ZBApiUrl.API_USA_URL` - USA region API (https://api-us.zerobounce.net/v2/)
- `ZBApiUrl.API_EU_URL` - EU region API (https://api-eu.zerobounce.net/v2/)

The region applies to the single-request API. File-based APIs always use `bulkapi.zerobounce.net` (see [Other hosts](#other-hosts)).

**Errors:** a method raises `ZBClientException` when it rejects an argument before sending anything, and `ZBApiException` when the API returns an error; both inherit from `ZBException`. `ZBApiException.status_code` holds the HTTP status when it is known (for example 429 from the Warmup API). An unknown status, sub-status or confidence value in a response becomes `None` with a `UserWarning` instead of an error.

## Examples
Then you can use any of the SDK methods, for example:

* ##### Check how many credits you have left on your account
```python
from zerobouncesdk import ZeroBounce

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

response = zero_bounce.get_credits()
print("ZeroBounce get_credits response: " + str(response))
```

* ##### Check your API usage for a given period of time
```python
from datetime import datetime
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

start_date = datetime(2019, 8, 1);  # The start date of when you want to view API usage
end_date = datetime(2019, 9, 1);    # The end date of when you want to view API usage

try:
    response = zero_bounce.get_api_usage(start_date, end_date)
    print("ZeroBounce get_api_usage response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_api_usage error: " + str(e))
```

* ##### Gather insights into your subscribers' overall email engagement
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

email = "valid@example.com";    # Subscriber email address

try:
    response = zero_bounce.get_activity(email)
    print("ZeroBounce get_activity response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_activity error: " + str(e))
```

* ##### Find the correct email format when you provide a name and email domain or company name

Pass exactly one of `domain` or `company_name`. The name fields are optional, and `use_post=True` sends the request as a form-encoded `POST`.

```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

# Option 1: Use find_email_format with domain
domain = "example.com"  # The email domain for which to find the email format
first_name = "John"      # The first name of the person whose email format is being searched
middle_name = "Quill"    # Optional: The middle name of the person
last_name = "Doe"        # Optional: The last name of the person

try:
    response = zero_bounce.find_email_format(
        first_name=first_name,
        domain=domain,
        middle_name=middle_name,
        last_name=last_name
    )
    print("Email: " + str(response.email))
    print("Email Confidence: " + str(response.email_confidence))
except ZBException as e:
    print("ZeroBounce find_email_format error: " + str(e))
```

```python
# Option 2: Use find_email_format with company_name
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

company_name = "Acme Corp"  # The company name for which to find the email format
first_name = "Jane"          # The first name of the person

try:
    response = zero_bounce.find_email_format(
        first_name=first_name,
        company_name=company_name
    )
    print("Email: " + str(response.email))
    print("Domain: " + str(response.domain))
    print("Company: " + str(response.company_name))
except ZBException as e:
    print("ZeroBounce find_email_format error: " + str(e))
```

```python
# Option 3: Use find_domain to discover email formats for a domain
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

domain = "example.com"  # The email domain to analyze

try:
    response = zero_bounce.find_domain(domain=domain)
    print("Domain: " + str(response.domain))
    print("Format: " + str(response.format))
    print("Confidence: " + str(response.confidence))
    print("Other formats: " + str(len(response.other_domain_formats)))
except ZBException as e:
    print("ZeroBounce find_domain error: " + str(e))
```

```python
# Option 4: Use find_domain with company_name
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

company_name = "Acme Corp"  # The company name to analyze

try:
    response = zero_bounce.find_domain(company_name=company_name)
    print("Domain: " + str(response.domain))
    print("Company: " + str(response.company_name))
    print("Format: " + str(response.format))
    print("Confidence: " + str(response.confidence))
    for fmt in response.other_domain_formats:
        print(f"  Alternative: {fmt.format} (confidence: {fmt.confidence})")
except ZBException as e:
    print("ZeroBounce find_domain error: " + str(e))
```

* ##### Validate an email address
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

email = "<EMAIL_ADDRESS>"   # The email address you want to validate
ip_address = "127.0.0.1"    # The IP Address the email signed up from (Optional)

try:
    response = zero_bounce.validate(email, ip_address)
    print("ZeroBounce validate response: " + str(response))
except ZBException as e:
    print("ZeroBounce validate error: " + str(e))
```

* ##### Validate a batch of up to 100 emails at a time
```python
from zerobouncesdk import ZeroBounce, ZBException, ZBValidateBatchElement

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

email_batch = [
    ZBValidateBatchElement("valid@example.com", "127.0.0.1"),
    ZBValidateBatchElement("invalid@example.com"),
]                   # The batch of emails you want to validate

try:
    response = zero_bounce.validate_batch(email_batch)
    print("ZeroBounce validate_batch response: " + str(response))
except ZBException as e:
    print("ZeroBounce validate_batch error: " + str(e))
```

* ##### The _sendFile_ API allows user to send a file for bulk email validation
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_path = './email_file.csv'  # The csv or txt file
email_address_column = 1        # The index of "email" column in the file. Index starts at 1

return_url = "https://domain.com/called/after/processing/request"

first_name_column = None        # The index of "first name" column in the file
last_name_column = None         # The index of "last name" column in the file
gender_column = None            # The index of "gender" column in the file
ip_address_column = None        # The index of "IP address" column in the file
has_header_row = False          # If the first row from the submitted file is a header row
remove_duplicate = True         # If you want the system to remove duplicate emails
allow_phase_2 = True            # Optional: sends allow_phase_2 (validation bulk only); omit or use None to skip

try:
    response = zero_bounce.send_file(
        file_path,
        email_address_column,
        return_url,
        first_name_column,
        last_name_column,
        gender_column,
        ip_address_column,
        has_header_row,
        remove_duplicate,
        allow_phase_2,
    )
    print("ZeroBounce send_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce send_file error: " + str(e))
```

Bulk validation uses `https://bulkapi.zerobounce.net/v2`. See [v2 send file](https://www.zerobounce.net/docs/email-validation-api-quickstart/v2-send-file), [v2 file status](https://www.zerobounce.net/docs/email-validation-api-quickstart/v2-file-status), and [v2 get file](https://www.zerobounce.net/docs/email-validation-api-quickstart/v2-get-file).

* ##### Check the status of a file uploaded via _sendFile_ method
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id = "<FILE_ID>"       # The returned file ID when calling sendFile API

try:
    response = zero_bounce.file_status(file_id)
    # response.file_status, response.file_phase_2_status, response.error_reason (when present)
    print("ZeroBounce file_status response: " + str(response))
except ZBException as e:
    print("ZeroBounce file_status error: " + str(e))
```

* ##### The _getfile_ API allows users to get the validation results file for the file been submitted using _sendFile_ API
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id="<FILE_ID>"                         # The returned file ID when calling sendFile API
local_download_path = "./dwnld_file.csv"    # The path where the file will be downloaded

try:
    response = zero_bounce.get_file(file_id, local_download_path)
    # Large result files: stream=True writes the file in chunks instead of holding it in memory first
    # response = zero_bounce.get_file(file_id, local_download_path, stream=True)
    print("ZeroBounce get_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_file error: " + str(e))
```

Optional [v2 get file](https://www.zerobounce.net/docs/email-validation-api-quickstart/v2-get-file) query parameters use `ZBGetFileOptions` and `ZBDownloadType` (`PHASE_1`, `PHASE_2`, `COMBINED`). Set `activity_data` on the options object for validation `get_file` only; it is not sent for `scoring_get_file`.

```python
from zerobouncesdk import ZeroBounce, ZBException, ZBGetFileOptions, ZBDownloadType

zero_bounce = ZeroBounce("<YOUR_API_KEY>")
opts = ZBGetFileOptions(download_type=ZBDownloadType.COMBINED, activity_data=True)
response = zero_bounce.get_file(file_id, local_download_path, opts)
```

If the API returns a non-success HTTP status or a JSON error body (including some HTTP 200 responses with `success: false`), the client raises `ZBApiException`. To inspect a raw body string yourself, use `ZeroBounce.get_file_json_indicates_error(body)`.

* ##### Delete the file that was submitted using _sendFile_ API. File can be deleted only when its status is `Complete`
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id="<FILE_ID>"     # The returned file ID when calling sendFile API

try:
    response = zero_bounce.delete_file(file_id)
    print("ZeroBounce delete_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce delete_file error: " + str(e))
```

### AI Scoring API

* ##### The _scoringSendFile_ API allows user to send a file for bulk email scoring
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_path = './email_file.csv'  # The csv or txt file
email_address_column = 1        # The index of "email" column in the file. Index starts at 1

return_url = "https://domain.com/called/after/processing/request"

has_header_row = False          # If the first row from the submitted file is a header row
remove_duplicate = True         # If you want the system to remove duplicate emails

try:
    response = zero_bounce.scoring_send_file(
        file_path,
        email_address_column,
        return_url,
        has_header_row,
        remove_duplicate,
    )
    print("ZeroBounce send_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce send_file error: " + str(e))
```

* ##### Check the status of a file uploaded via _scoringSendFile_ method
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id = "<FILE_ID>"       # The returned file ID when calling scoringSendFile API

try:
    response = zero_bounce.scoring_file_status(file_id)
    print("ZeroBounce file_status response: " + str(response))
except ZBException as e:
    print("ZeroBounce file_status error: " + str(e))
```

* ##### The scoring _scoringGetFile_ API allows users to get the validation results file for the file been submitted using scoring _scoringSendFile_ API
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id="<FILE_ID>"                         # The returned file ID when calling scoringSendFile API
local_download_path = "./dwnld_file.csv"    # The path where the file will be downloaded

try:
    response = zero_bounce.scoring_get_file(file_id, local_download_path)  # stream=True for large files
    print("ZeroBounce get_file response: " + str(response))
    # Optional third argument: ZBGetFileOptions with download_type only (activity_data is not used for scoring getfile)
    # response = zero_bounce.scoring_get_file(file_id, local_download_path, opts)
except ZBException as e:
    print("ZeroBounce get_file error: " + str(e))
```

* ##### Delete the file that was submitted using _scoringSendFile_ API. File can be deleted only when its status is `Complete`
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id="<FILE_ID>"     # The returned file ID when calling scoringSendFile API

try:
    response = zero_bounce.scoring_delete_file(file_id)
    print("ZeroBounce delete_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce delete_file error: " + str(e))
```

### Validation options

* ##### Validate with activity data, Verify+, WHOIS and greylist retry
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

try:
    response = zero_bounce.validate(
        "valid@example.com",
        timeout=30,                # 3-60 seconds; unknown/greylisted when it runs out
        activity_data=True,        # adds active_in_days and active_first_seen
        verify_plus=True,          # overrides the account's Verify+ setting
        domain_info=True,          # adds domain_website_exists and domain_registrant_company_name
        greylist_processing=True,  # process a greylisted address again instead of returning unknown
    )
    if response.message:           # greylist retry still running: call validate again in about 30 minutes
        print(response.message)
    else:
        print(response.status, response.domain_website_exists, response.domain_registrant_company_name)
except ZBException as e:
    print("ZeroBounce validate error: " + str(e))
```

With `greylist_processing=True`, pass `callback_url="https://..."` to have the result sent there instead of picking it up. Every option is omitted from the request until you set it, and `use_post=True` sends them as a form-encoded `POST`.

* ##### Score one email in real time
```python
response = zero_bounce.score_email("valid@example.com")  # GET /v2/scoring
print(response.email, response.score)
```

`get_credits`, `get_api_usage`, `get_activity`, `score_email`, `validate`, `list_filters`, `find_email_format` and `find_domain` take `use_post=True` to send the same parameters as a form-encoded `POST`, which the API accepts as well as `GET`.

### Bulk email finder and domain search

```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

try:
    # Columns are 1-based. Email finder needs a domain column and a first-name or full-name column.
    sent = zero_bounce.send_email_finder_file(
        "./people.csv", domain_column=3, first_name_column=1, last_name_column=2, has_header_row=True
    )
    print(zero_bounce.email_finder_file_status(sent.file_id))
    zero_bounce.email_finder_get_file(sent.file_id, "./people_results.csv")  # stream=True for large files
    zero_bounce.email_finder_delete_file(sent.file_id)  # only when the status is Complete

    sent = zero_bounce.send_domain_search_file("./domains.csv", domain_column=1, has_header_row=True)
    print(zero_bounce.domain_search_file_status(sent.file_id))
except ZBException as e:
    print("ZeroBounce bulk finder error: " + str(e))
```

### List evaluator

```python
sent = zero_bounce.send_list_evaluator_file("./list.csv", email_address_column=1)  # at least 100 emails
result = zero_bounce.get_list_evaluator_result(sent.file_id)  # .status (processing/finished), .progress, .invalid_percentage, ...
zero_bounce.send_evaluated_file("./list.csv")  # submit the evaluated list for validation
```

### Allowlist and blocklist filters

```python
zero_bounce.add_filter("block", "domain", "example.com")  # rule: allow | block; target: email | domain | mx | tld (checked before sending)
print(zero_bounce.list_filters())                         # [{"rule": ..., "target": ..., "value": ...}]
zero_bounce.delete_filter("block", "domain", "example.com")
```

### Amazon S3 and SFTP/FTP files

These run validation, scoring, the email finder or domain search on a file already in your Amazon S3 bucket or on your SFTP/FTP server, as configured in your ZeroBounce settings. See [Amazon S3 Bulk API](https://www.zerobounce.net/docs/api-integrations/amazon-s3-bulk-api) and [SFTP/FTP Bulk API](https://www.zerobounce.net/docs/api-integrations/sftp_bulk_api).

```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

try:
    files = zero_bounce.list_s3files(search="2026")       # [{"Name": ..., "Size": ..., "LastModified": ...}]
    name = files[0]["Name"]                                # full path in the bucket

    zero_bounce.validate_s3file(name, True, return_url="https://example.com/done")
    # Also: score_s3file, email_finder_s3file, domain_search_s3file (file_name, has_header_row, ...)
    zero_bounce.score_sftpfile("my_file.txt", True)       # file name on your SFTP/FTP server
    # Also: validate_sftpfile, email_finder_sftpfile, domain_search_sftpfile

    # When the file is processed, export it back with its file ID (from return_url's callback,
    # file_status, or the ZeroBounce app). The bucket/path default to the ones in your settings.
    zero_bounce.export_s3file("<FILE_ID>")
    zero_bounce.export_sftpfile("<FILE_ID>", export_path="/exports")
except ZBException as e:
    print("ZeroBounce S3/SFTP error: " + str(e))
```

`has_header_row` is required; `remove_duplicates` (default `True` on the API) and `return_url` are optional. The documented success response is `success` and `message`, without a file ID.

### Inbox Placement Tester

Tests use the account's inbox-test credits. The key is sent in the `Authorization: Bearer` header.

```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

try:
    providers = zero_bounce.get_inbox_placement_providers()
    test = zero_bounce.create_inbox_placement_test(
        "Spring launch",                  # unique, at most 64 characters
        test_type=3,                      # 1 Email (needs sender_email), 2 Unique ID, 3 Auto Alias
        webhook_url="https://example.com/ipt-webhook",
    )
    print(test["emailAddressList"])       # send the campaign to these seed addresses

    result = zero_bounce.get_inbox_placement_test(test["id"])
    print(result["status"], result.get("percentages"))

    finished = zero_bounce.list_inbox_placement_tests(status="finished", page_size=25)
    zero_bounce.delete_inbox_placement_test(test["id"])  # finished tests only
    zero_bounce.set_inbox_placement_webhook("https://example.com/ipt-webhook")
    print(zero_bounce.get_inbox_placement_webhook())
except ZBException as e:
    print("ZeroBounce inbox placement error: " + str(e))
```

### Warmup API

The [Warmup API](https://www.zerobounce.net/docs/warmup-api) has its own client: it uses a Warmup API key (bound to one team) in an `API-Key` header and its own host. Pass the base URL ZeroBounce gave you if it differs from the default `https://warmup-api.zerobounce.net`.

```python
from zerobouncesdk import ZeroBounceWarmup, ZBException, ZBApiException

warmup = ZeroBounceWarmup("<YOUR_WARMUP_API_KEY>")

try:
    print(warmup.get_engagement_rules())                       # -1 Custom, 0 Default ... 4 Protect
    warmup.add_sending_account("sender@example.com", "self_managed", engagement_rule_id=0)
    warmup.add_sending_account(
        "news@example.com",
        "zb_managed",
        email_content={"company_name": "Acme", "types_of_emails": ["newsletter"]},
        managed_sending={"weekdays_only": True, "timezone_offset": 3.0, "warmup_start_date": "2026-11-02"},
    )
    print(warmup.get_sending_account("sender@example.com"))
    print(warmup.check_domain_dmarc("example.com", dkim_selector="default"))
    warmup.set_engagement_rule("sender@example.com", 1)        # returns None (HTTP 204)
    warmup.create_custom_engagement("sender@example.com", reply_pct=20, important_pct=25, click_pct=25)
    print(warmup.get_statistics_per_day("sender@example.com", "2026-10-01", "2026-10-14"))
    csv_text = warmup.download_statistics("sender@example.com", "./stats.csv")
    warmup.update_sending_account("sender@example.com", engagement_rule_id=0, status_id=4, auto_enable=False)  # 4 = Paused
except ZBApiException as e:
    if e.status_code == 429:                                   # rate limit, or the custom-rule 7 day cooldown
        print("Try again later: " + str(e))
    else:
        print("ZeroBounce warmup error: " + str(e))
except ZBException as e:
    print("ZeroBounce warmup error: " + str(e))
```

Every documented endpoint has a method: sending accounts (`list_sending_accounts`, `get_sending_account`, `add_sending_account`, `update_sending_account`, `delete_sending_account`, `change_from_address`, `list_from_addresses`), engagement (`get_engagement_rules`, `set_engagement_rule`, `get_custom_engagement`, `create_custom_engagement`, `update_custom_engagement`, `delete_custom_engagement`), and statistics and utilities (`get_seeds`, `download_seeds`, `get_seed_count`, `get_progress_today`, `get_sent_today`, `get_emails_per_day`, `get_statistics`, `get_statistics_per_day`, `get_statistics_detailed`, `download_statistics`, `get_from_address_statistics`, `check_domain_dmarc`, `test_smtp_configuration`). Calls the API answers with 204 or an empty body return `None`; the two CSV downloads return the CSV text.

### Other hosts

`base_url` sets the host of the single-request API (validate, scoring, email finder, filters). The bulk APIs have their own class attributes, which you can set on an instance. ZeroBounce documents no regional bulk host, so with an EU or US `base_url` the bulk calls still go to `bulkapi.zerobounce.net`; the client warns once (`UserWarning`) when that happens, unless you set the bulk URLs yourself.

```python
zero_bounce = ZeroBounce("<YOUR_API_KEY>", base_url="https://api-eu.zerobounce.net/v2")
zero_bounce.BULK_BASE_URL = "https://bulkapi.zerobounce.net/v2"                     # send/status/get/delete file
zero_bounce.SCORING_BASE_URL = "https://bulkapi.zerobounce.net/v2/scoring"
zero_bounce.EMAIL_FINDER_BASE_URL = "https://bulkapi.zerobounce.net/email-finder"
zero_bounce.DOMAIN_SEARCH_BASE_URL = "https://bulkapi.zerobounce.net/domain-search"
zero_bounce.LIST_EVALUATOR_BASE_URL = "https://bulkapi.zerobounce.net/v2/listevaluator"
zero_bounce.INBOX_PLACEMENT_BASE_URL = "https://bulkapi.zerobounce.net/api/ipt"
zero_bounce.BULK_ROOT_URL = "https://bulkapi.zerobounce.net"                         # S3 and SFTP/FTP
```

Each of these must be an `https://` URL; the client refuses to send the key anywhere else.

* ##### (Deprecated) Identify the correct email format when you provide a name and email domain

> **⚠️ Deprecated:** The `guess_format` method is deprecated and will be removed in future versions. Use `find_email_format` or `find_domain` instead (see examples above).

```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

domain = "example.com" # The email domain for which to find the email format
first_name = "John" # The first name of the person whose email format is being searched
middle_name = "Quill" # The middle name of the person whose email format is being searched
last_name = "Doe" # The last name of the person whose email format is being searched

try:
    response = zero_bounce.guess_format(domain, first_name, middle_name, last_name)
    print("ZeroBounce guess format response: " + str(response))
except ZBException as e:
    print("ZeroBounce guess format error: " + str(e))
```

## DEVELOPMENT

### Local setup
```bash
python -m venv venv   # Python 3.10+ recommended
source venv/bin/activate
pip install -e ".[test]"
pip install ruff==0.17.2
```

### Lint and test
```bash
ruff check src tests
python -m compileall -q src tests
python -m pytest
```

`python -m pytest` runs every offline suite: the scripted unit tests and the `tests/test_*.py` suites, which answer through a fake transport and never call the API. CI runs the same commands, with coverage.

### Live API tests
`tests/zero_bounce_integration_test.py` calls the real API and is not collected by `pytest`. Run it with a valid key:

```bash
export ZEROBOUNCE_API_KEY=<apikey>
python -m unittest tests.zero_bounce_integration_test -v
```

Without `ZEROBOUNCE_API_KEY` its tests are skipped. It covers the original single-request methods; the newer APIs are tested offline only.

### Run tests with Docker
```bash
docker build -t zb-python-sdk .
docker run --rm zb-python-sdk
```

From the **`sdk-docs/`** folder in the SDKs monorepo, `docker compose build python` and `docker compose run --rm python` do the same.

## Publish

1. Bump `version` in `pyproject.toml`, commit, tag (`vX.Y.Z`), push tag.
2. **Actions → Publish → Run workflow** with that tag.

Registry: [zerobouncesdk on PyPI](https://pypi.org/project/zerobouncesdk/)

The workflow publishes with [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/); no PyPI token is stored anywhere. The `zerobouncesdk` project on PyPI trusts this repository's `.github/workflows/publish.yml` running in the `release` environment, and the publish job (which has `id-token: write`) exchanges its GitHub OIDC token for a short-lived upload token. Each release also gets signed attestations. Renaming the workflow file or the environment breaks publishing until the trusted publisher on PyPI (project → Publishing) is updated to match.
