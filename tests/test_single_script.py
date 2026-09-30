import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import nara_backup as m

class Tests(unittest.TestCase):
 def test_file_runs_alone_without_neighboring_modules(self):
  with tempfile.TemporaryDirectory() as tmp:
   script=Path(tmp)/'nara_backup.py'
   script.write_bytes(Path(m.__file__).read_bytes())
   completed=subprocess.run([sys.executable,'-I',str(script),'--help'],capture_output=True,text=True)
   self.assertEqual(completed.returncode,0,completed.stderr)
   self.assertIn('--backup-only',completed.stdout)
 def test_loading_single_script_does_not_load_optional_packages(self):
  code="import importlib.util, sys; s=importlib.util.spec_from_file_location('onefile',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert 'aiohttp' not in sys.modules and 'huckleberry_api' not in sys.modules"
  result=subprocess.run([sys.executable,'-I','-c',code,str(Path(m.__file__).resolve())],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stderr)
 def test_option_one_never_sets_up_migration(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(sys,'argv',['nara_backup.py']),patch('builtins.input',return_value='1'),patch.object(m,'credentials',return_value=('fake@example.invalid','fake')),patch.object(m.Client,'login'),patch.object(m,'export',return_value={'errors':[]}),patch.object(m,'ensure_migration_dependencies') as setup:
   self.assertEqual(m.main(),0);setup.assert_not_called()
 def test_option_two_backs_up_before_requesting_huckleberry_credentials(self):
  events=[]
  def login(service):events.append(service);return ('fake@example.invalid','fake')
  def backup(client,folder):events.append('backup');return {'errors':[]}
  async def canceled(*args):events.append('migration');return {'canceled':True}
  with tempfile.TemporaryDirectory() as tmp,patch.object(sys,'argv',['nara_backup.py','--output',tmp]),patch.object(sys,'version_info',(3,14)),patch('builtins.input',return_value='2'),patch.object(m,'credentials',side_effect=login),patch.object(m.Client,'login'),patch.object(m,'export',side_effect=backup),patch.object(m,'prepare',return_value=[]),patch.object(m,'run_migration',side_effect=canceled),patch.object(m,'ensure_migration_dependencies'):
   self.assertEqual(m.main(),0)
  self.assertEqual(events,['Nara','backup','Huckleberry','migration'])
 def test_declining_dependency_install_does_not_run_subprocess(self):
  with patch.object(m,'load_migration_dependencies',side_effect=ImportError),patch.object(Path,'exists',return_value=False),patch('builtins.input',return_value='n'),patch.object(m.subprocess,'run') as run:
   with self.assertRaises(m.UserError):m.ensure_migration_dependencies()
   run.assert_not_called()
if __name__=='__main__':unittest.main()
