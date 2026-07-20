# Security Policy

## Supported version

Security fixes are applied to the latest revision of the default branch. This is a portfolio release, so no older release line is promised support unless a tagged release says otherwise.

## Reporting a vulnerability

Please use the repository's **Security** tab to submit a private vulnerability report. If private reporting is unavailable, email [nilhan.dev@gmail.com](mailto:nilhan.dev@gmail.com) with the repository name and a minimal reproduction. Do not publish credentials, personal data, exploit details, or unredacted logs in a public issue.

Useful reports include the affected revision, impact, prerequisites, reproduction steps, and a suggested mitigation. Receipt will be acknowledged when practical; remediation timing depends on severity and whether the affected surface is a prototype or a deployed system.

## Safe operation

- Keep credentials in environment variables or an external secret manager; never commit them.
- Treat example configuration as placeholders.
- Review network, filesystem, browser, and subprocess permissions before enabling integrations.
- Use synthetic data for demonstrations and remove generated evidence before sharing it.
- This repository does not authorize testing against third-party systems without permission.
