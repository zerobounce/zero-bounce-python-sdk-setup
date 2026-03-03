# Security Policy

## Reporting a Vulnerability

If you think you've found a security issue, please report it privately instead of opening a public issue.

**Email:** integrations@zerobounce.net (use a subject like `[zero-bounce-python-sdk-setup] Security`).

We'll look into reports as we can. If the issue is in the Zero Bounce API or service rather than this SDK, we may forward it to the right team.

## Supported Versions

We focus on the current release line for fixes. Using the latest release is recommended.

## Tips for Using This SDK

* Don't commit API keys or `.env` files—use environment variables or a secrets manager.
* Keep dependencies up to date and upgrade when new versions are released.
* The client uses HTTPS by default; avoid overriding to non-HTTPS in production.

Thanks for helping keep things secure.
