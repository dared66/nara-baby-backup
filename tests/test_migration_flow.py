"""Offline end-to-end checks: confirmation, uncertain submission, and corruption."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
 import nara_backup as m
 m.load_migration_dependencies()
except ImportError:
 raise unittest.SkipTest('Optional migration dependencies are not installed')

class Snapshot:
 def __init__(self,key,value):self.id=key;self.value=value;self.exists=value is not None
 def to_dict(self):return self.value
class Ref:
 def __init__(self,db,path):self.db=db;self.path=path
 def document(self,key):return Ref(self.db,self.path+'/'+key)
 def collection(self,key):return Ref(self.db,self.path+'/'+key)
 async def stream(self,timeout):
  prefix=self.path+'/'
  for path,data in list(self.db.data.items()):
   if path.startswith(prefix):yield Snapshot(path.split('/')[-1],dict(data))
class Batch:
 def __init__(self,db):self.db=db;self.pending=[]
 def create(self,ref,payload):self.pending.append((ref,dict(payload)))
 async def commit(self,**kwargs):
  if any(ref.path in self.db.data for ref,_ in self.pending):raise RuntimeError('Already exists')
  for ref,payload in self.pending:
   if self.db.corrupt:payload['offset']=999
   self.db.data[ref.path]=payload
   self.db.writes+=1
  if self.db.lose_response:raise TimeoutError('Response lost after commit')
class DB:
 def __init__(self):self.data={};self.writes=0;self.lose_response=False;self.corrupt=False
 def collection(self,key):return Ref(self,key)
 def batch(self):return Batch(self)
 async def get_all(self,refs,timeout):
  for ref in refs:yield Snapshot(ref.path.split('/')[-1],self.data.get(ref.path))
 def close(self):pass
class API:
 database=None
 def __init__(self,*args):self._firestore_client=self.database
 async def authenticate(self):pass
 async def get_user(self):return SimpleNamespace(childList=[SimpleNamespace(cid='c',nickname='Example')])
 async def get_child(self,cid):return SimpleNamespace(childsName='Example',birthdate='2024-01-01')
 async def _get_firestore_client(self):return self.database

class Tests(unittest.TestCase):
 def groups(self):
  return [{'profile':{'name':'Example','birthDate':'2024-01-01'},'source_child':'source','unmapped':[],
   'photo_references':[],'deleted_excluded':0,'records':[{'collection':'diaper','subcollection':'intervals',
   'document':'source-doc','source_id':'original','payload':{'mode':'pee','start':1,'offset':0}}]}]
 def run_flow(self,db,approve):
  API.database=db
  with tempfile.TemporaryDirectory() as tmp,patch.object(m,'HuckleberryAPI',API):
   return asyncio.run(m.run_migration(Path(tmp),self.groups(),'synthetic@example.invalid','not-a-real-password',lambda preview:approve,lambda text:None))
 def test_declining_confirmation_prevents_all_writes(self):
  db=DB();r=self.run_flow(db,False)
  self.assertTrue(r['canceled']);self.assertEqual(db.writes,0)
 def test_verified_import_and_rerun_do_not_duplicate(self):
  db=DB();r=self.run_flow(db,True)
  self.assertTrue(r['all_supported_records_verified']);self.assertEqual(db.writes,1)
  r=self.run_flow(db,True)
  self.assertTrue(r['all_supported_records_verified']);self.assertEqual(db.writes,1)
 def test_lost_commit_response_readback_recovers_without_retry(self):
  db=DB();db.lose_response=True;r=self.run_flow(db,True)
  self.assertTrue(r['all_supported_records_verified']);self.assertEqual(db.writes,1)
 def test_corrupted_write_cannot_report_verified_success(self):
  db=DB();db.corrupt=True;r=self.run_flow(db,True)
  self.assertFalse(r['all_supported_records_verified']);self.assertEqual(r['children'][0]['verified'],0)
 def test_conflict_preserves_existing_destination(self):
  db=DB();db.data['diaper/c/intervals/existing']={'mode':'pee','start':1,'offset':480}
  before=dict(db.data);r=self.run_flow(db,True)
  self.assertFalse(r['all_supported_records_verified']);self.assertEqual(db.writes,0);self.assertEqual(db.data,before)
if __name__=='__main__':unittest.main()
