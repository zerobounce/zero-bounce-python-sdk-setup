import json
import warnings
from datetime import date, timedelta
import os
from typing import BinaryIO, List, Optional, Union
from urllib.parse import quote_plus

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
    ZBFileStatusResponse,
    ZBGetFileResponse,
    ZBDeleteFileResponse,
    ZBGuessFormatResponse,
    ZBFindEmailFormatResponse,
    ZBFindDomainResponse,
)


class ZeroBounce:
    """The ZeroBounce main class. All the requests are implemented here."""

    BULK_BASE_URL = "https://bulkapi.zerobounce.net/v2"
    BULK_ROOT_URL = "https://bulkapi.zerobounce.net"
    EMAIL_FINDER_BASE_URL = "https://bulkapi.zerobounce.net/email-finder"
    DOMAIN_SEARCH_BASE_URL = "https://bulkapi.zerobounce.net/domain-search"
    SCORING_BASE_URL = "https://bulkapi.zerobounce.net/v2/scoring"
    DEFAULT_HTTP_TIMEOUT_S = 120.0

    @staticmethod
    def _require_https_url(url: str) -> str:
        if not url.lower().startswith("https://"):
            raise ZBClientException("base_url must be an https:// URL")
        return url.rstrip("/")

    def __init__(self, api_key: str, base_url: Optional[Union[ZBApiUrl, str]] = None, timeout: timedelta | None = None):
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
    def _format_get_file_error_message(body: str) -> str:
        try:
            o = json.loads(body)
        except ValueError:
            return body if body else "Invalid getfile response"
        if not isinstance(o, dict):
            return body
        for k in ("message", "error", "error_message"):
            v = o.get(k)
            if not v:
                continue
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, list) and v and isinstance(v[0], str):
                return v[0].strip()
        return body

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

    def _get(self, url, response_class, params=None):
        if not params:
            params = {}
        params["api_key"] = self._api_key
        try:
            response = requests.get(url, params=params, timeout=self._timeout_s)
        except RequestException as e:
            raise type(e)(self._redact(e)) from None

        try:
            json_response = response.json()
        except ValueError as e:
            raise ZBApiException from e

        error = json_response.pop("error", None)
        if error:
            raise ZBApiException(error)
        return response_class(json_response)

    def _post(self, url, response_class, data=None, json=None, files=None):
        response = requests.post(url, data=data, json=json, files=files, timeout=self._timeout_s)
        try:
            json_response = response.json()
        except ValueError as e:
            raise ZBApiException('Request not processed succesfully. Status code %s' % response.status_code)

        return response_class(json_response)

    def _post_form(self, url, response_class, data=None):
        if not data:
            data = {}
        data = dict(data)
        data["api_key"] = self._api_key
        try:
            response = requests.post(url, data=data, timeout=self._timeout_s)
        except RequestException as e:
            raise type(e)(self._redact(e)) from None

        try:
            json_response = response.json()
        except ValueError as e:
            raise ZBApiException from e

        error = json_response.pop("error", None)
        if error:
            raise ZBApiException(error)
        return response_class(json_response)

    def _request_json(self, method: str, url: str, *, params=None, data=None, files=None):
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
                data=data,
                files=files,
                timeout=self._timeout_s,
            )
        except RequestException as e:
            raise type(e)(self._redact(e)) from None
        try:
            return response.json()
        except ValueError as e:
            raise ZBApiException(
                f"Request not processed successfully. Status code {response.status_code}"
            ) from e

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
            )
        except RequestException as e:
            raise type(e)(self._redact(e)) from None
        body_bytes = response.content or b""
        body_str = body_bytes.decode("utf-8", errors="replace")
        content_type = response.headers.get("Content-Type") or ""
        if response.status_code > 299:
            if body_str.lstrip().startswith("{"):
                raise ZBApiException(self._redact(self._format_get_file_error_message(body_str)))
            raise ZBApiException(self._redact(body_str or f"HTTP {response.status_code}"))
        if self._should_treat_get_file_body_as_error(body_str, content_type):
            raise ZBApiException(self._redact(self._format_get_file_error_message(body_str)))
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

    def get_credits(self):
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

        return self._get(f"{self._base_url}/getcredits", ZBGetCreditsResponse)

    def get_api_usage(self, start_date: date, end_date: date):
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

        return self._get(
            f"{self._base_url}/getapiusage",
            ZBGetApiUsageResponse,
            params={
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            },
        )

    def get_activity(self, email: str):
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

        return self._get(
            f"{self._base_url}/activity", ZBGetActivityResponse, params={"email": email}
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
        return self._post(
            f"{self._base_url}/validatebatch",
            ZBValidateBatchResponse,
            json=payload)

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
            )
        except RequestException as e:
            raise type(e)(self._redact(e)) from None
        body_bytes = response.content or b""
        body_str = body_bytes.decode("utf-8", errors="replace")
        content_type = response.headers.get("Content-Type") or ""

        if response.status_code > 299:
            if body_str.lstrip().startswith("{"):
                raise ZBApiException(self._redact(self._format_get_file_error_message(body_str)))
            raise ZBApiException(self._redact(body_str or f"HTTP {response.status_code}"))

        if self._should_treat_get_file_body_as_error(body_str, content_type):
            raise ZBApiException(self._redact(self._format_get_file_error_message(body_str)))

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
        if not domain_column:
            raise ZBClientException("Empty parameter: domain_column")
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
        if not domain_column:
            raise ZBClientException("Empty parameter: domain_column")
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
        if not domain_column:
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
        if not domain_column:
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
    ) -> ZBSendFileResponse:
        if not email_address_column:
            raise ZBClientException("Empty parameter: email_address_column")
        data = {
            "api_key": self._api_key,
            "email_address_column": email_address_column,
        }
        with open(file_path, "rb") as file:
            files = {"file": (os.path.basename(file_path), file, "text/csv")}
            return self._post(
                f"{self.BULK_BASE_URL}/listevaluator/",
                ZBSendFileResponse,
                data=data,
                files=files,
            )

    def send_list_evaluator_file_stream(
        self,
        file_stream: BinaryIO,
        file_name: str,
        email_address_column: int,
    ) -> ZBSendFileResponse:
        if not email_address_column:
            raise ZBClientException("Empty parameter: email_address_column")
        data = {
            "api_key": self._api_key,
            "email_address_column": email_address_column,
        }
        files = {"file": (file_name, file_stream, "text/csv")}
        return self._post(
            f"{self.BULK_BASE_URL}/listevaluator/",
            ZBSendFileResponse,
            data=data,
            files=files,
        )

    def get_list_evaluator_result(self, file_id: str):
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._request_json(
            "GET",
            f"{self.BULK_BASE_URL}/listevaluator/{file_id}/",
            params={"api_key": self._api_key},
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

    def add_filter(self, rule: str, target: str, value: str):
        if not rule or not target or not value:
            raise ZBClientException("Empty parameter: rule, target, and value are required")
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
        if not rule or not target or not value:
            raise ZBClientException("Empty parameter: rule, target, and value are required")
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
        if not isinstance(payload, list):
            raise ZBApiException("Unexpected listS3files response")
        return payload

    def validate_s3file(
        self,
        file_name: str,
        has_header_row: bool = None,
        remove_duplicates: bool = None,
        remove_duplicate: bool = None,
        email_address_column: int = None,
        return_url: str = None,
        first_name_column: int = None,
        last_name_column: int = None,
        gender_column: int = None,
        ip_address_column: int = None,
        allow_phase_2: Optional[bool] = None,
    ) -> ZBSendFileResponse:
        if not file_name or not file_name.strip():
            raise ZBClientException("Empty parameter: file_name")
        fields = {"file_name": file_name}
        if has_header_row is not None:
            fields["has_header_row"] = has_header_row
        if remove_duplicates is not None:
            fields["remove_duplicates"] = remove_duplicates
        if remove_duplicate is not None:
            fields["remove_duplicate"] = remove_duplicate
        if email_address_column is not None:
            fields["email_address_column"] = email_address_column
        if return_url is not None:
            fields["return_url"] = return_url
        if first_name_column is not None:
            fields["first_name_column"] = first_name_column
        if last_name_column is not None:
            fields["last_name_column"] = last_name_column
        if gender_column is not None:
            fields["gender_column"] = gender_column
        if ip_address_column is not None:
            fields["ip_address_column"] = ip_address_column
        if allow_phase_2 is not None:
            fields["allow_phase_2"] = "true" if allow_phase_2 else "false"
        return self._post_bulk_root_form("/validateS3file", fields)

    def score_s3file(
        self,
        file_name: str,
        has_header_row: bool = None,
        remove_duplicates: bool = None,
        remove_duplicate: bool = None,
        email_address_column: int = None,
    ) -> ZBSendFileResponse:
        if not file_name or not file_name.strip():
            raise ZBClientException("Empty parameter: file_name")
        fields = {"file_name": file_name}
        if has_header_row is not None:
            fields["has_header_row"] = has_header_row
        if remove_duplicates is not None:
            fields["remove_duplicates"] = remove_duplicates
        if remove_duplicate is not None:
            fields["remove_duplicate"] = remove_duplicate
        if email_address_column is not None:
            fields["email_address_column"] = email_address_column
        return self._post_bulk_root_form("/scoreS3file", fields)

    def export_s3file(self, file_id: str, export_bucket: str) -> ZBSendFileResponse:
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        if not export_bucket or not export_bucket.strip():
            raise ZBClientException("Empty parameter: export_bucket")
        return self._post_bulk_root_form(
            "/exportS3file",
            {"file_id": file_id, "export_bucket": export_bucket},
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
        first_name: str, 
        domain: str = '', 
        company_name: str = '',
        middle_name: str = '', 
        last_name: str = ''
    ):
        if not domain and not company_name:
            raise ZBClientException("Empty parameter: domain or company_name required")
        if domain and company_name:
            raise ZBClientException("Parameter error: domain and company_name cannot be used together")
        params = {"first_name": first_name}
        if domain:
            params["domain"] = domain
        if company_name:
            params["company_name"] = company_name
        if middle_name:
            params["middle_name"] = middle_name
        if last_name:
            params["last_name"] = last_name

        return self._get(
            f"{self._base_url}/guessformat",
            ZBFindEmailFormatResponse,
            params)

    def find_domain(
        self,
        domain: str = '',
        company_name: str = ''
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
        return self._get(
            f"{self._base_url}/guessformat",
            ZBFindDomainResponse,
            params)