import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
 import nara_backup as m
 m.load_migration_dependencies()
except ImportError:
 raise unittest.SkipTest('Optional migration dependencies are not installed')

class Tests(unittest.TestCase):
 def record(self):
  return {'collection':'diaper','subcollection':'intervals','document':'source','source_id':'id','payload':{'mode':'pee','start':1,'offset':0}}
 def test_matching_requires_name_and_birthdate(self):
  g=[{'profile':{'name':'Example','birthDate':'2024-01-01'}}]
  self.assertEqual(m.match(g,[{'name':'example','birthdate':'2024-01-01','id':'x'}])[0][1]['id'],'x')
  with self.assertRaises(m.MigrationError):m.match(g,[{'name':'Example','birthdate':'2024-01-02','id':'x'}])
 def test_duplicate_profiles_rejected(self):
  g=[{'profile':{'name':'Example','birthDate':'2024-01-01'}}]
  with self.assertRaises(m.MigrationError):m.match(g,[{'name':'Example','birthdate':'2024-01-01','id':k} for k in ['x','y']])
 def test_same_destination_cannot_receive_two_source_children(self):
  g=[{'profile':{'name':'Example','birthDate':'2024-01-01'}}]*2
  with self.assertRaises(m.MigrationError):m.match(g,[{'name':'Example','birthdate':'2024-01-01','id':'x'}])
 def test_existing_source_document_is_not_overwritten(self):
  r=self.record();h={('diaper','intervals'):{'source':{'mode':'pee','start':1,'offset':480}}}
  pending,existing,conflicts=m.classify([r],h)
  self.assertEqual(len(conflicts),1);self.assertFalse(pending)
 def test_batch_history_duplicate_recognized(self):
  r=self.record();h={('diaper','intervals'):{'batch':{'multi':True,'data':{'entry':dict(r['payload'])}}}}
  pending,existing,conflicts=m.classify([r],h)
  self.assertEqual(len(existing),1);self.assertFalse(pending);self.assertFalse(conflicts)
 def test_timestamp_conflict_never_submitted(self):
  r=self.record();h={('diaper','intervals'):{'other':{'mode':'pee','start':1,'offset':480}}}
  self.assertEqual(len(m.classify([r],h)[2]),1)
 def test_missing_source_profiles_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'family-01').mkdir()
   with self.assertRaises(m.MigrationError):m.prepare(p)
 def test_unmapped_and_photo_references_preserved(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);f=p/'family-01';f.mkdir()
   (p/'family-memberships.json').write_text('{}')
   (f/'children.json').write_text(json.dumps({'c':{'name':'Example','birthDate':'2024-01-01'}}))
   (f/'activities.json').write_text(json.dumps({'r':{'childKey':'c','beginDt':0,'tz':'UTC','type':'GROW.MILESTONE','photo':{'uri':'nara.photo.track:example'}}}))
   group=m.prepare(p)[0]
   self.assertEqual(len(group['unmapped']),1);self.assertEqual(len(group['photo_references']),1)
 def test_plan_ids_stable(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);f=p/'family-01';f.mkdir()
   (p/'family-memberships.json').write_text('{}')
   (f/'children.json').write_text(json.dumps({'c':{'name':'Example','birthDate':'2024-01-01'}}))
   (f/'activities.json').write_text(json.dumps({'r':{'childKey':'c','beginDt':0,'tz':'UTC','type':'DIAPER','diaperTypePee':True}}))
   self.assertEqual(m.prepare(p)[0]['records'][0]['document'],m.prepare(p)[0]['records'][0]['document'])
if __name__=='__main__':unittest.main()
