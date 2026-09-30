#!/usr/bin/env python3
"""Guided Nara backup with optional Huckleberry history migration."""
import argparse
import asyncio
from datetime import datetime
import getpass
import json
import os
from pathlib import Path
import sys
import warnings

import nara_export


class UserError(Exception):
    pass


def credentials(service):
    if not sys.stdin.isatty():
        raise UserError('Run this in your own terminal for private login prompts.')
    email = input('%s email: ' % service).strip()
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        password = getpass.getpass('%s password (hidden): ' % service)
    if not email or not password:
        raise UserError('Email and password are required.')
    return email,password


def confirm(preview):
    print('\nImport preview:')
    for child in preview:
        print('  {name}: {new_records} new, {already_present} already present, {conflicting_records} conflicts, '
              '{unmapped_records} unmapped, {photo_files_not_transferred} photo references without files.'.format(**child))
    print('Original records remain in your local backup. Conflicts are skipped; existing records are never overwritten.')
    print('This is an unofficial history import. Photos, unsupported entries and other profile settings are not copied.')
    return input('Type IMPORT to copy the supported records into Huckleberry: ').strip() == 'IMPORT'


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-only',action='store_true',help='Back up Nara without Huckleberry dependencies')
    parser.add_argument('--migrate',action='store_true',help='Back up Nara, then preview a Huckleberry import')
    parser.add_argument('--backup-dir',type=Path,help='Use an existing backup for a migration/resume')
    parser.add_argument('--output',type=Path,help='New backup folder; must not already exist')
    args = parser.parse_args()
    if args.backup_only and (args.migrate or args.backup_dir):
        parser.error('--backup-only cannot be combined with migration')
    if args.backup_dir and args.output:
        parser.error('--backup-dir and --output cannot be combined')
    migrate = args.migrate or args.backup_dir is not None
    if not args.backup_only and not migrate:
        print('1. Back up Nara\n2. Back up Nara and copy history to Huckleberry')
        choice = input('Choose 1 or 2: ').strip()
        if choice not in ('1','2'):
            raise UserError('Choose 1 or 2.')
        migrate = choice == '2'
    if migrate:
        if sys.version_info < (3,14):
            raise UserError('Huckleberry migration requires Python 3.14 or newer. Backup-only works with Python 3.9+.')
        try:
            import huckleberry_import
        except ImportError:
            raise UserError('Migration dependencies are missing. Run setup_migration.py as described in README.md, then use the .venv Python.') from None
    folder = args.backup_dir
    if folder is None:
        folder = args.output or Path('nara-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        client = nara_export.Client()
        email,password = credentials('Nara')
        try:
            client.login(email,password)
            email=password=None
            report = nara_export.export(client,folder)
        finally:
            email=password=None
            client.token=client.uid=None
        print('Backup saved to: '+str(folder.resolve()))
        if report['errors']:
            print('Some backup requests failed. Details are in export-report.json.')
        if not migrate:
            print('Compare with official app exports before claiming exhaustive coverage.')
            return 1 if report['errors'] else 0
    if not folder.is_dir():
        raise UserError('Backup folder not found.')
    groups = huckleberry_import.prepare(folder)
    # Keep unmapped original data available even if login or profile matching fails.
    huckleberry_import.save(folder/'migration-plan.json',{'children':groups})
    email,password = credentials('Huckleberry')
    try:
        result = asyncio.run(huckleberry_import.migrate(folder,groups,email,password,confirm))
    finally:
        email=password=None
    if result.get('canceled'):
        print('Canceled. Your backup is saved; no import writes were submitted.')
        return 0
    print('\nMigration result:')
    for child in result['children']:
        print('%s: %d/%d supported records verified; %d unmapped; %d photo references without files.' %
              (child['name'],child['verified'],child['supported_records'],len(child['unmapped']),len(child['photo_references_without_files'])))
    print('Report: '+str((folder/'migration-report.json').resolve()))
    print('Check representative entries in the Huckleberry app. Database readback does not verify app display or exhaustive source coverage.')
    return 0 if result['all_supported_records_verified'] else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (KeyboardInterrupt,EOFError):
        print('\nCanceled. Keep any saved backup/report; resume using --backup-dir.',file=sys.stderr)
        sys.exit(1)
    except (UserError,nara_export.ExportError) as exc:
        print('Error: '+str(exc),file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # Do not print upstream exceptions/tracebacks: they can include private payloads.
        if exc.__class__.__name__ == 'MigrationError':
            print('Error: '+str(exc),file=sys.stderr)
        else:
            print('Operation stopped. Check connectivity, login, disk access and saved reports. Resume with --backup-dir; do not delete the backup.',file=sys.stderr)
        sys.exit(1)
