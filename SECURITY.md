# Security Policy

## Supported versions

Only the latest release on the `main` branch is supported. Security fixes are
backported to the latest tagged release only.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities. Instead,
report privately through the project's GitHub Security Advisories page
(`https://github.com/abhishek/macmedic/security/advisories/new`) or open a
private issue and label it `security`.

You can expect an acknowledgment within 5 business days and a remediation plan
or fix within 30 days, depending on severity.

## Scope

MacMedic is a menu bar utility that runs with the privileges of the launching
user. The following are explicitly in scope:

- Path traversal or arbitrary-delete bugs in `macmedic/scanner.py` (Smart Clean)
- Injection via `launchctl bootout` / plist manipulation in `macmedic/launchagents.py`
- Unsafe SMC reads/writes in `macmedic/smc.py` (a malformed SMC key must never
  crash the app or write to an unintended key)
- Config parsing in `macmedic/config.py` (a hostile `config.json` must never
  disable protected-path checks)

The config file is read from the user's own home directory and is not a
trusted-input surface; still, treat any attacker-controlled `config.json` as
low-but-nonzero risk.

## Reporting principles

Include your macOS version, Intel/Apple Silicon, the MacMedic version, and the
steps to reproduce. If the issue involves the filesystem, run MacMedic from the
command line with logging to capture `~/Library/Logs/MacMedic.log`.