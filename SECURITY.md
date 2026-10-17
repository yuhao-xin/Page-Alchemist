# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

## Scope

Notion Alchemist is a **local-first** CLI tool. It does not operate any server,
does not phone home, and stores nothing outside the directories you point it at.

Secrets handling:

- Credentials are read from environment variables / `.env` only.
- `.env` is git-ignored by default; never commit it.
- `notion-alchemist doctor` prints only the *presence* and *shape* of tokens,
  never their values.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

1. Use GitHub's private vulnerability reporting
   ("Security" → "Report a vulnerability") if available, or
2. Email the maintainers via the address listed in the repository metadata.

Include: affected version, engine, reproduction steps, and impact. We aim to
acknowledge within 72 hours.

## Handling of unofficial engine

The unofficial engine (`--backend unofficial`) relies on Notion's internal
export endpoint using a `token_v2` cookie. Treat that cookie as a **password**:

- it grants full access to your Notion account,
- rotate it (log out / clear cookies) if you suspect exposure,
- prefer the official API engine whenever the source page allows it.

## Responsible use

This tool extracts content you are authorised to access. Respect the licences
and terms of the source material. See the "Responsible use" section of the
README.
