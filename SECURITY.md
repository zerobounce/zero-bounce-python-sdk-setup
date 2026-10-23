# Security Policy

## Reporting a Vulnerability

If you think you've found a security issue, please report it privately instead of opening a public issue.

**Email:** integrations@zerobounce.net (use a subject like `[zero-bounce-python-sdk-setup] Security`).

We'll look into reports as we can. If the issue is in the Zero Bounce API or service rather than this SDK, we may forward it to the right team.

## Supported Versions

We focus on the current release line for fixes. Using the latest release is recommended.

## Tips for Using This SDK

* Don't commit API keys or `.env` files—use environment variables or a secrets manager. The Warmup API uses its own key; keep it separate from the validation API key.
* Keep the SDK and its dependencies up to date. Use Python 3.10 or newer: older versions cannot install the current `requests` and `urllib3` security releases.
* The client only sends requests to `https://` URLs and never follows redirects. Do not point a base URL at a host you don't control.
* The validation API puts the key in the query string of `GET` requests, and query strings can reach proxy and server logs. Don't log full request URLs; use `use_post=True` where a method offers it.
* Exceptions raised by the SDK mask the key, but avoid logging request objects or enabling HTTP debug logging (for example `http.client` debuglevel), which would print the key.

Thanks for helping keep things secure.
