# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-04-15

### Added
- Fold correction invoices (KOR) into the invoice they correct — parent row shows summed effective amounts, corrections listed in the detail view with signed deltas.
- "KOR ×N" badge on corrected invoices and "Korekta do X" badge on orphan corrections (parent not in DB).
- Warning icon when paid/ignored flags don't match between a parent and its corrections; toggling the parent cascades to its corrections.
- Brutto and Do zapłaty amounts in the invoice detail view and per line item.
- Redownload from KSeF now cascades to all corrections of the selected invoice.

### Fixed
- KSeF sync no longer redownloads locally-ignored invoices.

## [0.1.0] - 2026-04-11

### Added
- First tagged release.
- KSeF authentication via certificate + encrypted private key.
- Zero-knowledge server: invoices encrypted client-side with an AES key wrapped by the user's certificate public key.
- Invoice sync from KSeF (last 12 months), list/sort/filter, inline detail expansion with line items.
- Multi-select invoices with bulk actions: mark paid, mark ignored, generate mBank transfer CSV (capped at 32 per file).
- Per-NIP bank account and configurable transfer title template.
- Payment amount (DoZaplaty) extraction for invoices where it differs from gross (e.g. notarial with PCC).
- CI/CD pipeline: GitHub Actions builds and pushes Docker images to `ghcr.io/krzaq/ksefcio` on push to main and on version tags.
- Version + commit SHA baked into the build and shown in the footer.

[Unreleased]: https://github.com/KrzaQ/ksefcio/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/KrzaQ/ksefcio/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/KrzaQ/ksefcio/releases/tag/v0.1.0
