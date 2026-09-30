import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nara_backup as m

class Tests(unittest.TestCase):
    def record(self, **fields):
        return dict(beginDt=1700000000123, tz='America/Los_Angeles', childKey='baby', **fields)

    def test_native_csv_quoting_and_source_roundtrip(self):
        r = self.record(type='DIAPER', diaperTypePee=True, diaperTypePoop=True,
            diaperPoopTexture='MUSH RUN', diaperPoopColor='BROWN YELLOW', note='=formula,"quoted"\nnext')
        rows = m.little_log_rows('diaper', r, 'destination', 'Nara caregiver 1')
        text = m.little_log_csv({'id':'destination','name':"'family",'babyName':'Baby'}, rows)
        decoded = list(csv.reader(io.StringIO(text)))
        self.assertEqual(decoded[0], m.LITTLE_LOG_HEADER)
        self.assertTrue(all(len(row)==18 for row in decoded))
        self.assertEqual(decoded[1][2], "''family")
        self.assertTrue(decoded[2][10].startswith("'="))
        payload = json.loads(decoded[2][17])
        self.assertEqual(payload['source']['original'], r)
        self.assertEqual(payload['details']['poopConsistencies'], ['mushy','watery'])

    def test_nursing_ms_and_missing_end(self):
        r = self.record(type='FEED',feedType='BREAST',breastLeftDuration=1001)
        row = m.little_log_rows('n',r,'dest','author')[0]
        self.assertEqual(row[9:12], ['',1,0])
        self.assertEqual(json.loads(row[-1])['source']['leftDurationMs'],1001)
        self.assertEqual(row,m.little_log_rows('n',r,'dest','author')[0])

    def test_volume_uses_fixed_point_not_display_value(self):
        r = self.record(type='FEED',feedType='BOTTLE',bottleVolumeNum=125,bottleVolumeExp=2,
            bottleVolumeUnit='FLOZ',bottleVolume=999,bottleTypeBreastMilk=True)
        row=m.little_log_rows('b',r,'dest','author')[0]
        self.assertAlmostEqual(row[4],1.25*29.5735295625)
        self.assertEqual(json.loads(row[-1])['details']['formulaMl'],0)

    def test_growth_splits_measurements_and_sleep_and_milestone(self):
        rows=m.little_log_rows('g',self.record(type='GROW',weightNum=809375,weightExp=5,
            weightUnit='LB',heightNum=200,heightExp=1,heightUnit='IN'),'dest','author')
        self.assertEqual(len(rows),2)
        self.assertNotEqual(rows[0][0],rows[1][0])
        self.assertEqual(json.loads(rows[0][-1])['details'],{'measurement':'Weight','value':8.09375,'unit':'lb'})
        self.assertEqual(m.little_log_rows('s',self.record(type='SLEEP',endDt=1700001000123),'dest','a')[0][3],'sleep')
        self.assertEqual(m.little_log_rows('m',self.record(type='GROW.MILESTONE',milestoneName='Smiles'),'dest','a')[0][3],'milestone')

    def test_invalid_and_unknown_are_not_guessed(self):
        for r in [self.record(type='MEDICAL.VACCINE'),self.record(type='SLEEP',endDt=0),
                self.record(type='FEED',feedType='BREAST'),
                self.record(type='FEED',feedType='BOTTLE',bottleVolumeNum=1,bottleVolumeExp=0),
                self.record(type='DIAPER',diaperTypePee=True,diaperTypePoop=True,diaperPoopTexture='UNKNOWN')]:
            with self.subTest(r=r),self.assertRaises(m.Unmapped):
                m.little_log_rows('r',r,'dest','a')

    def test_destination_identity_and_name_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'export.json'
            path.write_text(json.dumps({'format':'little-log','schemaVersion':4,
                'family':{'id':'exact-id','name':'Family','babyName':'Baby'}}))
            self.assertEqual(m.little_log_destination(path,'baby')['id'],'exact-id')
            with self.assertRaises(m.UserError):m.little_log_destination(path,'Other')
            path.write_text('{}')
            with self.assertRaises(m.UserError):m.little_log_destination(path,'Baby')

    def test_all_babies_deletions_unassociated_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);family=root/'family-01';family.mkdir()
            (family/'children.json').write_text(json.dumps({'baby':{'name':'Baby'},'two':{'name':'Two'}}))
            (family/'activities.json').write_text(json.dumps({'s':self.record(type='SLEEP',endDt=1700001000123),
                'd':self.record(type='SLEEP',deleteDt=1), 'unknown':self.record(type='NEW'),
                'orphan':{'type':'PUMP'}}))
            paths=[]
            for name in ['Baby','Two']:
                path=root/(name+'.json');path.write_text(json.dumps({'format':'little-log','schemaVersion':4,
                    'family':{'id':name+'-destination','name':'Family','babyName':name}}));paths.append(path)
            self.assertEqual(m.export_little_log(root,paths),1)
            report=json.loads((root/'little-log-report.json').read_text())
            self.assertEqual(len(report['children']),2)
            self.assertEqual(report['unassociated_records'],1)
            self.assertEqual(report['children'][0]['deleted_excluded'],1)
            self.assertEqual(report['children'][0]['mapped_source_records'],1)
            self.assertEqual(len(report['children'][0]['unmapped']),1)
            before=(family/'little-log-child-01.csv').read_bytes()
            m.export_little_log(root,paths)
            self.assertEqual(before,(family/'little-log-child-01.csv').read_bytes())

    def test_option_three_no_huckleberry_dependencies_or_credentials(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(sys,'argv',['script','--little-log','--backup-dir',tmp]),patch.object(m,'export_little_log',return_value=0) as convert,patch.object(m,'ensure_migration_dependencies') as setup,patch.object(m,'credentials') as credentials:
            self.assertEqual(m.main(),0)
            setup.assert_not_called();credentials.assert_not_called();convert.assert_called_once()

    def test_limit(self):
        with self.assertRaises(m.UserError):
            m.little_log_csv({'id':'dest','name':'Family','babyName':'Baby'},[['x'*11_000_000]])

if __name__=='__main__':unittest.main()
