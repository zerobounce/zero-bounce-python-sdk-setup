import contextlib
import itertools
import json
import re
import warnings
from datetime import date, timedelta
from secrets import token_hex
import os
from typing import BinaryIO, List, Optional, Union
from urllib.parse import quote, quote_plus, unquote, unquote_plus, urlsplit

import requests
from requests.exceptions import RequestException

from ._zb_response import ZBFieldTypeError
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


def _reject_constant(name: str):
    raise ValueError(f"{name} is not valid JSON")


def _strict_json(text: str):
    """``text`` parsed as RFC 8259 JSON, or ``ValueError``.

    ``json.loads`` (and ``requests``' ``Response.json``) accept ``NaN``, ``Infinity`` and ``-Infinity``, which are
    not JSON; a body holding them is not an API response either. A body nested deeper than the parser's recursion
    limit (``[[[[...``) is a ValueError too, not a RecursionError.
    """
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except RecursionError:
        pass
    # Raised outside the except block, so the RecursionError is not its __context__.
    raise ValueError("JSON nested too deeply")


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
            parsed = _strict_json(trimmed)
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
        # e.g. ["In-progress tests cannot be deleted."] from the Inbox Placement Tester
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], str) and parsed[0].strip():
            return _strip_error_prefix(parsed[0])
        if len(trimmed) > 500:
            return "ZeroBounce returned an error (HTTP %s)." % status_code
        return trimmed
    if len(trimmed) > 1000 or any(char in trimmed for char in "{}[]<>"):
        return "ZeroBounce returned a response that is not valid JSON."
    message = _strip_error_prefix(trimmed)
    if not message:
        return "Empty response from ZeroBounce (HTTP %s)" % status_code
    return message


def _check_api_key(api_key: str) -> None:
    """Reject a key with surrounding whitespace or control characters (e.g. read from a file with its newline).

    Such a key would fail as an HTTP header value, and the HTTP library's error would quote it unredacted.
    """
    if api_key != api_key.strip() or any(ord(char) < 32 or ord(char) == 127 for char in api_key):
        raise ZBClientException("Invalid parameter: api_key has surrounding whitespace or control characters")


def _path_segment(value, name: str) -> str:
    """A caller value as one URL path segment: percent-encoded, and never ``.`` or ``..``."""
    if value is None or not str(value).strip():
        raise ZBClientException(f"Empty parameter: {name}")
    text = str(value).strip()
    if text in (".", ".."):
        raise ZBClientException(f"Invalid parameter: {name}")
    return quote(text, safe="")


def _https_url(url: str) -> str:
    """Every request carries the API key: refuse to send it anywhere but https.

    Covers the per-API base URL attributes (BULK_BASE_URL and the like), which callers can reassign.
    """
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        raise ZBClientException("Refusing to send the API key to a URL that is not https://")
    return url


def _root(url) -> str:
    """A base URL without trailing slashes, so ``f"{root}/path"`` never has ``//``.

    The per-API ``*_BASE_URL`` attributes are documented as reassignable, so they are normalised where they are read.
    """
    return url.rstrip("/") if isinstance(url, str) else url


def _strict_bool(value, name: str) -> bool:
    """A boolean option, parsed strictly.

    ``True``/``False``, ``"true"``/``"false"`` (any case) and ``1``/``0`` are accepted; anything else raises, so
    ``"false"`` is never sent as true and a typo is not taken as a flag.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return value == 1
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1"):
            return True
        if text in ("false", "0"):
            return False
    raise ZBClientException(f"Invalid parameter: {name} must be true or false")


def _json_escaped(text: str, ensure_ascii: bool, escape_slash: bool) -> str:
    """``text`` as it appears inside a JSON string, ``/`` as is or as JSON's optional ``\\/``."""
    escaped = json.dumps(text, ensure_ascii=ensure_ascii)[1:-1]
    # Replacing in the JSON-escaped text is exact, since every backslash in it is already escaped.
    return escaped.replace("/", "\\/") if escape_slash else escaped


def _secret_forms(secret: str) -> list:
    """Every form a secret can take in a body or URL echoed back to us.

    Composed from the encoders up to depth 2: {raw, JSON-escaped, JSON-escaped with ``\\/``} (each JSON form
    with non-ASCII as is or as ``\\uXXXX``) x {as is, URL-encoded with ``+``, with ``%20``, with ``/`` kept},
    each JSON form escaped twice (a JSON error body quoting the JSON request body), and ``repr``. Longest first,
    so a form that contains another is masked whole.
    """
    if not secret:
        return []
    json_forms = [
        _json_escaped(secret, ensure_ascii, escape_slash)
        for ensure_ascii in (True, False)
        for escape_slash in (False, True)
    ]
    twice = [
        _json_escaped(_json_escaped(secret, ensure_ascii, escape_slash), ensure_ascii, escape_slash)
        for ensure_ascii in (True, False)
        for escape_slash in (False, True)
    ]
    forms = {repr(secret)[1:-1], *twice}
    for form in (secret, *json_forms):
        forms.update((form, quote_plus(form), quote(form, safe=""), quote(form)))
    return sorted((form for form in forms if form), key=len, reverse=True)


def _partial_file(directory: str):
    """A new, empty temporary file in ``directory`` for a download, as ``(fd, path)``.

    Created with the usual mode for a new file (0666 less the umask), unlike ``tempfile.mkstemp`` (0600), since
    it is renamed over the download path.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    while True:
        path = os.path.join(directory or ".", f".zb-download-{token_hex(8)}.part")
        try:
            return os.open(path, flags, 0o666), path
        except FileExistsError:
            continue


# The message an error carries instead of text that still holds a secret in an encoding no spelling covers.
CREDENTIAL_OMITTED_MESSAGE = (
    "ZeroBounce returned an error; the response body was omitted because it contained a credential."
)

_JSON_ESCAPE = re.compile(r'\\(?:u([0-9a-fA-F]{4})|(["\\/bfnrt]))')
_JSON_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _json_unescape(text: str) -> str:
    """``text`` with its JSON string escapes decoded (``\\/`` and ``\\uXXXX`` included); other text as is."""
    decoded = _JSON_ESCAPE.sub(
        lambda match: chr(int(match.group(1), 16)) if match.group(1) else _JSON_SIMPLE_ESCAPES[match.group(2)], text
    )
    try:
        # Surrogate pairs from \\uXXXX\\uXXXX into one character.
        return decoded.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        return decoded


_DECODERS = (unquote, unquote_plus, lambda text: text.replace("+", " "), _json_unescape)


# How many layers of encoding the decode check undoes: the SDK's own request encoding plus three echo layers.
_DECODE_LAYERS = 4


def _decoded_views(text: str, layers: int = _DECODE_LAYERS) -> set:
    """``text`` and every view of it after up to ``layers`` decodings (URL, ``+`` as space, JSON), in any order."""
    views = {text}
    frontier = {text}
    for _ in range(layers):
        frontier = {decode(view) for view in frontier for decode in _DECODERS} - views
        if not frontier:
            break
        views |= frontier
    return views


def _redact_secrets(text, secrets) -> str:
    """``text`` with every form of every secret masked.

    Then closed under encoding: if any decoded view of what is left (URL, ``+`` as space, JSON, up to four
    layers in any order: the SDK's own request encoding plus three echo layers) still holds a secret, the whole text is replaced by a fixed message.
    """
    text = str(text)
    secrets = [secret for secret in secrets if secret]
    for secret in secrets:
        for form in _secret_forms(secret):
            text = text.replace(form, "***")
    views = _decoded_views(text)
    if any(secret in view for secret in secrets for view in views):
        return CREDENTIAL_OMITTED_MESSAGE
    return text


class _RefusesPickling:
    """A client holds its API key; pickling it would write the key to wherever the pickle goes."""

    def __reduce_ex__(self, protocol):
        raise TypeError(f"{type(self).__name__} cannot be pickled or copied: it holds an API key")


def _wire_bool(value, name: str) -> str:
    """A strict boolean option as the string the API expects in a query or form."""
    return "true" if _strict_bool(value, name) else "false"


# What a body that does not parse as JSON reads as, so the error is raised outside the except block.
_NOT_JSON = object()

_JSON_TYPE_NAMES = {dict: "an object", list: "an array", str: "a string", bool: "a boolean", type(None): "null"}


def _json_type_name(value) -> str:
    return _JSON_TYPE_NAMES.get(type(value), "a number")


def _shape_message(payload, shape) -> str:
    """The message for strict JSON that is not the shape the call returns (e.g. ``[]`` or ``0`` for an object)."""
    shapes = shape if isinstance(shape, tuple) else (shape,)
    expected = " or ".join(_JSON_TYPE_NAMES[expected] for expected in shapes)
    return (
        f"ZeroBounce returned JSON of an unexpected shape: expected {expected}, got {_json_type_name(payload)}."
    )


# The keys a message-only body is made of.
_MESSAGE_KEYS = ("error", "message", "error_message", "Message", "Error", "detail")


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


def _s3_files(payload):
    """The file list of a listS3files answer: documented as ``{"success": true, "files": [...]}``, or a bare
    array. A 2xx with an ``error`` field has already raised; any other object is the wrong shape (TypeError)."""
    if isinstance(payload, dict):
        payload = payload.get("files")
    if not isinstance(payload, list):
        raise TypeError("listS3files: expected an array of files")
    return payload


class ZeroBounce(_RefusesPickling):
    """Client for the ZeroBounce API: validation, scoring, email finder and domain search, bulk and S3/SFTP
    files, the list evaluator, filters and the Inbox Placement Tester. The Warmup API has its own client,
    ``ZeroBounceWarmup``, with its own key."""

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
        _check_api_key(api_key)
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

        host = urlsplit(self._base_url).hostname or ""
        self._region = {"api-eu.zerobounce.net": "EU", "api-us.zerobounce.net": "US"}.get(host.lower())
        self._bulk_region_warned = False

        self._timeout_s: float = (
            self.DEFAULT_HTTP_TIMEOUT_S if timeout is None else timeout.total_seconds()
        )

    _BULK_HOST = "bulkapi.zerobounce.net"

    def _checked_url(self, url: str) -> str:
        """``url`` if it is https; warn once when a regional base_url meets the global bulk host."""
        _https_url(url)
        if not self._bulk_region_warned and self._region and urlsplit(url).hostname == self._BULK_HOST:
            self._bulk_region_warned = True
            warnings.warn(
                f"base_url is the {self._region} API, but this request goes to {self._BULK_HOST}: ZeroBounce "
                "documents no regional host for bulk files, scoring files, email finder and domain search "
                "files, the list evaluator, S3/SFTP or the Inbox Placement Tester. Set the matching *_BASE_URL "
                "attributes if ZeroBounce gave you regional ones.",
                UserWarning,
                stacklevel=4,
            )
        return url

    @staticmethod
    def get_file_json_indicates_error(body: str) -> bool:
        """Whether a getfile response body looks like a JSON error payload (including HTTP 200)."""
        t = body.lstrip()
        if not t or t[0] != "{":
            return False
        try:
            o = _strict_json(body)
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
        return _redact_secrets(text, (self._api_key,))

    def _read_json_payload(self, response, message_only_is_error: bool = False, shape=dict):
        """The JSON payload of a 2xx answer, which must be of type ``shape`` (``dict``, ``list`` or a tuple of
        them); anything else, like an error body or ``0`` / ``[]`` where an object is expected, raises
        ZBApiException with the HTTP status."""
        body = _response_text(response)
        status = getattr(response, "status_code", 0) or 0
        headers = getattr(response, "headers", None) or {}
        content_type = headers.get("Content-Type") or headers.get("content-type") or ""
        if 300 <= status < 400:
            raise ZBApiException(
                self._redact("ZeroBounce returned a redirect, which this client does not follow."), status_code=status
            )
        if status > 299 or _looks_like_html(body, content_type) or not body.strip():
            raise ZBApiException(self._redact(_message_from_body(body, status)), status_code=status)
        try:
            payload = _strict_json(body)
        except ValueError:
            payload = _NOT_JSON
        if payload is _NOT_JSON:
            # Raised outside the except block: the parser's error quotes the body, so it must not be the
            # __context__ (``from None`` only hides it from tracebacks).
            raise ZBApiException(self._redact(_message_from_body(body, status)), status_code=status)
        if isinstance(payload, dict):
            title = payload.get("title")
            if isinstance(title, str) and payload.get("cloudflare_error") is True:
                raise ZBApiException(self._redact(title), status_code=status)
            error = None
            for key in ("error", "Error"):
                if key in payload and payload[key]:
                    error = payload[key]
                    break
            if isinstance(error, str) and error.strip():
                raise ZBApiException(self._redact(_strip_error_prefix(error)), status_code=status)
            if error:
                raise ZBApiException(self._redact(str(error)), status_code=status)
            success = payload.get("success")
            failed = success is False or (
                isinstance(success, str) and success.lower() == "false"
            )
            if failed:
                message = payload.get("message") or payload.get("error_message") or "Request failed"
                if isinstance(message, list):
                    message = message[0] if message else "Request failed"
                text = str(message).strip() or "Request failed"
                raise ZBApiException(self._redact(_strip_error_prefix(text)), status_code=status)
            # A dead or invalid key on a 2xx: no "success" and a non-empty "error_message".
            error_message = payload.get("error_message")
            if "success" not in payload and isinstance(error_message, str) and error_message.strip():
                raise ZBApiException(self._redact(_strip_error_prefix(error_message)), status_code=status)
            # The email finder and domain search never answer with a bare message: a body made only of message
            # keys is how they report a rejected request (LIVE: a dead key gets {"Message": "Invalid API key..."}).
            # Not for validate, whose greylist answer {"Message": "..."} is a result.
            if message_only_is_error and payload and "success" not in payload and all(
                key in _MESSAGE_KEYS for key in payload
            ):
                for key in _MESSAGE_KEYS:
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        raise ZBApiException(self._redact(_strip_error_prefix(value)), status_code=status)
        if shape is not None and not isinstance(payload, shape):
            raise ZBApiException(_shape_message(payload, shape), status_code=status)
        return payload

    def _typed(self, response, response_class, shape=dict):
        """``response_class`` built from the JSON object (or ``shape``) of ``response``.

        A field of the wrong shape (e.g. ``"email_batch": 5``) is an API error with the HTTP status, not the
        TypeError or AttributeError the response class would raise.
        """
        payload = self._read_json_payload(response, getattr(response_class, "_MESSAGE_ONLY_IS_ERROR", False), shape)
        # Field types are part of the shape: a field of another JSON type (or a required one missing) is an API
        # error with the HTTP status, never a coerced or defaulted result. The text names the field only.
        check_shape = getattr(response_class, "check_shape", None)
        if check_shape is not None and isinstance(payload, dict):
            try:
                check_shape(payload)
            except ZBFieldTypeError as error:
                problem = str(error)
            else:
                problem = None
            if problem is not None:
                raise ZBApiException(
                    f"ZeroBounce returned JSON of an unexpected shape for this call: {problem}.",
                    status_code=getattr(response, "status_code", 0) or 0,
                )
        try:
            return response_class(payload)
        except (TypeError, AttributeError, ValueError, KeyError):
            pass
        # Raised outside the except block, so the response class's error is not its __context__.
        raise ZBApiException(
            "ZeroBounce returned JSON of an unexpected shape for this call.",
            status_code=getattr(response, "status_code", 0) or 0,
        )

    def _raise_if_download_error(self, response, body_str: str, content_type: str) -> None:
        status = response.status_code
        if 300 <= status < 400:
            raise ZBApiException(
                self._redact("ZeroBounce returned a redirect, which this client does not follow."), status_code=status
            )
        if not (body_str or "").strip():
            raise ZBApiException(self._redact(_message_from_body(body_str, status)), status_code=status)
        if (
            status > 299
            or _looks_like_html(body_str, content_type)
            or self._should_treat_get_file_body_as_error(body_str, content_type)
        ):
            raise ZBApiException(self._redact(_message_from_body(body_str, status)), status_code=status)

    def _get(self, url, response_class, params=None):
        self._checked_url(url)
        if not params:
            params = {}
        params["api_key"] = self._api_key
        try:
            response = requests.get(url, params=params, timeout=self._timeout_s, allow_redirects=False)
        except RequestException as e:
            error = type(e)(self._redact(e))
        else:
            error = None
        if error is not None:
            # Raised outside the except block: the original, unredacted error must not be its __context__.
            raise error
        return self._typed(response, response_class)

    def _post(self, url, response_class, data=None, json=None, files=None):
        self._checked_url(url)
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
            error = type(e)(self._redact(e))
        else:
            error = None
        if error is not None:
            # Raised outside the except block: the original, unredacted error must not be its __context__.
            raise error
        return self._typed(response, response_class)

    def _post_form(self, url, response_class, data=None):
        self._checked_url(url)
        if not data:
            data = {}
        data = dict(data)
        data["api_key"] = self._api_key
        try:
            response = requests.post(
                url, data=_form_data(data), timeout=self._timeout_s, allow_redirects=False
            )
        except RequestException as e:
            error = type(e)(self._redact(e))
        else:
            error = None
        if error is not None:
            # Raised outside the except block: the original, unredacted error must not be its __context__.
            raise error
        return self._typed(response, response_class)

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params=None,
        data=None,
        files=None,
        json=None,
        bearer: bool = False,
        empty_is_success: bool = False,
        shape=dict,
        response_class=None,
    ):
        """``bearer`` sends the key as ``Authorization: Bearer`` instead of an ``api_key`` parameter.

        ``empty_is_success`` returns None for a 2xx with an empty body (204 No Content) instead of raising.
        ``shape`` is the JSON type the call returns (see ``_read_json_payload``); ``response_class`` builds a
        typed result from it instead.
        """
        self._checked_url(url)
        if params is None:
            params = {}
        headers = None
        if bearer:
            headers = {"Authorization": f"Bearer {self._api_key}"}
        elif "api_key" not in params and (data is None or "api_key" not in data):
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
                headers=headers,
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except RequestException as e:
            error = type(e)(self._redact(e))
        else:
            error = None
        if error is not None:
            # Raised outside the except block: the original, unredacted error must not be its __context__.
            raise error
        # Empty means zero bytes: a blank body is not JSON, and not the documented empty success either.
        if empty_is_success and 200 <= response.status_code < 300 and _response_text(response) == "":
            return None
        if response_class is not None:
            return self._typed(response, response_class, shape)
        return self._read_json_payload(response, shape=shape)

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
        stream: bool = False,
    ) -> ZBGetFileResponse:
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        params = {"api_key": self._api_key, "file_id": file_id}
        return self._download(f"{base_url}/getfile", params, download_path, stream)

    # Streamed downloads look at this much of the body before deciding it is a file, not an error page.
    _DOWNLOAD_SNIFF_BYTES = 64 * 1024
    # An error body is short; reading more than this to show its message would defeat streaming.
    _DOWNLOAD_MAX_ERROR_BYTES = 2 * 1024 * 1024

    def _download(self, url: str, params: dict, download_path: str, stream: bool = False) -> ZBGetFileResponse:
        """GET a result file and save it at ``download_path``.

        Either way the file is written to a temporary file next to ``download_path`` and moved into place when
        complete, so a failed download or write leaves no partial file and keeps a file already at
        ``download_path``. ``stream=True`` writes it in chunks, so a large file never has to fit in memory.
        """
        try:
            response = requests.get(
                self._checked_url(url),
                params=params,
                timeout=self._timeout_s,
                allow_redirects=False,
                **({"stream": True} if stream else {}),
            )
        except RequestException as e:
            error = type(e)(self._redact(e))
        else:
            error = None
        if error is not None:
            # Raised outside the except block: the original, unredacted error must not be its __context__.
            raise error

        dirname = os.path.dirname(download_path)
        if not stream:
            body_bytes = response.content or b""
            body_str = body_bytes.decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type") or ""
            self._raise_if_download_error(response, body_str, content_type)
            self._save_atomically(download_path, dirname, [body_bytes])
            return ZBGetFileResponse({"local_file_path": download_path})

        try:
            self._save_streamed(response, download_path, dirname)
        finally:
            response.close()
        return ZBGetFileResponse({"local_file_path": download_path})

    @staticmethod
    def _save_atomically(download_path: str, dirname: str, chunks) -> None:
        """Write ``chunks`` to a temporary file next to ``download_path``, then move it into place.

        A failed write (a full disk, a file size limit) removes the temporary file and leaves whatever was
        at ``download_path`` untouched: no partial file, and an earlier download is neither truncated nor deleted.
        """
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        fd, partial = _partial_file(dirname)
        try:
            with os.fdopen(fd, "wb") as out:
                for chunk in chunks:
                    if chunk:
                        out.write(chunk)
            os.replace(partial, download_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(partial)
            raise

    def _save_streamed(self, response, download_path: str, dirname: str) -> None:
        content_type = response.headers.get("Content-Type") or ""
        try:
            chunks = response.iter_content(chunk_size=64 * 1024)
            head = b""
            for chunk in chunks:
                head += chunk
                if len(head) >= self._DOWNLOAD_SNIFF_BYTES:
                    break
            head_str = head.decode("utf-8", errors="replace")
            might_be_error = (
                not 200 <= response.status_code < 300
                or not head.strip()
                or "application/json" in content_type.lower()
                or _looks_like_html(head_str, content_type)
                or head.lstrip()[:1] in (b"{", b"[")
            )
            if might_be_error:
                for chunk in chunks:
                    head += chunk
                    if len(head) >= self._DOWNLOAD_MAX_ERROR_BYTES:
                        break
                self._raise_if_download_error(response, head.decode("utf-8", errors="replace"), content_type)
                # A JSON object cut at the cap cannot be parsed to tell an error from a file; no result file starts
                # with "{", so it is an error with its status, as the same body under the cap would be.
                if len(head) >= self._DOWNLOAD_MAX_ERROR_BYTES and head.lstrip()[:1] == b"{":
                    raise ZBApiException(
                        "ZeroBounce returned a JSON body larger than the error limit instead of the file.",
                        status_code=response.status_code,
                    )

            self._save_atomically(download_path, dirname, itertools.chain([head], chunks))
        except RequestException as e:
            error = type(e)(self._redact(e))
        else:
            error = None
        if error is not None:
            # A connection lost mid-download: redacted, and raised outside the except block.
            raise error

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
            f"{_root(self.BULK_ROOT_URL)}{path}",
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
        if activity_data is not None:
            activity_data = _strict_bool(activity_data, "activity_data")
        if verify_plus is not None:
            verify_plus = _strict_bool(verify_plus, "verify_plus")
        if domain_info is not None:
            domain_info = _strict_bool(domain_info, "domain_info")
        if greylist_processing is not None:
            greylist_processing = _strict_bool(greylist_processing, "greylist_processing")
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
            # The live API rejects a JSON number here (it answers with the account-level "Invalid API Key
            # or your account ran out of credits" error) and accepts the value as a string.
            payload["timeout"] = str(timeout)
        if activity_data is not None:
            payload["activity_data"] = _strict_bool(activity_data, "activity_data")
        if verify_plus is not None:
            payload["verify_plus"] = _strict_bool(verify_plus, "verify_plus")
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
                # Reported on an HTTP 200, like a dead key on the other calls. The text comes from the body,
                # which can quote the key.
                raise ZBApiException(self._redact(text), status_code=200)
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
        url = f"{_root(self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL)}/sendfile"
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
        url = f"{_root(self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL)}/sendfile"
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
        remove_duplicate: Optional[bool] = None,
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
        remove_duplicate: bool or None
            If you want the system to remove duplicate emails. Sent only when set (the API defaults to True).
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
            data["has_header_row"] = _wire_bool(has_header_row, "has_header_row")
        if remove_duplicate is not None:
            data["remove_duplicate"] = _wire_bool(remove_duplicate, "remove_duplicate")
        if allow_phase_2 is not None:
            data["allow_phase_2"] = _wire_bool(allow_phase_2, "allow_phase_2")

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
        remove_duplicate: Optional[bool] = None,
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
        remove_duplicate: bool or None
            If you want the system to remove duplicate emails. Sent only when set (the API defaults to True).
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
            data["has_header_row"] = _wire_bool(has_header_row, "has_header_row")
        if remove_duplicate is not None:
            data["remove_duplicate"] = _wire_bool(remove_duplicate, "remove_duplicate")
        if allow_phase_2 is not None:
            data["allow_phase_2"] = _wire_bool(allow_phase_2, "allow_phase_2")

        return self._send_file_from_stream(
            False, file_stream, file_name, email_address_column, data
        )

    def scoring_send_file(
        self,
        file_path: str,
        email_address_column: int,
        return_url: str = None,
        has_header_row: bool = False,
        remove_duplicate: Optional[bool] = None,
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
        remove_duplicate: bool or None
            If you want the system to remove duplicate emails. Sent only when set (the API defaults to True).

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
            data["has_header_row"] = _wire_bool(has_header_row, "has_header_row")
        if remove_duplicate is not None:
            data["remove_duplicate"] = _wire_bool(remove_duplicate, "remove_duplicate")

        return self._send_file(True, file_path, email_address_column, data)

    def scoring_send_file_stream(
        self,
        file_stream: BinaryIO,
        file_name: str,
        email_address_column: int,
        return_url: str = None,
        has_header_row: bool = False,
        remove_duplicate: Optional[bool] = None,
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
        remove_duplicate: bool or None
            If you want the system to remove duplicate emails. Sent only when set (the API defaults to True).

        Returns
        -------
        response: ZBSendFileResponse
        """
        data = {}
        if return_url is not None:
            data["return_url"] = return_url
        if has_header_row is not None:
            data["has_header_row"] = _wire_bool(has_header_row, "has_header_row")
        if remove_duplicate is not None:
            data["remove_duplicate"] = _wire_bool(remove_duplicate, "remove_duplicate")

        return self._send_file_from_stream(
            True, file_stream, file_name, email_address_column, data
        )

    def _file_status(self, scoring: bool, file_id: str):
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._get(
            f"{_root(self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL)}/filestatus",
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
        stream: bool = False,
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
                params["activity_data"] = _wire_bool(options.activity_data, "activity_data")

        url = f"{_root(self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL)}/getfile"
        return self._download(url, params, download_path, stream)

    def get_file(
        self,
        file_id: str,
        download_path: str,
        options: Optional[ZBGetFileOptions] = None,
        stream: bool = False,
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

        stream: bool
            When True, the file is written in chunks as it downloads instead of being held in memory first.
            It appears at download_path only once complete.

        Raises
        ------
        ZBClientException
        ZBApiException

        Returns
        -------
        response: ZBGetFileResponse
            Returns a ZBGetFileResponse object if the request was successful
        """

        return self._get_file(False, file_id, download_path, options, stream=stream)

    def scoring_get_file(
        self,
        file_id: str,
        download_path: str,
        options: Optional[ZBGetFileOptions] = None,
        stream: bool = False,
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

        stream: bool
            When True, the file is written in chunks as it downloads instead of being held in memory first.
            It appears at download_path only once complete.

        Raises
        ------
        ZBClientException
        ZBApiException

        Returns
        -------
        response: ZBGetFileResponse
            Returns a ZBGetFileResponse object if the request was successful
        """

        return self._get_file(True, file_id, download_path, options, stream=stream)

    def _delete_file(self, scoring: bool, file_id: str):
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._get(
            f"{_root(self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL)}/deletefile",
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
        fields = {"domain_column": domain_column}
        if has_header_row is not None:
            fields["has_header_row"] = _wire_bool(has_header_row, "has_header_row")
        if first_name_column is not None:
            fields["first_name_column"] = first_name_column
        if last_name_column is not None:
            fields["last_name_column"] = last_name_column
        if middle_name_column is not None:
            fields["middle_name_column"] = middle_name_column
        if full_name_column is not None:
            fields["full_name_column"] = full_name_column
        return self._send_bulk_root_multipart(
            f"{_root(self.EMAIL_FINDER_BASE_URL)}/sendfile", file_path, fields
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
        fields = {"domain_column": domain_column}
        if has_header_row is not None:
            fields["has_header_row"] = _wire_bool(has_header_row, "has_header_row")
        if first_name_column is not None:
            fields["first_name_column"] = first_name_column
        if last_name_column is not None:
            fields["last_name_column"] = last_name_column
        if middle_name_column is not None:
            fields["middle_name_column"] = middle_name_column
        if full_name_column is not None:
            fields["full_name_column"] = full_name_column
        return self._send_bulk_root_multipart_stream(
            f"{_root(self.EMAIL_FINDER_BASE_URL)}/sendfile",
            file_stream,
            file_name,
            fields,
        )

    def email_finder_file_status(self, file_id: str) -> ZBFileStatusResponse:
        return self._bulk_root_file_status(_root(self.EMAIL_FINDER_BASE_URL), file_id)

    def email_finder_get_file(self, file_id: str, download_path: str, stream: bool = False) -> ZBGetFileResponse:
        """Save the results at ``download_path``; ``stream=True`` writes them in chunks instead of in memory."""
        return self._bulk_root_get_file(_root(self.EMAIL_FINDER_BASE_URL), file_id, download_path, stream)

    def email_finder_delete_file(self, file_id: str) -> ZBDeleteFileResponse:
        return self._bulk_root_delete_file(_root(self.EMAIL_FINDER_BASE_URL), file_id)

    # Priority 3 — bulk domain search (bulkapi …/domain-search/*)

    @staticmethod
    def _domain_search_fields(domain_column: int, has_header_row) -> dict:
        fields = {"domain_column": domain_column}
        if has_header_row is not None:
            fields["has_header_row"] = _wire_bool(has_header_row, "has_header_row")
        return fields

    def send_domain_search_file(
        self,
        file_path: str,
        domain_column: int,
        has_header_row: bool = False,
    ) -> ZBSendFileResponse:
        if domain_column is None:
            raise ZBClientException("Empty parameter: domain_column")
        return self._send_bulk_root_multipart(
            f"{_root(self.DOMAIN_SEARCH_BASE_URL)}/sendfile",
            file_path,
            self._domain_search_fields(domain_column, has_header_row),
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
            f"{_root(self.DOMAIN_SEARCH_BASE_URL)}/sendfile",
            file_stream,
            file_name,
            self._domain_search_fields(domain_column, has_header_row),
        )

    def domain_search_file_status(self, file_id: str) -> ZBFileStatusResponse:
        return self._bulk_root_file_status(_root(self.DOMAIN_SEARCH_BASE_URL), file_id)

    def domain_search_get_file(self, file_id: str, download_path: str, stream: bool = False) -> ZBGetFileResponse:
        """Save the results at ``download_path``; ``stream=True`` writes them in chunks instead of in memory."""
        return self._bulk_root_get_file(_root(self.DOMAIN_SEARCH_BASE_URL), file_id, download_path, stream)

    def domain_search_delete_file(self, file_id: str) -> ZBDeleteFileResponse:
        return self._bulk_root_delete_file(_root(self.DOMAIN_SEARCH_BASE_URL), file_id)

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
                f"{_root(self.LIST_EVALUATOR_BASE_URL)}/",
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
            f"{_root(self.LIST_EVALUATOR_BASE_URL)}/",
            ZBListEvaluatorResponse,
            data=data,
            files=files,
        )

    def get_list_evaluator_result(self, file_id: str) -> ZBListEvaluatorResponse:
        """The evaluation's progress and, once ``status`` is ``finished``, its percentages."""
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._request_json(
            "GET",
            f"{_root(self.LIST_EVALUATOR_BASE_URL)}/{_path_segment(file_id, 'file_id')}/",
            params={"api_key": self._api_key},
            response_class=ZBListEvaluatorResponse,
        )

    def send_evaluated_file(self, file_id: str) -> ZBSendFileResponse:
        """Submit a list the list evaluator has finished for bulk validation (POST /send-evaluated-file/).

        ``file_id`` is the list evaluator's ``file_id``. The live API takes that ID, not a new upload
        (the docs describe a file upload, which the API rejects with "file_id: This field is required").
        The result's ``file_id`` is the new validation job, followed with ``file_status`` and ``get_file``.
        """
        if not file_id or not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._post_form(f"{_root(self.BULK_BASE_URL)}/send-evaluated-file/", ZBSendFileResponse, {"file_id": file_id})

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
        """The allowlist / blocklist rules, a JSON array (GET or POST /filters/list)."""
        if use_post:
            return self._request_json(
                "POST",
                f"{self._base_url}/filters/list",
                data={"api_key": self._api_key},
                shape=list,
            )
        return self._request_json(
            "GET",
            f"{self._base_url}/filters/list",
            params={"api_key": self._api_key},
            shape=list,
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
        return self._request_json(
            "GET",
            f"{_root(self.BULK_ROOT_URL)}/listS3files",
            params=params,
            shape=(dict, list),
            response_class=_s3_files,
        )

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
        """POST one of the documented S3 / SFTP file jobs on the bulkapi root.

        The live API rejects a job without ``return_url`` ("Provided return URL is not permitted: None") and a
        ``validateSFTPfile`` without ``file_name``, although the docs mark both optional; so both are required here.
        """
        if (file_name is None and file_name_required) or (file_name is not None and not file_name.strip()):
            raise ZBClientException("Empty parameter: file_name")
        if has_header_row is None:
            raise ZBClientException("Empty parameter: has_header_row")
        if not return_url or not str(return_url).strip():
            raise ZBClientException("Empty parameter: return_url (the API rejects these jobs without one)")
        fields = {"has_header_row": _wire_bool(has_header_row, "has_header_row")}
        if file_name is not None:
            fields["file_name"] = file_name
        if remove_duplicates is not None:
            fields["remove_duplicates"] = _wire_bool(remove_duplicates, "remove_duplicates")
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
        file_name: str,
        has_header_row: bool,
        remove_duplicates: Optional[bool] = None,
        return_url: Optional[str] = None,
    ) -> ZBSendFileResponse:
        """Validate a file from your SFTP/FTP server (POST /validateSFTPfile). ``file_name`` is e.g. ``my_file.txt``."""
        return self._bulk_root_file_job(
            "/validateSFTPfile", file_name, has_header_row, remove_duplicates, return_url
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

    # Inbox Placement Tester (bulkapi /api/ipt). Uses the account's inbox-test credits. The key goes in the
    # documented Authorization: Bearer header, so it stays out of URLs and access logs.

    @staticmethod
    def _ipt_test_path(test_id: Union[int, str]) -> str:
        return _path_segment(test_id, "test_id")

    def get_inbox_placement_providers(self):
        """Seed providers available for new tests (GET /api/ipt/providers).

        Returns
        -------
        dict with ``emailProviders`` and ``gatewayProviders``; each has ``items`` of
        ``{id, name, location, seedCount, seedIds}``.
        """
        return self._request_json("GET", f"{_root(self.INBOX_PLACEMENT_BASE_URL)}/providers", bearer=True)

    def get_inbox_placement_test_types(self):
        """Supported test types and the default one (GET /api/ipt/test-types)."""
        return self._request_json("GET", f"{_root(self.INBOX_PLACEMENT_BASE_URL)}/test-types", bearer=True)

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
        return self._request_json("POST", f"{_root(self.INBOX_PLACEMENT_BASE_URL)}/test", json=body, bearer=True)

    def get_inbox_placement_test(self, test_id: Union[int, str]):
        """A test and its placement results (GET /api/ipt/test/{id}).

        Returns
        -------
        dict with ``status`` (running or finished), inbox/spam/other/not delivered/pending
        counts, ``percentages``, ``results`` and ``seeds``.
        """
        path = self._ipt_test_path(test_id)
        return self._request_json("GET", f"{_root(self.INBOX_PLACEMENT_BASE_URL)}/test/{path}", bearer=True)

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
        return self._request_json("GET", f"{_root(self.INBOX_PLACEMENT_BASE_URL)}/tests", params=params, bearer=True)

    def delete_inbox_placement_test(self, test_id: Union[int, str]):
        """Delete a finished test (DELETE /api/ipt/test/{id}). A running test cannot be deleted.

        Returns the API's JSON answer, or None when it answers with an empty 2xx (204 No Content).
        """
        path = self._ipt_test_path(test_id)
        return self._request_json(
            "DELETE", f"{_root(self.INBOX_PLACEMENT_BASE_URL)}/test/{path}", bearer=True, empty_is_success=True
        )

    def get_inbox_placement_webhook(self):
        """The webhook URL saved on this API key (GET /api/ipt/webhook); empty when none is set."""
        return self._request_json("GET", f"{_root(self.INBOX_PLACEMENT_BASE_URL)}/webhook", bearer=True)

    def set_inbox_placement_webhook(self, webhook_url: str):
        """Save the URL finished test results are posted to (PUT /api/ipt/webhook). One per API key."""
        if not webhook_url or not webhook_url.strip():
            raise ZBClientException("Empty parameter: webhook_url")
        return self._request_json(
            "PUT",
            f"{_root(self.INBOX_PLACEMENT_BASE_URL)}/webhook",
            json={"webhookUrl": webhook_url},
            bearer=True,
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