# Contributing

Keep backup usable with Python 3.9 and no dependencies. Keep migration optional and compatible with its pinned client.

Run the offline test suite before submitting a change. Use synthetic fixtures only. Never commit exports, child names, birth dates, identifiers, passwords, tokens, or screenshots from real accounts.

Schema changes need evidence from the upstream client's schema/source or an explicitly authorised test account. Add regression tests for conversions, missing values, timezone changes, duplicate detection and partial failures. Do not add guessed enum values or silently substitute zero for missing data.

Live testing must be explicitly authorised by the account owner. Ordinary tests must not contact either service. Keep writes create-only, persist intended identifiers before submission, and verify saved values after writes. Do not retry uncertain submissions without reading server state.

When reporting a bug, include Python/OS versions and a sanitised error summary. Do not attach a real backup or migration report. Preview changes and identify new data-loss limitations in the README.
