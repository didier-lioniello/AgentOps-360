# Security Policy

AgentOps-360 is a reference implementation, not a production-ready service. Security fixes are
maintained on the default branch; no long-term support window is currently offered for older
snapshots.

## Reporting a vulnerability

Please report suspected vulnerabilities through a
[private GitHub security advisory](https://github.com/didier-lioniello/AgentOps-360/security/advisories/new).
Do not include credentials, personal data, exploit payloads, or unredacted logs in a public issue.

You can expect an initial acknowledgement within seven days. A fix timeline depends on severity,
reproducibility, and maintainer availability.

## Security boundaries

- `AUTH_MODE=development` is only for the local Docker Compose demo. It uses an explicitly
  configured static token and must never be exposed on a network you do not trust.
- `AUTH_MODE=jwt` uses a shared HS256 secret as a compact reference. A real deployment should use
  an external identity provider, asymmetric verification through JWKS, key rotation, and explicit
  authorization policies.
- Tenant identity is accepted only from the authenticated token. Client-supplied tenant headers
  are ignored.
- The included database credentials, exposed ports, and observability stack are local-development
  defaults, not a hardened deployment configuration.
