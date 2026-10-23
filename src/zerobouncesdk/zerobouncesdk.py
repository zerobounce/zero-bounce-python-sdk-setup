import json
import re
import warnings
from datetime import date, timedelta
import os
from typing import BinaryIO, List, Optional, Union
from urllib.parse import quote, quote_plus

import requests
from requests.exceptions import RequestException

from .zb_get_file_options import ZBGetFileOptions
from . import (
    ZBApiException,
    ZBApiUrl,
    ZBClientException,
    ZBGetCreditsResponse,
    ZBGetApiUsageResponse,
    ZBGetActivityResponse,
    ZBScoreEmailResponse,
    ZBValidateResponse,
    ZBValidateBatchElement,
    ZBValidateBatchResponse,
    ZBSendFileResponse,
    ZBListEvaluatorResponse,
    ZBFileStatusResponse,
    ZBGetFileResponse,
    ZBDeleteFileResponse,
    ZBGuessFormatResponse,
    ZBFindEmailFormatResponse,
    ZBFindDomainResponse,
)


def _looks_like_html(body: str, content_type: str = "") -> bool:
    if content_type and "text/html" in content_type.lower():
        return True
    sample = (body or "").lstrip()[:2000].lower()
    return (
        "<!doctype html" in sample
        or "<html" in sample
        or "<head" in sample
        or "<body" in sample
    )


def _html_title(body: str) -> str:
    snippet = body[:8000]
    lower = snippet.lower()
    start = lower.find("<title")
    if start < 0:
        return ""
    open_end = lower.find(">", start)
    if open_end < 0:
        return ""
    close = lower.find("</title>", open_end)
    if close < 0:
        return ""
    return snippet[open_end + 1:close].strip()


def _strip_error_prefix(message: str) -> str:
    """Collapse a repeated ``Error:`` / ``[Error]:`` prefix and leave a single one."""
    stripped = message.strip()
    changed = True
    while changed:
        changed = False
        match = re.match(r"(?i)(?:error:\s*){2,}", stripped)
        if match:
            stripped = ("Error: " + stripped[match.end():]).strip()
            changed = True
        match = re.match(r"(?i)(?:\[error\]:\s*){2,}", stripped)
        if match:
            stripped = ("[Error]: " + stripped[match.end():]).strip()
            changed = True
    return stripped


def _message_from_body(body: str, status_code: int) -> str:
    """Turn an HTTP body into a short message. Never return raw HTML or a parser exception."""
    trimmed = (body or "").strip()
    if not trimmed:
        return "Empty response from ZeroBounce (HTTP %s)" % status_code
    if _looks_like_html(body):
        title = _html_title(body)
        if title and "access denied" in title.lower():
            return "Access denied"
        if title:
            return 'ZeroBounce returned an HTML error page ("%s") instead of an API response.' % title
        return "ZeroBounce returned an HTML error page instead of an API response."
    if trimmed[0] in "{[":
        try:
            parsed = json.loads(trimmed)
        except ValueError:
            return "ZeroBounce returned a response that is not valid JSON."
        if isinstance(parsed, dict):
            title = parsed.get("title")
            if isinstance(title, str) and ("Access denied" in title or "1020" in title):
                has_api_message = False
                for key in ("error", "message", "error_message"):
                    value = parsed.get(key)
                    if isinstance(value, str) and value.strip():
                        has_api_message = True
                    elif isinstance(value, list) and value:
                        has_api_message = True
                if parsed.get("cloudflare_error") is True or not has_api_message:
                    return title
            # "detail" is how the Inbox Placement Tester (Django REST framework) reports errors.
            for key in ("message", "error", "error_message", "detail"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return _strip_error_prefix(value)
                if isinstance(value, list) and value and isinstance(value[0], str) and value[0].strip():
                    return _strip_error_prefix(value[0])
                # A validation error list: [{"loc": ["body", "field"], "msg": "...", ...}, ...].
                if isinstance(value, list) and value and isinstance(value[0], dict) and value[0].get("msg"):
                    loc = value[0].get("loc")
                    field = ".".join(str(part) for part in loc[1:]) if isinstance(loc, list) and len(loc) > 1 else ""
                    return f"{field}: {value[0]['msg']}" if field else str(value[0]["msg"])
        if len(trimmed) > 500:
            return "ZeroBounce returned an error (HTTP %s)." % status_code
        return trimmed
    if len(trimmed) > 1000 or any(char in trimmed for char in "{}[]<>"):
        return "ZeroBounce returned a response that is not valid JSON."
    message = _strip_error_prefix(trimmed)
    if not message:
        return "Empty response from ZeroBounce (HTTP %s)" % status_code
    return message


def _form_data(data):
    """Encode booleans as the strings ``true`` and ``false`` for form and multipart bodies.

    ``requests`` would otherwise send a Python bool as ``True`` or ``False``.
    """
    if not isinstance(data, dict):
        return data
    encoded = {}
    for key, value in data.items():
        if isinstance(value, bool):
            encoded[key] = "true" if value else "false"
        else:
            encoded[key] = value
    return encoded


def _response_text(response) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return content.decode("utf-8", errors="replace")
    text = getattr(response, "text", "")
    return text if isinstance(text, str) else ""


class ZeroBounce:
    """The ZeroBounce main class. All the requests are implemented here."""

    BULK_BASE_URL = "https://bulkapi.zerobounce.net/v2"
    BULK_ROOT_URL = "https://bulkapi.zerobounce.net"
    EMAIL_FINDER_BASE_URL = "https://bulkapi.zerobounce.net/email-finder"
    DOMAIN_SEARCH_BASE_URL = "https://bulkapi.zerobounce.net/domain-search"
    SCORING_BASE_URL = "https://bulkapi.zerobounce.net/v2/scoring"
    LIST_EVALUATOR_BASE_URL = "https://bulkapi.zerobounce.net/v2/listevaluator"
    INBOX_PLACEMENT_BASE_URL = "https://bulkapi.zerobounce.net/api/ipt"
    DEFAULT_HTTP_TIMEOUT_S = 120.0
    IPT_TEST_TYPES = (1, 2, 3)
    IPT_TEST_STATUSES = ("running", "finished")
    # Documented: letters, numbers and - / \ , . & ' ( ). Spaces are accepted too.
    IPT_NAME_PUNCTUATION = frozenset(" -/\\,.&'()")

    @staticmethod
    def _require_https_url(url: str) -> str:
        if not url.lower().startswith("https://"):
            raise ZBClientException("base_url must be an https:// URL")
        return url.rstrip("/")

    def __init__(self, api_key: str, base_url: Optional[Union[ZBApiUrl, str]] = None, timeout: Optional[timedelta] = None):
        """Initialize the ZeroBounce client.

        Parameters
        ----------
        api_key: str
            Your ZeroBounce API key
        base_url: Optional[Union[ZBApiUrl, str]], default ZBApiUrl.API_DEFAULT_URL
            The base URL for the API. Can be a ZBApiUrl enum value, a custom URL string,
            or None to use the default URL.
        timeout: Optional[timedelta], default timeout to use for API requests.

        Raises
        ------
        ZBClientException
            If api_key is empty
        """
        if not api_key.strip():
            raise ZBClientException("Empty parameter: api_key")
        self._api_key = api_key
        
        # Handle base_url: enum, string, or default
        if base_url is None:
            self._base_url = ZBApiUrl.API_DEFAULT_URL.value
        elif isinstance(base_url, ZBApiUrl):
            self._base_url = base_url.value
        elif isinstance(base_url, str):
            self._base_url = self._require_https_url(base_url)
        else:
            raise ZBClientException(f"Invalid base_url type: {type(base_url)}. Expected ZBApiUrl, str, or None.")
        
        # Remove trailing slash if present to maintain consistent URL construction
        self._base_url = self._base_url.rstrip('/')

        self._timeout_s: float = (
            self.DEFAULT_HTTP_TIMEOUT_S if timeout is None else timeout.total_seconds()
        )

    @staticmethod
    def get_file_json_indicates_error(body: str) -> bool:
        """Whether a getfile response body looks like a JSON error payload (including HTTP 200)."""
        t = body.lstrip()
        if not t or t[0] != "{":
            return False
        try:
            o = json.loads(body)
        except ValueError:
            return False
        if not isinstance(o, dict):
            return False
        if "success" in o:
            s = o["success"]
            if s is False or s == "False" or s == "false":
                return True
        for k in ("message", "error", "error_message"):
            v = o.get(k)
            if v:
                if isinstance(v, str) and v.strip():
                    return True
                if isinstance(v, list) and len(v) > 0:
                    return True
        return "success" in o

    @staticmethod
    def _should_treat_get_file_body_as_error(body: str, content_type: str) -> bool:
        ct = content_type.lower()
        if "application/json" in ct:
            return True
        return ZeroBounce.get_file_json_indicates_error(body)

    def _redact(self, text) -> str:
        """Mask the API key in text that can end up in exception messages or logs."""
        text = str(text)
        for secret in (self._api_key, quote_plus(self._api_key)):
            text = text.replace(secret, "***")
        return text

    def _read_json_payload(self, response):
        body = _response_text(response)
        status = getattr(response, "status_code", 0) or 0
        headers = getattr(response, "headers", None) or {}
        content_type = headers.get("Content-Type") or headers.get("content-type") or ""
        if 300 <= status < 400:
            raise ZBApiException(
                self._redact("ZeroBounce returned a redirect, which this client does not follow.")
            )
        if status > 299 or _looks_like_html(body, content_type) or not body.strip():
            raise ZBApiException(self._redact(_message_from_body(body, status)))
        try:
            payload = response.json()
        except ValueError:
            raise ZBApiException(self._redact(_message_from_body(body, status))) from None
        if isinstance(payload, dict):
            title = payload.get("title")
            if isinstance(title, str) and payload.get("cloudflare_error") is True:
                raise ZBApiException(self._redact(title))
            error = None
            for key in ("error", "Error"):
                if key in payload and payload[key]:
                    error = payload[key]
                    break
            if isinstance(error, str) and error.strip():
                raise ZBApiException(self._redact(_strip_error_prefix(error)))
            if error:
                raise ZBApiException(self._redact(str(error)))
            success = payload.get("success")
            failed = success is False or (
                isinstance(success, str) and success.lower() == "false"
            )
            if failed:
                message = payload.get("message") or payload.get("error_message") or "Request failed"
                if isinstance(message, list):
                    message = message[0] if message else "Request failed"
                text = str(message).strip() or "Request failed"
                raise ZBApiException(self._redact(_strip_error_prefix(text)))
        return payload

    def _raise_if_download_error(self, response, body_str: str, content_type: str) -> None:
        status = response.status_code
        if 300 <= status < 400:
            raise ZBApiException(
                self._redact("ZeroBounce returned a redirect, which this client does not follow.")
            )
        if not (body_str or "").strip():
            raise ZBApiException(self._redact(_message_from_body(body_str, status)))
        if (
            status > 299
            or _looks_like_html(body_str, content_type)
            or self._should_treat_get_file_body_as_error(body_str, content_type)
        ):
            raise ZBApiException(self._redact(_message_from_body(body_str, status)))

    def _get(self, url, response_class, params=None):
        if not params:
            params = {}
        params["api_key"] = self._api_key
        try:
            response = requests.get(url, params=params, timeout=self._timeout_s, allow_redirects=False)
        except RequestException as e:
            raise type(e)(self._redact(e)) from None
        return response_class(self._read_json_payload(response))

    def _post(self, url, response_class, data=None, json=None, files=None):
        try:
            response = requests.post(
                url,
                data=_form_data(data),
                json=json,
                files=files,
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except RequestException as e:
            raise type(e)(self._redact(e)) from None
        return response_class(self._read_json_payload(response))

    def _post_form(self, url, response_class, data=None):
        if not data:
            data = {}
        data = dict(data)
        data["api_key"] = self._api_key
        try:
            response = requests.post(
                url, data=_form_data(data), timeout=self._timeout_s, allow_redirects=False
            )
        except RequestException as e:
            raise type(e)(self._redact(e)) from None
        return response_class(self._read_json_payload(response))

    def _request_json(self, method: str, url: str, *, params=None, data=None, files=None, json=None):
        if params is None:
            params = {}
        if "api_key" not in params and (data is None or "api_key" not in data):
            params = dict(params)
            params["api_key"] = self._api_key
        try:
            response = requests.request(
                method,
                url,
                params=params,
                data=_form_data(data),
                files=files,
                json=json,
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except RequestException as e:
            raise type(e)(self._redact(e)) from None
        return self._read_json_payload(response)

    def _send_bulk_root_multipart(
        self, url: str, file_path: str, fields: dict
    ) -> ZBSendFileResponse:
        data = dict(fields)
        data["api_key"] = self._api_key
        with open(file_path, "rb") as file:
            files = {"file": (os.path.basename(file_path), file, "text/csv")}
            return self._post(url, ZBSendFileResponse, data=data, files=files)

    def _send_bulk_root_multipart_stream(
        self, url: str, file_stream: BinaryIO, file_name: str, fields: dict
    ) -> ZBSendFileResponse:
        data = dict(fields)
        data["api_key"] = self._api_key
        files = {"file": (file_name, file_stream, "text/csv")}
        return self._post(url, ZBSendFileResponse, data=data, files=files)

    def _bulk_root_file_status(self, base_url: str, file_id: str) -> ZBFileStatusResponse:
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._get(
            f"{base_url}/filestatus",
            ZBFileStatusResponse,
            params={"file_id": file_id},
        )

    def _bulk_root_get_file(
        self,
        base_url: str,
        file_id: str,
        download_path: str,
    ) -> ZBGetFileResponse:
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        params = {"api_key": self._api_key, "file_id": file_id}
        try:
            response = requests.get(
                f"{base_url}/getfile",
                params=params,
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except RequestException as e:
            raise type(e)(self._redact(e)) from None
        body_bytes = response.content or b""
        body_str = body_bytes.decode("utf-8", errors="replace")
        content_type = response.headers.get("Content-Type") or ""
        self._raise_if_download_error(response, body_str, content_type)
        dirname = os.path.dirname(download_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(download_path, "wb") as f:
            f.write(body_bytes)
        return ZBGetFileResponse({"local_file_path": download_path})

    def _bulk_root_delete_file(self, base_url: str, file_id: str) -> ZBDeleteFileResponse:
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._get(
            f"{base_url}/deletefile",
            ZBDeleteFileResponse,
            params={"file_id": file_id},
        )

    def _post_bulk_root_form(self, path: str, fields: dict) -> ZBSendFileResponse:
        data = dict(fields)
        data["api_key"] = self._api_key
        return self._post(
            f"{self.BULK_ROOT_URL}{path}",
            ZBSendFileResponse,
            data=data,
        )

    def _get_or_post_form(self, url, response_class, params, use_post: bool):
        """GET with query parameters, or the documented form-encoded POST with the same parameters."""
        if use_post:
            return self._post_form(url, response_class, data=params)
        return self._get(url, response_class, params=params)

    def get_credits(self, use_post: bool = False):
        """Tells you how many credits you have left on your account.
        It's simple, fast and easy to use.

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBGetCreditsResponse
            Returns a ZBGetCreditsResponse object if the request was successful
        """

        return self._get_or_post_form(f"{self._base_url}/getcredits", ZBGetCreditsResponse, {}, use_post)

    def get_api_usage(self, start_date: date, end_date: date, use_post: bool = False):
        """Returns the API usage between the given dates.

        Parameters
        ----------
        start_date: date
            The start date of when you want to view API usage
        end_date: date
            The end date of when you want to view API usage

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBGetApiUsageResponse
            Returns a ZBGetApiUsageResponse object if the request was successful
        """

        return self._get_or_post_form(
            f"{self._base_url}/getapiusage",
            ZBGetApiUsageResponse,
            {
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            },
            use_post,
        )

    def get_activity(self, email: str, use_post: bool = False):
        """Allows you to gather insights into your subscribers' overall email engagement

        Parameters
        ----------
        email: str
            The email whose activity you want to check

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBGetActivityResponse
            Returns a ZBGetActivityResponse object if the request was successful
        """

        return self._get_or_post_form(
            f"{self._base_url}/activity", ZBGetActivityResponse, {"email": email}, use_post
        )

    def score_email(self, email: str, use_post: bool = False):
        """Real-time AI scoring for a single email (GET or POST /scoring).

        Parameters
        ----------
        email: str
            The email address to score
        use_post: bool
            When True, sends ``api_key`` and ``email`` as form-encoded POST body.

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBScoreEmailResponse
        """

        if use_post:
            return self._post_form(
                f"{self._base_url}/scoring",
                ZBScoreEmailResponse,
                data={"email": email},
            )
        return self._get(
            f"{self._base_url}/scoring",
            ZBScoreEmailResponse,
            params={"email": email},
        )

    @staticmethod
    def _check_validate_timeout(timeout: Optional[int]) -> None:
        if timeout is not None and (timeout < 3 or timeout > 60):
            raise ZBClientException("Invalid parameter: timeout (must be between 3 and 60 seconds)")

    @staticmethod
    def _check_validate_batch_timeout(timeout: Optional[int]) -> None:
        if timeout is not None and (timeout < 10 or timeout > 120):
            raise ZBClientException("Invalid parameter: timeout (must be between 10 and 120 seconds)")

    def validate(
        self,
        email: str,
        ip_address: str = None,
        timeout: Optional[int] = None,
        activity_data: Optional[bool] = None,
        verify_plus: Optional[bool] = None,
        use_post: bool = False,
        domain_info: Optional[bool] = None,
        greylist_processing: Optional[bool] = None,
        callback_url: Optional[str] = None,
    ):
        """Validates the given email address.

        Parameters
        ----------
        email: str
            The email address you want to validate
        ip_address: str or None
            The IP Address the email signed up from (Can be blank)
        timeout: int or None
            Validation timeout in seconds (3-60). Optional.
        activity_data: bool or None
            When set, sends ``activity_data`` query parameter.
        verify_plus: bool or None
            When set, sends ``verify_plus`` query parameter.
        use_post: bool
            When True, sends parameters as form-encoded POST body.
        domain_info: bool or None
            When True, the response adds ``domain_website_exists`` and
            ``domain_registrant_company_name`` (website availability and WHOIS).
        greylist_processing: bool or None
            When True, a greylisted address is processed again instead of returned as unknown.
            Without ``callback_url``, call ``validate`` again after about 30 minutes to pick up
            the result; until then the response's ``message`` says it is still in progress.
        callback_url: str or None
            With ``greylist_processing=True``, the URL the result is sent to when it is ready.

        Raises
        ------
        ZBApiException
        ZBClientException

        Returns
        -------
        response: ZBValidateResponse
            Returns a ZBValidateResponse object if the request was successful
        """
        self._check_validate_timeout(timeout)
        if callback_url is not None and greylist_processing is not True:
            raise ZBClientException("Invalid parameter: callback_url requires greylist_processing=True")
        if callback_url is not None and not callback_url.strip():
            raise ZBClientException("Empty parameter: callback_url")

        params = {
            "email": email,
            "ip_address": ip_address,
        }
        if timeout is not None:
            params["timeout"] = timeout
        if activity_data is not None:
            params["activity_data"] = "true" if activity_data else "false"
        if verify_plus is not None:
            params["verify_plus"] = "true" if verify_plus else "false"
        if domain_info is not None:
            params["domain_info"] = "true" if domain_info else "false"
        if greylist_processing is not None:
            params["greylist_processing"] = "true" if greylist_processing else "false"
        if callback_url is not None:
            params["callback_url"] = callback_url

        if use_post:
            return self._post_form(
                f"{self._base_url}/validate",
                ZBValidateResponse,
                data=params,
            )
        return self._get(
            f"{self._base_url}/validate",
            ZBValidateResponse,
            params=params,
        )

    def validate_batch(
        self,
        email_batch: List[ZBValidateBatchElement],
        timeout: Optional[int] = None,
        activity_data: Optional[bool] = None,
        verify_plus: Optional[bool] = None,
    ):
        """Allows you to send us batches up to 100 emails at a time.

        Parameters
        ----------
        email_batch: List[ZBValidateBatchElement]
            Array of ZBValidateBatchElement
        timeout: int or None
            Batch validation timeout in seconds (10-120). Optional.
        activity_data: bool or None
            When set, includes activity data on each result.
        verify_plus: bool or None
            When true, uses Verify+ for validation.

        Raises
        ------
        ZBApiException
        ZBClientException

        Returns
        -------
        response: ZBValidateBatchResponse
            Returns a ZBValidateBatchResponse object if the request was successful
        """
        if not email_batch:
            raise ZBClientException("Empty parameter: email_batch")
        self._check_validate_batch_timeout(timeout)

        payload = {
            "api_key": self._api_key,
            "email_batch": [
                batch_element.to_json() for batch_element in email_batch
            ],
        }
        if timeout is not None:
            payload["timeout"] = timeout
        if activity_data is not None:
            payload["activity_data"] = activity_data
        if verify_plus is not None:
            payload["verify_plus"] = verify_plus
        result = self._post(
            f"{self._base_url}/validatebatch",
            ZBValidateBatchResponse,
            json=payload)
        for batch_error in result.errors or []:
            address = (batch_error.email_address or "").strip().lower()
            if address == "all":
                text = batch_error.error or "Invalid API Key or your account ran out of credits"
                if isinstance(text, str):
                    text = _strip_error_prefix(text)
                raise ZBApiException(text)
        return result

    def _send_file(
        self,
        scoring: bool,
        file_path: str,
        email_address_column: int,
        data: dict,
    ):
        data.update(
            {
                "api_key": self._api_key,
                "email_address_column": email_address_column,
            }
        )
        url = f"{self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL}/sendfile"
        with open(file_path, "rb") as file:
            files = {"file": (os.path.basename(file_path), file, "text/csv")}
            return self._post(url, ZBSendFileResponse, data=data, files=files)

    def _send_file_from_stream(
        self,
        scoring: bool,
        file_stream: BinaryIO,
        file_name: str,
        email_address_column: int,
        data: dict,
    ):
        data = dict(data)
        data.update(
            {
                "api_key": self._api_key,
                "email_address_column": email_address_column,
            }
        )
        url = f"{self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL}/sendfile"
        files = {"file": (file_name, file_stream, "text/csv")}
        return self._post(url, ZBSendFileResponse, data=data, files=files)

    def send_file(
        self,
        file_path: str,
        email_address_column: int,
        return_url: str = None,
        first_name_column: int = None,
        last_name_column: int = None,
        gender_column: int = None,
        ip_address_column: int = None,
        has_header_row: bool = False,
        remove_duplicate: bool = True,
        allow_phase_2: Optional[bool] = None,
    ):
        """Allows user to send a file for bulk email validation

        Parameters
        ----------
        file_path: str
            The path of the csv or txt file to be submitted.
        email_address_column: int
            The column index of the email address in the file. Index starts from 1.
        return_url: str or None
            The URL will be used to call back when the validation is completed.
        first_name_column: int or None
            The column index of the first name column.
        last_name_column: int or None
            The column index of the last name column.
        gender_column: int or None
            The column index of the gender column.
        ip_address_column: int or None
            The IP Address the email signed up from.
        has_header_row: bool
            If the first row from the submitted file is a header row.
        remove_duplicate: bool
            If you want the system to remove duplicate emails.
        allow_phase_2: bool or None
            When not None, sends allow_phase_2 (validation bulk sendfile only).

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBSendFileResponse
            Returns a ZBSendFileResponse object if the request was successful
        """

        data = {}
        if return_url is not None:
            data["return_url"] = return_url
        if first_name_column is not None:
            data["first_name_column"] = first_name_column
        if last_name_column is not None:
            data["last_name_column"] = last_name_column
        if gender_column is not None:
            data["gender_column"] = gender_column
        if ip_address_column is not None:
            data["ip_address_column"] = ip_address_column
        if has_header_row is not None:
            data["has_header_row"] = has_header_row
        if remove_duplicate is not None:
            data["remove_duplicate"] = remove_duplicate
        if allow_phase_2 is not None:
            data["allow_phase_2"] = "true" if allow_phase_2 else "false"

        return self._send_file(False, file_path, email_address_column, data)

    def send_file_stream(
        self,
        file_stream: BinaryIO,
        file_name: str,
        email_address_column: int,
        return_url: str = None,
        first_name_column: int = None,
        last_name_column: int = None,
        gender_column: int = None,
        ip_address_column: int = None,
        has_header_row: bool = False,
        remove_duplicate: bool = True,
        allow_phase_2: Optional[bool] = None,
    ):
        """Send a file for bulk email validation from a stream (e.g. in-memory CSV or uploaded file).

        Parameters
        ----------
        file_stream: BinaryIO
            A file-like object opened in binary mode (e.g. io.BytesIO, or open(..., "rb")).
        file_name: str
            The file name to use for the upload (e.g. "emails.csv").
        email_address_column: int
            The column index of the email address in the file. Index starts from 1.
        return_url: str or None
            The URL will be used to call back when the validation is completed.
        first_name_column: int or None
            The column index of the first name column.
        last_name_column: int or None
            The column index of the last name column.
        gender_column: int or None
            The column index of the gender column.
        ip_address_column: int or None
            The IP Address the email signed up from.
        has_header_row: bool
            If the first row from the submitted file is a header row.
        remove_duplicate: bool
            If you want the system to remove duplicate emails.
        allow_phase_2: bool or None
            When not None, sends allow_phase_2 (validation bulk sendfile only).

        Returns
        -------
        response: ZBSendFileResponse
        """
        data = {}
        if return_url is not None:
            data["return_url"] = return_url
        if first_name_column is not None:
            data["first_name_column"] = first_name_column
        if last_name_column is not None:
            data["last_name_column"] = last_name_column
        if gender_column is not None:
            data["gender_column"] = gender_column
        if ip_address_column is not None:
            data["ip_address_column"] = ip_address_column
        if has_header_row is not None:
            data["has_header_row"] = has_header_row
        if remove_duplicate is not None:
            data["remove_duplicate"] = remove_duplicate
        if allow_phase_2 is not None:
            data["allow_phase_2"] = "true" if allow_phase_2 else "false"

        return self._send_file_from_stream(
            False, file_stream, file_name, email_address_column, data
        )

    def scoring_send_file(
        self,
        file_path: str,
        email_address_column: int,
        return_url: str = None,
        has_header_row: bool = False,
        remove_duplicate: bool = True,
    ):
        """Allows user to send a file for bulk email scoring

        Parameters
        ----------
        file_path: str
            The path of the csv or txt file to be submitted.
        email_address_column: int
            The column index of the email address in the file. Index starts from 1.
        return_url: str or None
            The URL will be used to call back when the validation is completed.
        has_header_row: bool
            If the first row from the submitted file is a header row.
        remove_duplicate: bool
            If you want the system to remove duplicate emails.

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBSendFileResponse
            Returns a ZBSendFileResponse object if the request was successful
        """

        data = {}
        if return_url is not None:
            data["return_url"] = return_url
        if has_header_row is not None:
            data["has_header_row"] = has_header_row
        if remove_duplicate is not None:
            data["remove_duplicate"] = remove_duplicate

        return self._send_file(True, file_path, email_address_column, data)

    def scoring_send_file_stream(
        self,
        file_stream: BinaryIO,
        file_name: str,
        email_address_column: int,
        return_url: str = None,
        has_header_row: bool = False,
        remove_duplicate: bool = True,
    ):
        """Send a file for bulk email scoring from a stream.

        Parameters
        ----------
        file_stream: BinaryIO
            A file-like object opened in binary mode.
        file_name: str
            The file name to use for the upload (e.g. "emails.csv").
        email_address_column: int
            The column index of the email address in the file. Index starts from 1.
        return_url: str or None
            The URL will be used to call back when the validation is completed.
        has_header_row: bool
            If the first row from the submitted file is a header row.
        remove_duplicate: bool
            If you want the system to remove duplicate emails.

        Returns
        -------
        response: ZBSendFileResponse
        """
        data = {}
        if return_url is not None:
            data["return_url"] = return_url
        if has_header_row is not None:
            data["has_header_row"] = has_header_row
        if remove_duplicate is not None:
            data["remove_duplicate"] = remove_duplicate

        return self._send_file_from_stream(
            True, file_stream, file_name, email_address_column, data
        )

    def _file_status(self, scoring: bool, file_id: str):
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._get(
            f"{self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL}/filestatus",
            ZBFileStatusResponse,
            params={"file_id": file_id},
        )

    def file_status(self, file_id: str):
        """Returns the file processing status for the file that has been submitted

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.

        Raises
        ------
        ZBClientException

        Returns
        -------
        response: ZBSendFileResponse
            Returns a ZBSendFileResponse object if the request was successful
        """

        return self._file_status(False, file_id)

    def scoring_file_status(self, file_id: str):
        """Returns the file processing status for the file that has been submitted

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.

        Raises
        ------
        ZBClientException

        Returns
        -------
        response: ZBSendFileResponse
            Returns a ZBSendFileResponse object if the request was successful
        """

        return self._file_status(True, file_id)

    def _get_file(
        self,
        scoring: bool,
        file_id: str,
        download_path: str,
        options: Optional[ZBGetFileOptions] = None,
    ):
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        params = {
            "api_key": self._api_key,
            "file_id": file_id,
        }
        if options is not None:
            if options.download_type:
                params["download_type"] = options.download_type
            if not scoring and options.activity_data is not None:
                params["activity_data"] = "true" if options.activity_data else "false"

        try:
            response = requests.get(
                f"{self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL}/getfile",
                params=params,
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except RequestException as e:
            raise type(e)(self._redact(e)) from None
        body_bytes = response.content or b""
        body_str = body_bytes.decode("utf-8", errors="replace")
        content_type = response.headers.get("Content-Type") or ""
        self._raise_if_download_error(response, body_str, content_type)

        dirname = os.path.dirname(download_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(download_path, "wb") as f:
            f.write(body_bytes)

        return ZBGetFileResponse({"local_file_path": download_path})

    def get_file(
        self,
        file_id: str,
        download_path: str,
        options: Optional[ZBGetFileOptions] = None,
    ):
        """Allows you to get the validation results for the file you submitted

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.
        download_path: str
            The local path where the file will be downloaded.
        options: ZBGetFileOptions or None
            Optional download_type and activity_data (validation bulk getfile only).

        Raises
        ------
        ZBClientException
        ZBApiException

        Returns
        -------
        response: ZBGetFileResponse
            Returns a ZBGetFileResponse object if the request was successful
        """

        return self._get_file(False, file_id, download_path, options)

    def scoring_get_file(
        self,
        file_id: str,
        download_path: str,
        options: Optional[ZBGetFileOptions] = None,
    ):
        """Allows you to get the validation results for the file you submitted

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.
        download_path: str
            The local path where the file will be downloaded.
        options: ZBGetFileOptions or None
            Optional download_type; activity_data is not sent for scoring getfile.

        Raises
        ------
        ZBClientException
        ZBApiException

        Returns
        -------
        response: ZBGetFileResponse
            Returns a ZBGetFileResponse object if the request was successful
        """

        return self._get_file(True, file_id, download_path, options)

    def _delete_file(self, scoring: bool, file_id: str):
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._get(
            f"{self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL}/deletefile",
            ZBDeleteFileResponse,
            params={"file_id": file_id},
        )

    def delete_file(self, file_id: str):
        """Deletes the file that you submitted
        Please note that the file can be deleted only when its status is Complete

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.

        Raises
        ------
        ZBApiException
        ZBClientException

        Returns
        -------
        response: ZBDeleteFileResponse
            Returns a ZBDeleteFileResponse object if the request was successful
        """

        return self._delete_file(False, file_id)

    def scoring_delete_file(self, file_id: str):
        """Deletes the file that you submitted
        Please note that the file can be deleted only when its status is Complete

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.

        Raises
        ------
        ZBApiException
        ZBClientException

        Returns
        -------
        response: ZBDeleteFileResponse
            Returns a ZBDeleteFileResponse object if the request was successful
        """

        return self._delete_file(True, file_id)

    # Priority 3 — bulk email finder (bulkapi …/email-finder/*)

    def send_email_finder_file(
        self,
        file_path: str,
        domain_column: int,
        first_name_column: int = None,
        last_name_column: int = None,
        middle_name_column: int = None,
        full_name_column: int = None,
        has_header_row: bool = False,
    ) -> ZBSendFileResponse:
        if domain_column is None:
            raise ZBClientException("Empty parameter: domain_column")
        if first_name_column is None and full_name_column is None:
            raise ZBClientException("Empty parameter: first_name_column or full_name_column is required")
        fields = {"domain_column": domain_column, "has_header_row": has_header_row}
        if first_name_column is not None:
            fields["first_name_column"] = first_name_column
        if last_name_column is not None:
            fields["last_name_column"] = last_name_column
        if middle_name_column is not None:
            fields["middle_name_column"] = middle_name_column
        if full_name_column is not None:
            fields["full_name_column"] = full_name_column
        return self._send_bulk_root_multipart(
            f"{self.EMAIL_FINDER_BASE_URL}/sendfile", file_path, fields
        )

    def send_email_finder_file_stream(
        self,
        file_stream: BinaryIO,
        file_name: str,
        domain_column: int,
        first_name_column: int = None,
        last_name_column: int = None,
        middle_name_column: int = None,
        full_name_column: int = None,
        has_header_row: bool = False,
    ) -> ZBSendFileResponse:
        if domain_column is None:
            raise ZBClientException("Empty parameter: domain_column")
        if first_name_column is None and full_name_column is None:
            raise ZBClientException("Empty parameter: first_name_column or full_name_column is required")
        fields = {"domain_column": domain_column, "has_header_row": has_header_row}
        if first_name_column is not None:
            fields["first_name_column"] = first_name_column
        if last_name_column is not None:
            fields["last_name_column"] = last_name_column
        if middle_name_column is not None:
            fields["middle_name_column"] = middle_name_column
        if full_name_column is not None:
            fields["full_name_column"] = full_name_column
        return self._send_bulk_root_multipart_stream(
            f"{self.EMAIL_FINDER_BASE_URL}/sendfile",
            file_stream,
            file_name,
            fields,
        )

    def email_finder_file_status(self, file_id: str) -> ZBFileStatusResponse:
        return self._bulk_root_file_status(self.EMAIL_FINDER_BASE_URL, file_id)

    def email_finder_get_file(self, file_id: str, download_path: str) -> ZBGetFileResponse:
        return self._bulk_root_get_file(self.EMAIL_FINDER_BASE_URL, file_id, download_path)

    def email_finder_delete_file(self, file_id: str) -> ZBDeleteFileResponse:
        return self._bulk_root_delete_file(self.EMAIL_FINDER_BASE_URL, file_id)

    # Priority 3 — bulk domain search (bulkapi …/domain-search/*)

    def send_domain_search_file(
        self,
        file_path: str,
        domain_column: int,
        has_header_row: bool = False,
    ) -> ZBSendFileResponse:
        if domain_column is None:
            raise ZBClientException("Empty parameter: domain_column")
        return self._send_bulk_root_multipart(
            f"{self.DOMAIN_SEARCH_BASE_URL}/sendfile",
            file_path,
            {"domain_column": domain_column, "has_header_row": has_header_row},
        )

    def send_domain_search_file_stream(
        self,
        file_stream: BinaryIO,
        file_name: str,
        domain_column: int,
        has_header_row: bool = False,
    ) -> ZBSendFileResponse:
        if domain_column is None:
            raise ZBClientException("Empty parameter: domain_column")
        return self._send_bulk_root_multipart_stream(
            f"{self.DOMAIN_SEARCH_BASE_URL}/sendfile",
            file_stream,
            file_name,
            {"domain_column": domain_column, "has_header_row": has_header_row},
        )

    def domain_search_file_status(self, file_id: str) -> ZBFileStatusResponse:
        return self._bulk_root_file_status(self.DOMAIN_SEARCH_BASE_URL, file_id)

    def domain_search_get_file(self, file_id: str, download_path: str) -> ZBGetFileResponse:
        return self._bulk_root_get_file(self.DOMAIN_SEARCH_BASE_URL, file_id, download_path)

    def domain_search_delete_file(self, file_id: str) -> ZBDeleteFileResponse:
        return self._bulk_root_delete_file(self.DOMAIN_SEARCH_BASE_URL, file_id)

    # Priority 3 — list evaluator

    def send_list_evaluator_file(
        self, file_path: str, email_address_column: int
    ) -> ZBListEvaluatorResponse:
        if email_address_column is None:
            raise ZBClientException("Empty parameter: email_address_column")
        data = {
            "api_key": self._api_key,
            "email_address_column": email_address_column,
        }
        with open(file_path, "rb") as file:
            files = {"file": (os.path.basename(file_path), file, "text/csv")}
            return self._post(
                f"{self.LIST_EVALUATOR_BASE_URL}/",
                ZBListEvaluatorResponse,
                data=data,
                files=files,
            )

    def send_list_evaluator_file_stream(
        self,
        file_stream: BinaryIO,
        file_name: str,
        email_address_column: int,
    ) -> ZBListEvaluatorResponse:
        if email_address_column is None:
            raise ZBClientException("Empty parameter: email_address_column")
        data = {
            "api_key": self._api_key,
            "email_address_column": email_address_column,
        }
        files = {"file": (file_name, file_stream, "text/csv")}
        return self._post(
            f"{self.LIST_EVALUATOR_BASE_URL}/",
            ZBListEvaluatorResponse,
            data=data,
            files=files,
        )

    def get_list_evaluator_result(self, file_id: str) -> ZBListEvaluatorResponse:
        """The evaluation's progress and, once ``status`` is ``finished``, its percentages."""
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return ZBListEvaluatorResponse(
            self._request_json(
                "GET",
                f"{self.LIST_EVALUATOR_BASE_URL}/{quote(file_id, safe='')}/",
                params={"api_key": self._api_key},
            )
        )

    def send_evaluated_file(self, file_path: str) -> ZBSendFileResponse:
        data = {"api_key": self._api_key}
        with open(file_path, "rb") as file:
            files = {"file": (os.path.basename(file_path), file, "text/csv")}
            return self._post(
                f"{self.BULK_BASE_URL}/send-evaluated-file/",
                ZBSendFileResponse,
                data=data,
                files=files,
            )

    # Priority 3 — custom filters (main API)

    FILTER_RULES = ("allow", "block")
    FILTER_TARGETS = ("email", "domain", "mx", "tld")

    def _check_filter(self, rule: str, target: str, value: str) -> None:
        if not rule or not target or not value:
            raise ZBClientException("Empty parameter: rule, target, and value are required")
        if rule not in self.FILTER_RULES:
            raise ZBClientException("Invalid parameter: rule (must be allow or block)")
        if target not in self.FILTER_TARGETS:
            raise ZBClientException("Invalid parameter: target (must be email, domain, mx or tld)")

    def add_filter(self, rule: str, target: str, value: str):
        """Add or update an allowlist / blocklist rule (POST /filters/add)."""
        self._check_filter(rule, target, value)
        return self._request_json(
            "POST",
            f"{self._base_url}/filters/add",
            data={
                "api_key": self._api_key,
                "rule": rule,
                "target": target,
                "value": value,
            },
        )

    def list_filters(self, use_post: bool = False):
        if use_post:
            return self._request_json(
                "POST",
                f"{self._base_url}/filters/list",
                data={"api_key": self._api_key},
            )
        return self._request_json(
            "GET",
            f"{self._base_url}/filters/list",
            params={"api_key": self._api_key},
        )

    def delete_filter(self, rule: str, target: str, value: str):
        """Delete an allowlist / blocklist rule (POST /filters/delete)."""
        self._check_filter(rule, target, value)
        return self._request_json(
            "POST",
            f"{self._base_url}/filters/delete",
            data={
                "api_key": self._api_key,
                "rule": rule,
                "target": target,
                "value": value,
            },
        )

    # Priority 3 — S3 bulk helpers (bulkapi root)

    def list_s3files(
        self,
        bucket: str = None,
        search: str = None,
    ):
        """List S3 bucket files available for validation or scoring (GET /listS3files)."""
        params = {}
        if bucket is not None:
            params["bucket"] = bucket
        if search is not None:
            params["search"] = search
        payload = self._request_json(
            "GET",
            f"{self.BULK_ROOT_URL}/listS3files",
            params=params,
        )
        if isinstance(payload, dict) and payload.get("error"):
            raise ZBApiException(payload["error"])
        # Documented as {"success": true, "files": [{"Name", "Size", "LastModified"}]}.
        if isinstance(payload, dict) and isinstance(payload.get("files"), list):
            return payload["files"]
        if not isinstance(payload, list):
            raise ZBApiException("Unexpected listS3files response")
        return payload

    def validate_s3file(
        self,
        file_name: str,
        has_header_row: bool,
        remove_duplicates: Optional[bool] = None,
        return_url: Optional[str] = None,
    ) -> ZBSendFileResponse:
        """Validate a file in your Amazon S3 bucket (POST /validateS3file).

        ``file_name`` is the full path as returned by ``list_s3files``.
        """
        return self._bulk_root_file_job(
            "/validateS3file", file_name, has_header_row, remove_duplicates, return_url
        )

    def score_s3file(
        self,
        file_name: str,
        has_header_row: bool,
        remove_duplicates: Optional[bool] = None,
        return_url: Optional[str] = None,
    ) -> ZBSendFileResponse:
        """Score a file in your Amazon S3 bucket (POST /scoreS3file)."""
        return self._bulk_root_file_job(
            "/scoreS3file", file_name, has_header_row, remove_duplicates, return_url
        )

    def export_s3file(self, file_id: str, export_bucket: Optional[str] = None) -> ZBSendFileResponse:
        """Export a validated or scored file back to Amazon S3 (POST /exportS3file).

        Without ``export_bucket`` the export bucket from your ZeroBounce settings is used.
        """
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        if export_bucket is not None and not export_bucket.strip():
            raise ZBClientException("Empty parameter: export_bucket")
        fields = {"file_id": file_id}
        if export_bucket is not None:
            fields["export_bucket"] = export_bucket
        return self._post_bulk_root_form("/exportS3file", fields)

    def _bulk_root_file_job(
        self,
        path: str,
        file_name: Optional[str],
        has_header_row: bool,
        remove_duplicates: Optional[bool],
        return_url: Optional[str],
        *,
        file_name_required: bool = True,
    ) -> ZBSendFileResponse:
        """POST one of the documented S3 / SFTP file jobs on the bulkapi root."""
        if (file_name is None and file_name_required) or (file_name is not None and not file_name.strip()):
            raise ZBClientException("Empty parameter: file_name")
        if has_header_row is None:
            raise ZBClientException("Empty parameter: has_header_row")
        fields = {"has_header_row": has_header_row}
        if file_name is not None:
            fields["file_name"] = file_name
        if remove_duplicates is not None:
            fields["remove_duplicates"] = remove_duplicates
        if return_url is not None:
            fields["return_url"] = return_url
        return self._post_bulk_root_form(path, fields)

    def email_finder_s3file(
        self,
        file_name: str,
        has_header_row: bool,
        remove_duplicates: Optional[bool] = None,
        return_url: Optional[str] = None,
    ) -> ZBSendFileResponse:
        """Run the email finder on a file in your Amazon S3 bucket (POST /emailFinderS3file).

        ``file_name`` is the full path as returned by ``list_s3files``.
        """
        return self._bulk_root_file_job(
            "/emailFinderS3file", file_name, has_header_row, remove_duplicates, return_url
        )

    def domain_search_s3file(
        self,
        file_name: str,
        has_header_row: bool,
        remove_duplicates: Optional[bool] = None,
        return_url: Optional[str] = None,
    ) -> ZBSendFileResponse:
        """Run domain search on a file in your Amazon S3 bucket (POST /domainSearchS3file)."""
        return self._bulk_root_file_job(
            "/domainSearchS3file", file_name, has_header_row, remove_duplicates, return_url
        )

    # SFTP / FTP bulk (bulkapi root). The server, path and protocol come from your ZeroBounce settings.

    def validate_sftpfile(
        self,
        file_name: Optional[str],
        has_header_row: bool,
        remove_duplicates: Optional[bool] = None,
        return_url: Optional[str] = None,
    ) -> ZBSendFileResponse:
        """Validate a file from your SFTP/FTP server (POST /validateSFTPfile).

        The docs list ``file_name`` as optional for this endpoint; pass ``None`` to leave it out.
        """
        return self._bulk_root_file_job(
            "/validateSFTPfile",
            file_name,
            has_header_row,
            remove_duplicates,
            return_url,
            file_name_required=False,
        )

    def score_sftpfile(
        self,
        file_name: str,
        has_header_row: bool,
        remove_duplicates: Optional[bool] = None,
        return_url: Optional[str] = None,
    ) -> ZBSendFileResponse:
        """Score a file from your SFTP/FTP server (POST /scoreSFTPfile). ``file_name`` is e.g. ``my_file.txt``."""
        return self._bulk_root_file_job(
            "/scoreSFTPfile", file_name, has_header_row, remove_duplicates, return_url
        )

    def email_finder_sftpfile(
        self,
        file_name: str,
        has_header_row: bool,
        remove_duplicates: Optional[bool] = None,
        return_url: Optional[str] = None,
    ) -> ZBSendFileResponse:
        """Run the email finder on a file from your SFTP/FTP server (POST /emailFinderSFTPfile)."""
        return self._bulk_root_file_job(
            "/emailFinderSFTPfile", file_name, has_header_row, remove_duplicates, return_url
        )

    def domain_search_sftpfile(
        self,
        file_name: str,
        has_header_row: bool,
        remove_duplicates: Optional[bool] = None,
        return_url: Optional[str] = None,
    ) -> ZBSendFileResponse:
        """Run domain search on a file from your SFTP/FTP server (POST /domainSearchSFTPfile)."""
        return self._bulk_root_file_job(
            "/domainSearchSFTPfile", file_name, has_header_row, remove_duplicates, return_url
        )

    def export_sftpfile(self, file_id: str, export_path: Optional[str] = None) -> ZBSendFileResponse:
        """Export a validated or scored file back to your SFTP/FTP server (POST /exportSFTPfile).

        Without ``export_path`` the export path from your ZeroBounce settings is used.
        """
        if not file_id or not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        if export_path is not None and not export_path.strip():
            raise ZBClientException("Empty parameter: export_path")
        fields = {"file_id": file_id}
        if export_path is not None:
            fields["export_path"] = export_path
        return self._post_bulk_root_form("/exportSFTPfile", fields)

    # Inbox Placement Tester (bulkapi /api/ipt). Uses the account's inbox-test credits.

    @staticmethod
    def _ipt_test_path(test_id: Union[int, str]) -> str:
        if test_id is None or not str(test_id).strip():
            raise ZBClientException("Empty parameter: test_id")
        return quote(str(test_id).strip(), safe="")

    def get_inbox_placement_providers(self):
        """Seed providers available for new tests (GET /api/ipt/providers).

        Returns
        -------
        dict with ``emailProviders`` and ``gatewayProviders``; each has ``items`` of
        ``{id, name, location, seedCount, seedIds}``.
        """
        return self._request_json("GET", f"{self.INBOX_PLACEMENT_BASE_URL}/providers")

    def get_inbox_placement_test_types(self):
        """Supported test types and the default one (GET /api/ipt/test-types)."""
        return self._request_json("GET", f"{self.INBOX_PLACEMENT_BASE_URL}/test-types")

    def create_inbox_placement_test(
        self,
        name: str,
        test_type: Optional[int] = None,
        sender_email: Optional[str] = None,
        provider_ids: Optional[List[int]] = None,
        seed_ids: Optional[List[int]] = None,
        providers: Optional[List[dict]] = None,
        webhook_url: Optional[str] = None,
    ):
        """Create an inbox placement test (POST /api/ipt/test). Spends one inbox test.

        Parameters
        ----------
        name: str
            Unique test name, at most 64 characters.
        test_type: int or None
            1 (Email, needs ``sender_email``), 2 (Unique ID) or 3 (Auto Alias, the API's default).
        sender_email: str or None
            The From address to match; required when ``test_type`` is 1.
        provider_ids: list of int or None
            Use every active seed of these providers.
        seed_ids: list of int or None
            Use these seed mailboxes.
        providers: list of dict or None
            ``{"id": provider_id, "maxSeeds": n}`` to cap the seeds per provider (``n`` >= 1).
        webhook_url: str or None
            Where the finished result is posted; also saved as this API key's webhook.

        Without ``provider_ids``, ``seed_ids`` or ``providers`` the test uses every active seed.

        Returns
        -------
        dict with ``id``, ``identifier``, ``testType`` and ``emailAddressList`` (the seeds to send to).
        """
        if not name or not name.strip():
            raise ZBClientException("Empty parameter: name")
        if len(name) > 64:
            raise ZBClientException("Invalid parameter: name (at most 64 characters)")
        if any(not (char.isalnum() or char in self.IPT_NAME_PUNCTUATION) for char in name):
            raise ZBClientException(
                "Invalid parameter: name (letters, numbers, spaces and - / \\ , . & ' ( ) only)"
            )
        if test_type is not None and test_type not in self.IPT_TEST_TYPES:
            raise ZBClientException("Invalid parameter: test_type (must be 1, 2 or 3)")
        if test_type == 1 and (not sender_email or not sender_email.strip()):
            raise ZBClientException("Empty parameter: sender_email (required when test_type is 1)")
        for provider in providers or []:
            if not isinstance(provider, dict) or "id" not in provider:
                raise ZBClientException("Invalid parameter: providers (each needs an id)")
            max_seeds = provider.get("maxSeeds")
            if max_seeds is not None and max_seeds < 1:
                raise ZBClientException("Invalid parameter: providers (maxSeeds must be at least 1)")

        body = {"name": name}
        if test_type is not None:
            body["testType"] = test_type
        if sender_email is not None:
            body["senderEmail"] = sender_email
        if provider_ids is not None:
            body["providerIds"] = list(provider_ids)
        if seed_ids is not None:
            body["seedIds"] = list(seed_ids)
        if providers is not None:
            body["providers"] = list(providers)
        if webhook_url is not None:
            body["webhookUrl"] = webhook_url
        return self._request_json("POST", f"{self.INBOX_PLACEMENT_BASE_URL}/test", json=body)

    def get_inbox_placement_test(self, test_id: Union[int, str]):
        """A test and its placement results (GET /api/ipt/test/{id}).

        Returns
        -------
        dict with ``status`` (running or finished), inbox/spam/other/not delivered/pending
        counts, ``percentages``, ``results`` and ``seeds``.
        """
        path = self._ipt_test_path(test_id)
        return self._request_json("GET", f"{self.INBOX_PLACEMENT_BASE_URL}/test/{path}")

    def list_inbox_placement_tests(
        self,
        status: Optional[str] = None,
        created_after: Optional[Union[date, str]] = None,
        created_before: Optional[Union[date, str]] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ):
        """List tests, newest first (GET /api/ipt/tests).

        Parameters
        ----------
        status: str or None
            ``running`` or ``finished``.
        created_after, created_before: date, datetime, ISO string or None
            Only tests created in this range.
        page: int or None
            Page number, from 1.
        page_size: int or None
            Tests per page, 1 to 100 (the API's default is 25).
        """
        if status is not None and status not in self.IPT_TEST_STATUSES:
            raise ZBClientException("Invalid parameter: status (must be running or finished)")
        if page is not None and page < 1:
            raise ZBClientException("Invalid parameter: page (must be at least 1)")
        if page_size is not None and (page_size < 1 or page_size > 100):
            raise ZBClientException("Invalid parameter: page_size (must be between 1 and 100)")

        params = {}
        if status is not None:
            params["status"] = status
        for key, value in (("createdAfter", created_after), ("createdBefore", created_before)):
            if value is not None:
                params[key] = value.isoformat() if isinstance(value, date) else value
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["page_size"] = page_size
        return self._request_json("GET", f"{self.INBOX_PLACEMENT_BASE_URL}/tests", params=params)

    def delete_inbox_placement_test(self, test_id: Union[int, str]):
        """Delete a finished test (DELETE /api/ipt/test/{id}). A running test cannot be deleted."""
        path = self._ipt_test_path(test_id)
        return self._request_json("DELETE", f"{self.INBOX_PLACEMENT_BASE_URL}/test/{path}")

    def get_inbox_placement_webhook(self):
        """The webhook URL saved on this API key (GET /api/ipt/webhook); empty when none is set."""
        return self._request_json("GET", f"{self.INBOX_PLACEMENT_BASE_URL}/webhook")

    def set_inbox_placement_webhook(self, webhook_url: str):
        """Save the URL finished test results are posted to (PUT /api/ipt/webhook). One per API key."""
        if not webhook_url or not webhook_url.strip():
            raise ZBClientException("Empty parameter: webhook_url")
        return self._request_json(
            "PUT",
            f"{self.INBOX_PLACEMENT_BASE_URL}/webhook",
            json={"webhookUrl": webhook_url},
        )

    def guess_format(
        self,
        domain: str,
        first_name: str = None,
        middle_name: str = None,
        last_name: str = None,
    ):
        """Identifies and validates a person's primary email address.
        When no "name" fields are given, function makes a `domain search`.

        .. deprecated:: 
            This method is deprecated and will be removed in future versions.
            Use find_email_format or find_domain instead.

        Parameters
        ----------
        domain: str
            The email domain for which to find the email format.
        first_name: Optional[str]
            First name of the person whose email format is being searched
        middle_name: Optional[str]
            Middle name of the person whose email format is being searched
        last_name: Optional[str]
            Last name of the person whose email format is being searched

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBGuessFormatResponse
            Returns a ZBGuessFormatResponse object if the request was successful
        """
        warnings.warn(
            "guess_format is deprecated and will be removed in future versions. "
            "Use find_email_format or find_domain instead.",
            DeprecationWarning,
            stacklevel=2
        )
        params = {"domain": domain}
        if first_name:
            params["first_name"] = first_name
        if middle_name:
            params["middle_name"] = middle_name
        if last_name:
            params["last_name"] = last_name

        return self._get(
            f"{self._base_url}/guessformat",
            ZBGuessFormatResponse,
            params,
        )


    def find_email_format(
        self,
        first_name: str = '',
        domain: str = '',
        company_name: str = '',
        middle_name: str = '',
        last_name: str = '',
        use_post: bool = False,
    ):
        """Find a person's email address and the domain's format (GET or POST /guessformat).

        Pass exactly one of ``domain`` or ``company_name``. The name fields are optional.
        """
        if not domain and not company_name:
            raise ZBClientException("Empty parameter: domain or company_name required")
        if domain and company_name:
            raise ZBClientException("Parameter error: domain and company_name cannot be used together")
        params = {}
        if first_name:
            params["first_name"] = first_name
        if domain:
            params["domain"] = domain
        if company_name:
            params["company_name"] = company_name
        if middle_name:
            params["middle_name"] = middle_name
        if last_name:
            params["last_name"] = last_name

        return self._get_or_post_form(
            f"{self._base_url}/guessformat", ZBFindEmailFormatResponse, params, use_post
        )

    def find_domain(
        self,
        domain: str = '',
        company_name: str = '',
        use_post: bool = False,
    ):
        if not domain and not company_name:
            raise ZBClientException("Empty parameter: domain xor company_name required")
        if domain and company_name:
            raise ZBClientException("Parameter error: domain and company_name cannot be used together")
        params = {}
        if domain:
            params["domain"] = domain
        if company_name:
            params["company_name"] = company_name
        return self._get_or_post_form(
            f"{self._base_url}/guessformat", ZBFindDomainResponse, params, use_post
        )