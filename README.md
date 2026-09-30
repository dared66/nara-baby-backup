# Nara Baby Backup & Huckleberry Migration

Keep a local copy of your Nara Baby history, with an optional guided copy into Huckleberry. Plain Python, no app builds, Docker, AI assistant, phone connection, or Keychain setup.

**Backup:** Python 3.9+, no extra packages.  
**Huckleberry migration:** Python 3.14+ and an optional dependency installed into a local environment.

This is an unofficial community tool. It does not guarantee a complete copy of everything held by either service. Photos are not downloaded. Keep the original backup.

## Back up Nara

1. Install Python from [python.org](https://www.python.org/downloads/) if needed. On Windows, enable **Add Python to PATH** if offered.
2. Download and extract this project. Open Terminal (Mac/Linux) or PowerShell (Windows) in that folder.
3. Run:

   Mac/Linux: `python3 nara_backup.py --backup-only`

   Windows: `py nara_backup.py --backup-only`

4. Enter your Nara email and password. The password is hidden while you type.

The script creates a new `nara-backup-...` folder. Each `family-XX` contains child profiles, original activity sync JSON, lossless `activities.json`, and spreadsheet-friendly `activities.csv`. Account and family database snapshots are also attempted; Nara may deny these broader requests even when history is available. `export-report.json` lists failures and record counts.

CSV preserves every returned field, with nested objects represented as JSON text. Original identifiers, notes, units, timestamps, unknown fields, and deletion markers stay in JSON. Formula-like text is escaped only in CSV to prevent spreadsheet execution.

## Copy history to Huckleberry

Create a profile for each child in Huckleberry first. Use the same name and birth date as Nara. The tool will stop if profiles cannot be matched uniquely; it does not create or modify profiles.

Install **Python 3.14 or newer**, then run this one-time setup:

Mac/Linux:

```sh
python3 setup_migration.py
./.venv/bin/python nara_backup.py
```

Windows:

```powershell
py -3.14 setup_migration.py
.\.venv\Scripts\python.exe nara_backup.py
```

Choose **2** in the menu. The setup script explains the dependency installation and asks before downloading it. It installs `huckleberry-api==0.4.7` and its dependencies from PyPI into `.venv` beside the scripts; it does not change system Python.

The guided tool saves a Nara backup first, privately asks for your Huckleberry login, matches child profiles, checks destination history, and previews new records, existing records, conflicts, unsupported entries, and photo references. **No import writes occur until you type `IMPORT`.**

Each write creates a new history document. Existing documents are never overwritten. The tool reads back each batch and then scans the full destination collection to compare all mapped payload fields and confirm prior history is unchanged. Historical timezone offsets are calculated from each record's date, including daylight-saving changes. Latest-event summaries, live timers, reminders, and profile settings are not modified.

### Resume or import an existing backup

Keep the whole backup folder, including its reports and journal. Run using the migration environment:

```sh
./.venv/bin/python nara_backup.py --backup-dir /path/to/nara-backup-folder
```

On Windows, use `.\.venv\Scripts\python.exe` and quote paths containing spaces. The tool checks the server before every import, so already-matching entries are recognised. Same-time/category conflicts are skipped and reported rather than overwritten. Batch writes use create-only preconditions and no automatic retries. If a response is lost, actual server state is checked; retain the journal and resume from the same backup.

A recreated backup or modified source can produce conflicts instead of duplicates. Do not change backup filenames, identifiers, or JSON to force an import.

## What migration can preserve

| Nara category | Huckleberry destination |
| --- | --- |
| Diapers | Pee/poo/both/dry, rash, supported color/texture, notes |
| Nursing | Timestamp, available left/right durations, ending side; starting side/manual-entry details in notes |
| Bottles | Timestamp, recorded volume/unit and milk type; unspecified/mixed milk marked Other with explanatory notes |
| Completed sleep | Start, duration, original-date timezone offsets |
| Growth | Weight/height/head circumference, converted to metric units |

Nara fixed-point values use the original `Num` and `Exp` fields; rounded legacy bottle fields are not used. Missing nursing-side durations remain absent, not fabricated as zero. A nursing record without any duration and a bottle record without a verified unit are kept in the backup but not imported. Unknown numeric encodings stop conversion rather than silently changing values.

Combined stool descriptions and descriptions without an exact destination option are preserved in notes. A native structured texture is set only for the explicit mappings RUN/runny, MUCOUS/mucousy, PEBBLE/pebbles, and SOLID/solid. Original notes remain in notes.

**Milestones, vaccine entries, photos, and other unsupported categories are not migrated.** Photo references remain in the backup, but the image files are absent. Deletion-marked records are retained in the backup and excluded from migration. Records not associated with a discovered child profile are not assigned to a baby. Nothing is guessed to fill missing values.

## Verification and limitations

- `export-report.json` describes request success, not proven exhaustive server coverage. Its `complete` field has that limited meaning.
- `migration-plan.json` retains the conversion plan and unsupported original records.
- `migration-journal.json` retains the most recently prepared child's intended IDs for recovery.
- `migration-report.json` records verified counts, conflicts, unsupported original records, photo references, and prior-history checks.
- `all_supported_records_verified` can be true while `everything_transferred` remains false. A zero migration exit status means all supported records passed database readback, not that every source byte moved.
- App display, analytical behavior, and source completeness require independent checks. Compare the original backup with [Nara's official export](https://nara.com/pages/nara-baby-app-faqs), and inspect representative entries in Huckleberry. A matching database payload is not a guarantee of how the app displays it.
- Full-reset Nara sync was observed to return a stable history; following its cursor returned no additional records in the tested account. That does not prove universal server retention or pagination behavior.
- Both services can change their private APIs. No official Huckleberry import is offered; its [help page](https://huckleberry.zendesk.com/hc/en-us/articles/4409286804627-Can-I-export-my-data-from-the-app) says imports are unsupported.

The underlying migration strategy was live-tested with feed, diaper, sleep and growth history and individual field readback. The generalised release is checked with offline tests and a read-only live preview. The initial diaper was also confirmed visible in the app. This does not establish universal account/login support or verification of every app screen.

## Privacy

Run this on your own computer. Passwords and authentication tokens are not written to backups, arguments, environment variables, or reports. Only email/password authentication is implemented; Apple/Google-only login is unsupported. HTTPS verification stays enabled. Backups contain private family information: keep them out of public repositories and cloud folders you do not control.

On Unix, new folders/files are private. Windows uses your folder's access permissions. `.gitignore` is a convenience, not a privacy guarantee—custom output folders can still be accidentally committed. Inspect exactly what you publish.

## Troubleshooting

- **Python not found:** install Python and reopen your terminal. Some systems use `python` rather than `python3`.
- **Missing migration dependencies:** run `setup_migration.py`, then use the `.venv` Python command above. Backup-only never needs those packages.
- **Setup failed:** the environment remains in `.venv`. Retry with its Python: `-m pip install -r requirements-migration.txt`.
- **Login/access denied:** check the email/password, connectivity and service permissions. No raw upstream diagnostic payload is printed.
- **Partial backup:** keep saved files and read `export-report.json`. History migration can proceed if every family has both child profiles and parsed history, even when broader snapshots were denied.
- **Incomplete migration:** keep reports/journal. Resume with `--backup-dir`; conflicts need review. Never delete destination entries to force a rerun.
- **Certificate problem on Mac:** use the certificate installer supplied with your Python installation. Do not disable HTTPS verification.

Run `python3 nara_backup.py --help` for options. `nara_export.py` remains available as the standalone backup-only script.

## Development and attribution

```sh
python3 -m unittest discover -s tests -v
```

Without optional dependencies, migration tests are skipped. To run all tests, use the `.venv` Python after setup. All checked-in tests are offline; none authenticate or create real baby records. CI is configured for Python 3.9/3.14 and Windows/macOS/Linux. A configured CI matrix is not a claim that those remote jobs have already run.

Endpoint/schema observations come from [nara-baby-tracker-api](https://github.com/jfchenier/nara-baby-tracker-api) and [NaraGaiden](https://github.com/edemaine/NaraGaiden). Migration uses the MIT-licensed, unofficial [huckleberry-api](https://github.com/Woyken/py-huckleberry-api). No upstream client is vendored. Dependency version is pinned; transitive versions are resolved during setup.

MIT licensed. See CONTRIBUTING.md and SECURITY.md. No affiliation with Nara or Huckleberry. This package contains no family data or account credentials.
