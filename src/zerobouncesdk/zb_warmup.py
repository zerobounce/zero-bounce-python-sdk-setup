"""Client for the ZeroBounce Warmup API (https://www.zerobounce.net/docs/warmup-api).

The Warmup API is separate from the email validation API: it has its own host, its own team-scoped
key, and it authenticates with an ``API-Key`` header instead of an ``api_key`` parameter. Use
``ZeroBounceWarmup`` with a Warmup API key; ``ZeroBounce`` stays for the validation API key.
"""

import os
import re
from datetime import date, timedelta
from typing import Optional, Union
from urllib.parse import quote

import requests
from requests.exceptions import RequestException

from .zb_exceptions import ZBApiException, ZBClientException
from .zerobouncesdk import _check_api_key, _looks_like_html, _message_from_body, _path_segment, _response_text

DateLike = Union[date, str]

_SEARCH_FROM = re.compile(r"^[A-Za-z0-9.\-_@+]*$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ZeroBounceWarmup:
    """The ZeroBounce Warmup API. One instance per Warmup API key; the key is bound to one team."""

    DEFAULT_BASE_URL = "https://warmup-api.zerobounce.net"
    BASE_PATH = "/api/v1/warmup"
    DEFAULT_HTTP_TIMEOUT_S = 120.0

    ONBOARDING_MODELS = ("self_managed", "zb_managed")
    EMAIL_TYPES = ("transactional", "newsletter", "marketing")
    STANDARD_RULE_IDS = range(0, 5)  # 0 Default, 1 Slow Pace, 2 Repair, 3 Boost, 4 Protect
    STATUS_IDS = range(0, 9)  # 4 Paused, 5 Disabled
    # team_id is required by the schema but always replaced with the key's team.
    _ANY_TEAM_ID = 1

    def __init__(self, api_key: str, base_url: Optional[str] = None, timeout: Optional[timedelta] = None):
        """
        Parameters
        ----------
        api_key: str
            Your Warmup API key (sent in the ``API-Key`` header).
        base_url: str or None
            The base URL ZeroBounce gave you; defaults to https://warmup-api.zerobounce.net.
        timeout: timedelta or None
            Request timeout; 120 seconds by default.
        """
        if not api_key or not api_key.strip():
            raise ZBClientException("Empty parameter: api_key")
        _check_api_key(api_key)
        base = base_url or self.DEFAULT_BASE_URL
        if not isinstance(base, str) or not base.lower().startswith("https://"):
            raise ZBClientException("base_url must be an https:// URL")
        self._api_key = api_key
        self._root = base.rstrip("/") + self.BASE_PATH
        self._timeout_s = self.DEFAULT_HTTP_TIMEOUT_S if timeout is None else timeout.total_seconds()

    # -- transport ----------------------------------------------------------------------------

    def _redact(self, text, extra_secrets=()) -> str:
        text = str(text)
        for secret in (self._api_key, *extra_secrets):
            if secret:
                for form in (secret, quote(secret, safe=""), repr(secret)[1:-1]):
                    text = text.replace(form, "***")
        return text

    def _send(self, method: str, path: str, *, params=None, json=None, secrets=()):
        try:
            response = requests.request(
                method,
                f"{self._root}{path}",
                params=params,
                json=json,
                headers={"API-Key": self._api_key, "Accept": "application/json"},
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except RequestException as e:
            error = type(e)(self._redact(e, secrets))
        else:
            error = None
        if error is not None:
            # Raised outside the except block: the original, unredacted error must not be its __context__.
            raise error
        status = getattr(response, "status_code", 0) or 0
        if 300 <= status < 400:
            raise ZBApiException(
                "ZeroBounce returned a redirect, which this client does not follow.", status_code=status
            )
        if status > 299:
            raise ZBApiException(
                self._redact(_message_from_body(_response_text(response), status), secrets), status_code=status
            )
        return response

    def _json(self, method: str, path: str, *, params=None, json=None, secrets=()):
        """JSON payload of a 200, or None for the documented empty successes (204, empty 200)."""
        response = self._send(method, path, params=params, json=json, secrets=secrets)
        body = _response_text(response)
        if response.status_code == 204 or not body.strip():
            return None
        content_type = response.headers.get("Content-Type", "")
        if _looks_like_html(body, content_type):
            raise ZBApiException(self._redact(_message_from_body(body, response.status_code), secrets))
        try:
            return response.json()
        except ValueError:
            raise ZBApiException(self._redact(_message_from_body(body, response.status_code), secrets)) from None

    def _csv(self, path: str, params=None, download_path: Optional[str] = None) -> str:
        response = self._send("GET", path, params=params)
        body = _response_text(response)
        content_type = response.headers.get("Content-Type", "")
        if not body.strip() or _looks_like_html(body, content_type) or "application/json" in content_type.lower():
            raise ZBApiException(self._redact(_message_from_body(body, response.status_code)))
        if download_path:
            directory = os.path.dirname(download_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(download_path, "wb") as handle:
                handle.write(response.content)
        return body

    # -- argument checks ----------------------------------------------------------------------

    @staticmethod
    def _required(value, name: str) -> str:
        if value is None or not str(value).strip():
            raise ZBClientException(f"Empty parameter: {name}")
        return value

    @staticmethod
    def _in_range(value, allowed: range, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value not in allowed:
            raise ZBClientException(f"Invalid parameter: {name} (must be {allowed.start} to {allowed.stop - 1})")
        return value

    @staticmethod
    def _iso_date(value: DateLike, name: str) -> str:
        if isinstance(value, date):
            return value.isoformat()
        if not isinstance(value, str) or not _ISO_DATE.match(value):
            raise ZBClientException(f"Invalid parameter: {name} (expected YYYY-MM-DD)")
        return value

    @classmethod
    def _engagement_body(cls, c_from: str, reply_pct: int, important_pct: int, click_pct: int) -> dict:
        cls._required(c_from, "c_from")
        cls._in_range(reply_pct, range(5, 46), "reply_pct")
        cls._in_range(important_pct, range(5, 41), "important_pct")
        cls._in_range(click_pct, range(0, 71), "click_pct")
        if click_pct > important_pct * 1.75:
            raise ZBClientException("Invalid parameter: click_pct (at most important_pct x 1.75)")
        return {"c_from": c_from, "reply_pct": reply_pct, "important_pct": important_pct, "click_pct": click_pct}

    # -- sending accounts ---------------------------------------------------------------------

    def list_sending_accounts(self):
        """Every sending account of the key's team (GET /sending-accounts).

        Returns ``{"accounts": [...], "statistics": {...}}``, or an empty list when the team has none
        (what the live API sends).
        """
        return self._json("GET", "/sending-accounts")

    def get_sending_account(self, from_address: str):
        """One sending account (GET /sending-account)."""
        return self._json("GET", "/sending-account", params={"from_address": self._required(from_address, "from_address")})

    def add_sending_account(
        self,
        from_address: str,
        onboarding_model: str,
        engagement_rule_id: Optional[int] = None,
        ignore_conflict: Optional[bool] = None,
        email_content: Optional[dict] = None,
        managed_sending: Optional[dict] = None,
    ):
        """Add a from-address to warmup (POST /sending-accounts).

        Parameters
        ----------
        from_address: str
        onboarding_model: str
            ``self_managed`` (you run the mailbox; ``engagement_rule_id`` 0-4 is required) or
            ``zb_managed`` (ZeroBounce provisions it; ``engagement_rule_id`` is ignored).
        ignore_conflict: bool or None
            Self-managed only: do not fail with 409 when the address is already registered.
        email_content: dict or None
            ZB managed: ``company_name``, ``company_website``, ``company_description``,
            ``types_of_emails`` (transactional, newsletter, marketing) and ``example_email``.
        managed_sending: dict or None
            ZB managed, write-only: ``weekdays_only``, ``timezone``, ``timezone_offset`` (-11 to 14)
            and ``warmup_start_date`` (YYYY-MM-DD or a date).

        For ZB managed accounts a 200 means accepted; the mailbox is provisioned afterwards.
        """
        self._required(from_address, "from_address")
        if onboarding_model not in self.ONBOARDING_MODELS:
            raise ZBClientException("Invalid parameter: onboarding_model (must be self_managed or zb_managed)")
        body = {"from_address": from_address, "onboarding_model": onboarding_model}
        if onboarding_model == "self_managed":
            if engagement_rule_id is None:
                raise ZBClientException("Empty parameter: engagement_rule_id (required for self_managed)")
            body["engagement_rule_id"] = self._in_range(engagement_rule_id, self.STANDARD_RULE_IDS, "engagement_rule_id")
            if email_content is not None or managed_sending is not None:
                raise ZBClientException("Invalid parameter: email_content and managed_sending are for zb_managed")
        if ignore_conflict is not None:
            body["ignore_conflict"] = bool(ignore_conflict)
        if email_content is not None:
            content = dict(email_content)
            types = content.get("types_of_emails")
            if types is not None and (not isinstance(types, list) or any(t not in self.EMAIL_TYPES for t in types)):
                raise ZBClientException(
                    "Invalid parameter: types_of_emails (transactional, newsletter and/or marketing)"
                )
            body["email_content"] = content
        if managed_sending is not None:
            sending = dict(managed_sending)
            offset = sending.get("timezone_offset")
            if offset is not None and (isinstance(offset, bool) or not isinstance(offset, (int, float)) or not -11 <= offset <= 14):
                raise ZBClientException("Invalid parameter: timezone_offset (must be -11 to 14)")
            if sending.get("warmup_start_date") is not None:
                sending["warmup_start_date"] = self._iso_date(sending["warmup_start_date"], "warmup_start_date")
            body["managed_sending"] = sending
        return self._json("POST", "/sending-accounts", json=body)

    def update_sending_account(self, from_address: str, engagement_rule_id: int, status_id: int, auto_enable: bool):
        """Change an account's engagement rule, status and auto-enable flag (PUT /sending-accounts).

        ``status_id`` is 0 to 8 (4 Paused, 5 Disabled). ``auto_enable=True`` is accepted only for an
        account that is not active (Paused or Disabled).
        """
        self._required(from_address, "from_address")
        if not isinstance(auto_enable, bool):
            raise ZBClientException("Empty parameter: auto_enable (must be True or False)")
        body = {
            "team_id": self._ANY_TEAM_ID,
            "from_address": from_address,
            "engagement_rule_id": self._in_range(engagement_rule_id, self.STANDARD_RULE_IDS, "engagement_rule_id"),
            "status_id": self._in_range(status_id, self.STATUS_IDS, "status_id"),
            "auto_enable": auto_enable,
        }
        return self._json("PUT", "/sending-accounts", json=body)

    def delete_sending_account(self, from_address: str) -> None:
        """Remove a sending account (DELETE /sending-accounts). Destructive and cannot be undone."""
        self._json("DELETE", "/sending-accounts", params={"from_address": self._required(from_address, "from_address")})

    def change_from_address(self, old_from_address: str, new_from_address: str) -> None:
        """Move an account and its history to a new from-address (PUT /smtp-credentials).

        Despite the path, nothing about SMTP credentials is stored.
        """
        body = {
            "team_id": self._ANY_TEAM_ID,
            "old_from_address": self._required(old_from_address, "old_from_address"),
            "new_from_address": self._required(new_from_address, "new_from_address"),
        }
        self._json("PUT", "/smtp-credentials", json=body)

    def list_from_addresses(
        self, search_from: Optional[str] = None, offset: Optional[int] = None, limit: Optional[int] = None
    ):
        """Registered from-addresses (GET /from-addresses).

        ``search_from`` takes letters, digits and ``. - _ @ +`` only. ``offset`` and ``limit`` default to
        0 and 100 on the API.
        """
        params = {}
        if search_from is not None:
            if not _SEARCH_FROM.match(search_from):
                raise ZBClientException("Invalid parameter: search_from (letters, digits and . - _ @ + only)")
            params["search_from"] = search_from
        for name, value in (("offset", offset), ("limit", limit)):
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ZBClientException(f"Invalid parameter: {name} (must be a non-negative integer)")
                params[name] = str(value)
        return self._json("GET", "/from-addresses", params=params)

    # -- engagement rules ---------------------------------------------------------------------

    def get_engagement_rules(self):
        """The rule catalogue: -1 Custom, 0 Default, 1 Slow Pace, 2 Repair, 3 Boost, 4 Protect."""
        return self._json("GET", "/engagement-rules")

    def set_engagement_rule(self, c_from: str, rule_id: int) -> None:
        """Set a standard rule (0 to 4) on an address (PUT /engagement-rule)."""
        self._required(c_from, "c_from")
        body = {"rule_id": self._in_range(rule_id, self.STANDARD_RULE_IDS, "rule_id")}
        self._json("PUT", "/engagement-rule", params={"c_from": c_from}, json=body)

    def get_custom_engagement(self, c_from: str):
        """An address's custom rule, with ``can_update`` and ``remaining_seconds`` (GET /custom-engagement/{c_from})."""
        return self._json("GET", f"/custom-engagement/{_path_segment(c_from, 'c_from')}")

    def create_custom_engagement(self, c_from: str, reply_pct: int, important_pct: int, click_pct: int):
        """Create a custom rule (POST /custom-engagement). Starts a 7 day cooldown on updates.

        ``reply_pct`` 5-45, ``important_pct`` 5-40, ``click_pct`` 0-70 and at most ``important_pct`` x 1.75.
        """
        return self._json("POST", "/custom-engagement", json=self._engagement_body(c_from, reply_pct, important_pct, click_pct))

    def update_custom_engagement(self, c_from: str, reply_pct: int, important_pct: int, click_pct: int):
        """Update a custom rule (PUT /custom-engagement).

        During the 7 day cooldown this raises ``ZBApiException`` with ``status_code`` 429.
        """
        return self._json("PUT", "/custom-engagement", json=self._engagement_body(c_from, reply_pct, important_pct, click_pct))

    def delete_custom_engagement(self, c_from: str, engagement_rule_id: int):
        """Delete a custom rule and fall back to standard rule ``engagement_rule_id`` (1 to 4) (DELETE /custom-engagement)."""
        body = {
            "c_from": self._required(c_from, "c_from"),
            "engagement_rule_id": self._in_range(engagement_rule_id, range(1, 5), "engagement_rule_id"),
        }
        return self._json("DELETE", "/custom-engagement", json=body)

    # -- statistics, seeds and utilities ------------------------------------------------------

    def get_seeds(self):
        """The seed list (GET /seeds)."""
        return self._json("GET", "/seeds")

    def download_seeds(self, download_path: Optional[str] = None) -> str:
        """The seed list as CSV (columns ``seed,provider``) (GET /seeds/download); also saved when ``download_path`` is set."""
        return self._csv("/seeds/download", download_path=download_path)

    def get_seed_count(self):
        """Number of seeds (GET /seed-count)."""
        return self._json("GET", "/seed-count")

    def get_progress_today(self):
        """Today's warmup progress (GET /progress-today)."""
        return self._json("GET", "/progress-today")

    def get_sent_today(self):
        """Messages sent today (GET /sent-today)."""
        return self._json("GET", "/sent-today")

    def get_emails_per_day(self):
        """Current daily volume (GET /emails-per-day)."""
        return self._json("GET", "/emails-per-day")

    def get_statistics(self, from_address: str):
        """Statistics for an address (GET /statistics). An address with no history returns zeros."""
        return self._json("GET", "/statistics", params={"from_address": self._required(from_address, "from_address")})

    def get_statistics_per_day(self, from_address: str, start_date: DateLike, end_date: DateLike):
        """Daily statistics between two dates, inclusive (GET /statistics-per-day)."""
        self._required(from_address, "from_address")
        start = self._iso_date(start_date, "start_date")
        end = self._iso_date(end_date, "end_date")
        if start > end:
            raise ZBClientException("Invalid parameter: start_date is later than end_date")
        params = {"from_address": from_address, "start_date": start, "end_date": end}
        return self._json("GET", "/statistics-per-day", params=params)

    def get_statistics_detailed(self, c_from: str):
        """Detailed statistics for an address (GET /statistics-detailed)."""
        return self._json("GET", "/statistics-detailed", params={"c_from": self._required(c_from, "c_from")})

    def download_statistics(self, c_from: str, download_path: Optional[str] = None) -> str:
        """An address's statistics as CSV (GET /statistics/download); also saved when ``download_path`` is set."""
        return self._csv("/statistics/download", params={"c_from": self._required(c_from, "c_from")}, download_path=download_path)

    def get_from_address_statistics(self, from_address: str):
        """Statistics for one from-address (GET /from-address-statistics)."""
        return self._json(
            "GET", "/from-address-statistics", params={"from_address": self._required(from_address, "from_address")}
        )

    def check_domain_dmarc(self, from_address: str, dkim_selector: Optional[str] = None):
        """SPF, DKIM and DMARC status of a from-address's domain (GET /check-domain-dmarc).

        Pass an email address: the live API answers "Please provide a valid email address" for a bare
        domain, although the docs describe a domain. Returns ``SPF_status``, ``DKIM_status``,
        ``DMARC_status`` and the ``dkim_selector`` that was checked.
        """
        self._required(from_address, "from_address")
        if "@" not in from_address:
            raise ZBClientException("Invalid parameter: from_address (an email address, e.g. sender@example.com)")
        params = {"from_address": from_address}
        if dkim_selector is not None:
            params["dkim_selector"] = self._required(dkim_selector, "dkim_selector")
        return self._json("GET", "/check-domain-dmarc", params=params)

    def test_smtp_configuration(self, from_address: str, username: str, password: str, server: str, port: int):
        """Check that SMTP credentials connect and hand off a message (POST /test-smtp-configuration).

        Nothing is stored, and the test message goes to a ZeroBounce test recipient, not ``from_address``.
        The live API currently answers a failed SMTP login with HTTP 500, raised as ``ZBApiException``
        with ``status_code`` 500.
        """
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ZBClientException("Invalid parameter: port (must be 1 to 65535)")
        body = {
            "from_address": self._required(from_address, "from_address"),
            "username": self._required(username, "username"),
            "password": self._required(password, "password"),
            "server": self._required(server, "server"),
            "port": port,
        }
        return self._json("POST", "/test-smtp-configuration", json=body, secrets=(password, username))
