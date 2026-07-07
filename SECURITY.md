# Security Policy

Backstop runs in-process and is designed to enforce LLM budgets and backpressure without requiring prompt payloads to pass through a third-party proxy.

## Reporting Vulnerabilities

Please report security issues privately before opening a public issue.

Until a dedicated security contact is published, use GitHub private vulnerability reporting if available for this repository. If it is not available, open a minimal public issue that says a private security report is needed, without including exploit details.

Include:

- Affected Backstop version or commit.
- A minimal reproduction.
- Impact and likely attack path.
- Whether credentials, prompt payloads, tenant identifiers, or budget state may be exposed or bypassed.

## Supported Versions

Backstop is early-stage. Security fixes should target the latest release and `main`.

## Security Design Defaults

- Prompt payloads are not sent to a Backstop-hosted service by the OSS SDK.
- Metrics should avoid high-cardinality or sensitive labels.
- Budget and policy enforcement should fail explicitly rather than silently allowing unexpected spend.
- Provider API keys stay with the application and official provider SDKs.

## Out Of Scope

The maintainers cannot guarantee security of:

- User applications that wrap Backstop incorrectly.
- Third-party dashboards, exporters, or metrics stores.
- Provider SDK bugs outside Backstop's transport integration.
- Secrets committed to application repositories or logs.
