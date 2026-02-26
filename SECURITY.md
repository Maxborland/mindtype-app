# Security Policy

## Supported Versions

Security fixes are provided for the latest release on the default branch.

| Version | Supported |
| ------- | --------- |
| Latest (default branch) | :white_check_mark: |
| Older releases | :x: |

## Reporting a Vulnerability

**Please do NOT open public GitHub issues for security vulnerabilities.**

### How to Report

Use [GitHub Private Vulnerability Reporting](../../security/advisories/new) to submit a report directly through this repository.

Alternatively, email: **butmaxim95@gmail.com**

### What to Include

- A clear description of the vulnerability
- Steps to reproduce or proof of concept
- Affected files, versions, or commits
- Potential impact and severity assessment

### Response Timeline

| Action | Timeframe |
| ------ | --------- |
| Initial acknowledgment | Within 72 hours |
| Triage and validation | Within 1 week |
| Fix (critical/high) | Best effort, typically within 2 weeks |
| Fix (medium/low) | Next planned release |

### Disclosure

We follow [coordinated vulnerability disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). We will credit reporters unless they prefer to remain anonymous.

## Security Measures

This repository uses:

- **Dependabot** for automated dependency vulnerability alerts and updates
- **GitHub Secret Scanning** with push protection to prevent credential leaks
- **CodeQL Analysis** for automated code scanning on every push and PR
- **AGPL-3.0 License** ensuring source availability for security auditing
