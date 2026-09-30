import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
 import migration_fields as m
except ImportError:
 raise unittest.SkipTest("Optional migration dependencies are not installed")
class Tests(unittest.TestCase):
 def test_decimal_bottle_prefers_num_over_rounded_legacy(self):
  _,_,p=m.convert({'type':'FEED','feedType':'BOTTLE','beginDt':0,'tz':'UTC','bottleTypeBreastMilk':True,'bottleVolumeNum':375,'bottleVolumeExp':2,'bottleVolume':38,'bottleVolumeUnit':'FLOZ'})
  self.assertEqual(p['amount'],3.75);self.assertEqual(p['units'],'oz')
 def test_missing_bottle_units_rejected(self):
  with self.assertRaises(m.Unmapped):m.convert({'type':'FEED','feedType':'BOTTLE','beginDt':0,'tz':'UTC'})
 def test_missing_nursing_duration_is_not_fabricated(self):
  _,_,p=m.convert({'type':'FEED','feedType':'BREAST','beginDt':0,'tz':'UTC','breastLeftDuration':123456,'breastEndSide':'LEFT'})
  self.assertEqual(p['leftDuration'],123.456);self.assertNotIn('rightDuration',p)
 def test_unknown_nursing_duration_rejected(self):
  with self.assertRaises(m.Unmapped):m.convert({'type':'FEED','feedType':'BREAST','beginDt':0,'tz':'UTC'})
 def test_combined_texture_retained_and_not_guessed(self):
  _,_,p=m.convert({'type':'DIAPER','beginDt':0,'tz':'UTC','diaperTypePee':True,'diaperTypePoop':True,'diaperPoopTexture':'MUSH RUN','diaperPoopBlowout':True})
  self.assertEqual(p['mode'],'both');self.assertNotIn('consistency',p);self.assertIn('MUSH RUN',p['notes']);self.assertIn('blowout',p['notes'])
 def test_dst_offsets_follow_record_dates(self):
  from datetime import datetime,timezone
  start=datetime(2024,3,10,9,30,tzinfo=timezone.utc).timestamp()*1000
  _,_,p=m.convert({'type':'SLEEP','beginDt':start,'endDt':start+3600000,'tz':'America/Los_Angeles'})
  self.assertEqual(p['offset'],480);self.assertEqual(p['end_offset'],420);self.assertEqual(p['duration'],3600)
 def test_growth_converts_to_metric(self):
  _,_,p=m.convert({'type':'GROW','beginDt':0,'tz':'UTC','weightNum':809375,'weightExp':5,'weightUnit':'LB','heightNum':200,'heightExp':1,'heightUnit':'IN'})
  self.assertAlmostEqual(p['weight'],8.09375*0.45359237);self.assertEqual(p['height'],50.8)
 def test_readback_detects_mismatch(self):
  self.assertTrue(m.equal({'start':1,'lastUpdated':1},{'start':1,'lastUpdated':2}));self.assertFalse(m.equal({'start':1},{'start':2}))
if __name__=='__main__':unittest.main()
