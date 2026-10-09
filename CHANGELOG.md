# Changelog

## Unreleased

- Migrate Nara bath routines to Huckleberry bath activities, keeping notes and historical timezone offsets. Other routines remain unmapped.

## 0.3.0

- Add dependency-free option 3: native Little Log CSVs using each baby’s exported destination identity.
- Preserve original source records and report unmapped, deleted, and unassociated entries.
- Add detailed copy-and-paste instructions at the bottom of the README.

## 0.2.0

- Consolidate backup, field conversion, migration, and guided setup into one downloadable `nara_backup.py`.
- Offer optional dependency installation only for option 2; reuse its isolated environment on later runs.
- Preserve CLI resume, explicit import confirmation, and readback checks.

## 0.1.0

- Dependency-free Nara JSON/CSV backup for every accessible family.
- Optional guided Huckleberry migration with a pinned client dependency.
- Child matching by name/birth date, preview and explicit import confirmation.
- Create-only writes, conflict detection, recovery journals and full readback.
- Historical timezone calculation, fixed-point numeric conversion, explicit unsupported-data reports.
- Offline tests and cross-platform CI configuration.

Known limitations: no photo files, milestone/vaccine migration, profile creation, or guarantee of exhaustive service coverage. App display requires independent checking.
