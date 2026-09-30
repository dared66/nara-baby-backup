# Nara Baby Backup

One Python script to back up Nara Baby and optionally migrate supported history to Huckleberry. MIT licensed. Unofficial; not affiliated with either app.

## Run

1. Install [Python](https://www.python.org/downloads/): **3.9+ for backup**, **3.14+ for Huckleberry migration**.
2. Download [nara_backup.py](https://raw.githubusercontent.com/dared66/nara-baby-backup/main/nara_backup.py).
3. Open a terminal in its folder and run:

   **Mac/Linux:** `python3 nara_backup.py`

   **Windows:** `py nara_backup.py` (use `py -3.14` if you have multiple versions).

```text
1. Back up Nara Baby only
2. Back up Nara Baby and migrate to Huckleberry
```

Enter your login when prompted. Passwords are hidden and never saved. Email/password login is required; Apple/Google-only login is unsupported.

**Option 1** needs no extra packages. It saves every accessible family's returned history and profiles as JSON and CSV in a new `nara-backup-...` folder. Broader account/family snapshots are also attempted; failures appear in `export-report.json`.

**Option 2** offers to install its pinned Huckleberry dependency into `.nara-migration-env` beside the script, then continues automatically. It reuses that environment on later runs without changing system Python.

Create each child's Huckleberry profile first, using the same name and birth date as Nara. The tool backs up Nara, checks destination history, and shows an import preview. **Nothing is imported until you type `IMPORT`.**

## What transfers

| Category | Transferred information |
| --- | --- |
| Diapers | Contents, rash, supported color/texture, notes |
| Nursing | Available per-side durations, ending side; extra details in notes |
| Bottles | Recorded volume/unit and milk type |
| Sleep | Completed intervals |
| Growth | Measurements converted to metric units |

Original timestamps and historical timezone offsets are preserved. Combined diaper descriptions and details without an exact destination option stay in notes. Missing values are not invented.

**Photos, milestones, vaccine entries, unsupported categories, and profile settings are not transferred.** Original records and photo references remain in the backup; actual photo files are not downloaded. Deletion-marked records stay in the backup but are excluded from migration. Unassociated records are not assigned to a child.

## Verification and resume

The importer creates records without overwriting existing history, recognises matching entries, and skips conflicting entries. It reads back every mapped record and checks that prior history is unchanged.

Keep the whole backup folder. To resume or migrate an existing backup:

```sh
python3 nara_backup.py --backup-dir /path/to/nara-backup-folder
```

On Windows, substitute `py -3.14` for `python3`. Quote paths containing spaces. Interrupted imports check server state before submitting again; do not edit or delete the backup to force a retry.

Reports in the backup folder:

- `export-report.json`: download status and counts.
- `migration-plan.json`: mapped records and unsupported original data.
- `migration-journal.json`: intended identifiers for recovery.
- `migration-report.json`: readback results, conflicts, and transfer exceptions.

**Successful requests and readback do not prove exhaustive source coverage or correct app display.** Compare against [Nara's official export](https://nara.com/pages/nara-baby-app-faqs) and check representative entries in Huckleberry. `all_supported_records_verified` can be true while `everything_transferred` remains false. Huckleberry's [official help](https://huckleberry.zendesk.com/hc/en-us/articles/4409286804627-Can-I-export-my-data-from-the-app) says importing is unsupported; this tool uses a private API that may change.

## Privacy and troubleshooting

Run this on your own computer. Credentials are not stored in files, arguments, or environment variables. **Backups contain private family information—never publish them.** Unix files use private permissions; Windows follows your folder permissions. Backups are not encrypted, and `.gitignore` does not protect custom output locations.

- **Python not found:** install it, reopen the terminal, and try again.
- **Dependency setup failed:** check connectivity and rerun option 2.
- **Login/access denied:** check your email/password and service permissions.
- **Partial backup/import:** retain all files, read the reports, and resume using `--backup-dir`. Migration requires profiles and parsed history for every family; broader snapshots may be denied independently.

Run `python3 nara_backup.py --help` for flags, including `--backup-only`, `--migrate`, and `--output`.

## Development

```sh
python3 -m unittest discover -s tests -v
```

Tests are offline; migration tests require `huckleberry-api==0.4.7` and otherwise skip. CI covers Windows, macOS, and Linux on Python 3.9/3.14. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

Endpoint/schema references: [nara-baby-tracker-api](https://github.com/jfchenier/nara-baby-tracker-api), [NaraGaiden](https://github.com/edemaine/NaraGaiden). Migration uses [huckleberry-api](https://github.com/Woyken/py-huckleberry-api), pinned at 0.4.7; transitive dependencies resolve during setup.
