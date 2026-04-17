# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | ✅ Currently supported |

## Reporting a Vulnerability

Found a security issue? Please report it responsibly.

**Do NOT** create a public GitHub issue for security vulnerabilities.

Instead:
1. Email: security@opsiton.ai (if available)
2. Or use GitHub's **Private vulnerability reporting** (Settings → Security → Advisories)
3. Provide details: affected component, reproduction steps, potential impact

## Security Best Practices for Deployments

- **Never** expose the API server to the public internet without authentication
- **Always** use environment variables for secrets — never hardcode
- **Enable** TLS/HTTPS in production
- **Rate limit** API endpoints to prevent abuse
- **Validate** all user input before processing
- **Strip** sensitive data from logs and memory exports

## Known Security Considerations

### Tool Schemas
Tool parameters accept arbitrary JSON Schema. Validate type constraints server-side before passing to LLM providers.

### Memory Export (JSON/YAML)
Memory exports may contain sensitive context. Sanitize before sharing. See `docs/SECURITY_AUDIT_DOCKER_CI.md`.

### MCP Server
MCP server runs with the same permissions as the parent process. Use least-privilege service accounts.
