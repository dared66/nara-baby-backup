#!/usr/bin/env python3
"""Create an isolated environment for the optional Huckleberry import."""
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3,14):
        print('Install Python 3.14+ from python.org, then run this again.')
        return 1
    root = Path(__file__).resolve().parent
    folder = root/'.venv'
    if folder.exists():
        print('An environment already exists. See README.md for how to run it. No files were changed.')
        return 1
    print('This installs the pinned Huckleberry library and its dependencies from PyPI into .venv beside the script.')
    if input('Continue? [y/N] ').strip().lower() != 'y':
        return 0
    venv.create(folder,with_pip=True)
    python = folder/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    result = subprocess.run([str(python),'-m','pip','install','-r',str(root/'requirements-migration.txt')],check=False)
    if result.returncode:
        print('Setup failed. Keep .venv and retry its Python with: -m pip install -r requirements-migration.txt')
        return 1
    print('Setup complete. Run:')
    print((' .\\.venv\\Scripts\\python.exe nara_backup.py' if os.name=='nt' else './.venv/bin/python nara_backup.py').strip())
    return 0


if __name__=='__main__':
    sys.exit(main())
