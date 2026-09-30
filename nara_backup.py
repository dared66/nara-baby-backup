#!/usr/bin/env python3
"""One-file Nara Baby backup with optional guided Huckleberry migration."""
import argparse
import asyncio
import contextlib
import csv
from datetime import datetime, timezone
from decimal import Decimal
import getpass
import hashlib
import importlib.metadata
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib import request, error, parse
import venv
import warnings
from zoneinfo import ZoneInfo

VERSION = '0.2.0'
HUCKLEBERRY_VERSION = '0.4.7'


def load_migration_dependencies():
    """Load optional packages only when migration is selected; never install here."""
    global aiohttp, HuckleberryAPI, FirebaseDiaperData, FirebaseBottleFeedIntervalData
    global FirebaseBreastFeedIntervalData, FirebaseSleepIntervalData, FirebaseSleepDetails
    global FirebaseGrowthData, to_firebase_dict
    if importlib.metadata.version('huckleberry-api') != HUCKLEBERRY_VERSION:
        raise ImportError('The pinned Huckleberry client is required.')
    import aiohttp
    from huckleberry_api import HuckleberryAPI
    from huckleberry_api.firebase_types import (FirebaseDiaperData, FirebaseBottleFeedIntervalData,
        FirebaseBreastFeedIntervalData, FirebaseSleepIntervalData, FirebaseSleepDetails,
        FirebaseGrowthData, to_firebase_dict)


def relaunch_migration(python):
    argv = [str(python), str(Path(__file__).resolve())] + sys.argv[1:]
    if '--migrate' not in argv:
        argv.append('--migrate')
    os.execv(str(python), argv)


def ensure_migration_dependencies():
    try:
        load_migration_dependencies()
        return
    except (ImportError, importlib.metadata.PackageNotFoundError):
        pass
    environment = Path(__file__).resolve().parent / '.nara-migration-env'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if python.exists():
        probe = subprocess.run([str(python), '-c',
            "import importlib.metadata, aiohttp, huckleberry_api; assert importlib.metadata.version('huckleberry-api') == '0.4.7'"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if probe.returncode == 0:
            relaunch_migration(python)
            return
    print('Option 2 needs huckleberry-api==' + HUCKLEBERRY_VERSION + ' and its dependencies.')
    print('They will be installed from PyPI into .nara-migration-env beside this script.')
    print('No credentials have been requested, and system Python will not be changed.')
    if input('Install the optional migration dependencies? [y/N] ').strip().lower() != 'y':
        raise UserError('Migration setup canceled. Choose option 1 for a dependency-free backup.')
    if not python.exists():
        venv.create(environment, with_pip=True)
    result = subprocess.run([str(python), '-m', 'pip', '--disable-pip-version-check',
                             'install', 'huckleberry-api==' + HUCKLEBERRY_VERSION], check=False)
    if result.returncode:
        raise UserError('Dependency setup failed. Keep the environment, check your internet connection, and rerun option 2.')
    relaunch_migration(python)


API_KEY = "AIzaSyApsJ5h5-JCjp9SJvWbHG4Fxq8NbxDW0EQ"  # Public Firebase app identifier, not a password.
DB = "https://amazing-ripple-221320.firebaseio.com"
FUNCTION = "https://us-central1-amazing-ripple-221320.cloudfunctions.net/app"


class ExportError(Exception):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self):
        # Credentials go only to Firebase/Nara over verified HTTPS.
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
        self.token = None
        self.uid = None

    def call(self, url, payload=None, bearer=False):
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + self.token
        req = request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        try:
            with self.opener.open(req, timeout=60) as response:
                return json.load(response)
        except error.HTTPError as exc:
            try:
                exc.close()
            except Exception:
                # Cleanup must not mask the fixed, secret-free request error.
                pass
            if exc.code in (401, 403):
                raise ExportError("Login expired, incorrect login, or access denied (HTTP %s)." % exc.code) from None
            raise ExportError("Nara request failed (HTTP %s). Try again later." % exc.code) from None
        except (error.URLError, TimeoutError, OSError):
            raise ExportError("Could not connect. Check your internet connection and try again.") from None
        except (ValueError, UnicodeError):
            raise ExportError("Nara returned an unexpected response. The service may have changed.") from None

    def login(self, email, password):
        data = self.call("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + API_KEY,
                         {"email": email, "password": password, "returnSecureToken": True})
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k] for k in ("idToken", "localId")):
            raise ExportError("Login did not return a valid session.")
        self.token, self.uid = data["idToken"], data["localId"]

    def get(self, path):
        return self.call(DB + path + ".json?" + parse.urlencode({"auth": self.token}))

    def sync(self, family):
        return self.call(FUNCTION, {"data": {"action": "/family/trackz/sync2", "familyKey": family, "prevSyncKey": None}}, bearer=True)


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ExportError("Nara returned an invalid identifier.")
    return value


def mapping(value, label, allow_null=False):
    if value is None and allow_null:
        return {}
    if not isinstance(value, dict) or "error" in value:
        raise ExportError("Unexpected %s response; this is not an empty export." % label)
    return value


def tracks_from(payload):
    result = mapping(mapping(payload, "sync").get("result"), "sync result")
    data = result if "trackz" in result else result.get("data")
    if not isinstance(data, dict) or "trackz" not in data:
        raise ExportError("Activity sync is missing history; this is not an empty export.")
    tracks = mapping(data["trackz"], "activities", allow_null=True)
    if any(not isinstance(v, dict) for v in tracks.values()):
        raise ExportError("Unexpected activity record format.")
    return tracks


def save_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    path.chmod(0o600)


def csv_value(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    # Prevent notes/names from becoming formulas when opened in a spreadsheet.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def iso_ms(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


def save_csv(path, tracks, children):
    extra = ["export_record_id", "export_child_name", "export_begin_utc", "export_end_utc"]
    fields = extra + sorted({field for track in tracks.values() for field in track} - set(extra))
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record_id, track in tracks.items():
            child = children.get(track.get("childKey"))
            row = dict(track)
            row.update(export_record_id=record_id,
                       export_child_name=child.get("name", "") if isinstance(child, dict) else "",
                       export_begin_utc=iso_ms(track.get("beginDt")), export_end_utc=iso_ms(track.get("endDt")))
            writer.writerow({k: csv_value(v) for k, v in row.items()})
    path.chmod(0o600)


def export(client, folder):
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {"exported_at_utc": datetime.now(timezone.utc).isoformat(), "complete": False,
              "scope": "Accessible account/family database snapshots and full-reset activity sync; not a verified exhaustive server backup.",
              "families": [], "errors": []}
    try:
        memberships = mapping(client.get("/userz/%s/familyKeyz" % key(client.uid)), "family membership", allow_null=True)
        save_json(folder / "family-memberships.json", memberships)
        try:
            save_json(folder / "account.json", client.get("/userz/%s" % key(client.uid)))
        except ExportError as exc:
            report["errors"].append("Account snapshot: " + str(exc))
        for index, family in enumerate(memberships, 1):
            family_dir = folder / ("family-%02d" % index)
            family_dir.mkdir(mode=0o700)
            item = {"folder": family_dir.name, "family_key": family, "activities": None}
            report["families"].append(item)
            try:
                family = key(family)
                try:
                    save_json(family_dir / "family-snapshot.json", client.get("/familyz/" + family))
                except ExportError as exc:
                    report["errors"].append(family_dir.name + " database snapshot: " + str(exc))
                children = {}
                try:
                    children = mapping(client.get("/familyz/" + family + "/childz"), "children", allow_null=True)
                    if any(not isinstance(v, dict) for v in children.values()):
                        raise ExportError("Unexpected child profile format.")
                    save_json(family_dir / "children.json", children)
                except ExportError as exc:
                    report["errors"].append(family_dir.name + " child profiles: " + str(exc))
                    children = {}
                payload = client.sync(family)
                # Save original sync even when parsing fails, for future recovery.
                save_json(family_dir / "activity-sync.json", payload)
                tracks = tracks_from(payload)
                save_json(family_dir / "activities.json", tracks)
                save_csv(family_dir / "activities.csv", tracks, children)
                item["activities"] = len(tracks)
                print("Family %d: saved %d activities and %d child profiles." % (index, len(tracks), len(children)))
            except ExportError as exc:
                report["errors"].append(family_dir.name + ": " + str(exc))
        report["complete"] = not report["errors"]
    except ExportError as exc:
        report["errors"].append(str(exc))
    finally:
        save_json(folder / "export-report.json", report)
    return report



class Unmapped(Exception):pass


def number(record,prefix):
    if prefix+'Num' not in record or prefix+'Exp' not in record:
        raise Unmapped('Missing numeric value or exponent: '+prefix)
    num=record[prefix+'Num']; exp=record[prefix+'Exp']
    if isinstance(num,bool) or not isinstance(num,(int,float)) or not math.isfinite(num) or num<0 or isinstance(exp,bool) or not isinstance(exp,int) or not 0<=exp<=8:
        raise Unmapped('Unexpected numeric encoding: '+prefix)
    return float(Decimal(str(num))/(Decimal(10)**exp))


def convert(record):
    r=record
    if not isinstance(r.get('beginDt'),(int,float)) or not r.get('tz'):
        raise Unmapped('Missing event timestamp/timezone')
    start=r['beginDt']/1000
    dt=datetime.fromtimestamp(start,timezone.utc)
    zone=ZoneInfo(r['tz'])
    offset=-dt.astimezone(zone).utcoffset().total_seconds()/60
    kw={'start':start,'offset':offset,'lastUpdated':time.time()}
    notes=[r['note']] if r.get('note') else []
    typ=r['type']
    if typ=='DIAPER':
        pee=bool(r.get('diaperTypePee'));poo=bool(r.get('diaperTypePoop'));dry=bool(r.get('diaperTypeDry'))
        if not (pee or poo or dry):raise Unmapped('Diaper contents not specified')
        mode='both' if pee and poo else 'pee' if pee else 'poo' if poo else 'dry'
        if dry and (pee or poo):notes.append('Nara also marked this diaper dry.')
        if r.get('diaperPoopBlowout'):notes.append('Nara: blowout.')
        texture=r.get('diaperPoopTexture')
        consistency={'RUN':'runny','MUCOUS':'mucousy','PEBBLE':'pebbles','SOLID':'solid'}.get(texture)
        if texture:notes.append('Original Nara stool texture: '+texture)
        color=r.get('diaperPoopColor')
        if color and color.lower() not in ['yellow','brown','black','green','red','gray']:
            notes.append('Original Nara stool color: '+color);color=None
        model=FirebaseDiaperData(**kw,mode=mode,diaperRash=True if r.get('diaperTypeRash') else None,
                                color=color.lower() if color else None,consistency=consistency,notes='\n'.join(notes) or None)
        return 'diaper','intervals',to_firebase_dict(model)
    if typ=='FEED':
        ft=r.get('feedType')
        if ft=='BREAST':
            left=r.get('breastLeftDuration');right=r.get('breastRightDuration')
            if left is None and right is None:raise Unmapped('Nursing record has no recorded duration')
            if any(v is not None and (not isinstance(v,(int,float)) or v<0) for v in [left,right]):raise Unmapped('Invalid nursing duration')
            last=r.get('breastEndSide')
            if last not in ['LEFT','RIGHT','LEFT.nonTimer','RIGHT.nonTimer']:raise Unmapped('Unknown nursing side')
            if '.nonTimer' in last:notes.append('Nara: manually logged nursing.')
            if r.get('breastBeginSide'):notes.append('Nara starting side: '+r['breastBeginSide'])
            model=FirebaseBreastFeedIntervalData(**kw,mode='breast',lastSide=last.split('.')[0].lower(),
                leftDuration=left/1000 if left is not None else None,rightDuration=right/1000 if right is not None else None,
                end_offset=offset,notes='\n'.join(notes) or None)
        elif ft=='BOTTLE':
            unit={'FLOZ':'oz','ML':'ml'}.get(r.get('bottleVolumeUnit'))
            if not unit:raise Unmapped('Bottle entry has no verified volume unit')
            amount=number(r,'bottleVolume')
            bm=bool(r.get('bottleTypeBreastMilk'));formula=bool(r.get('bottleTypeFormula'))
            if bm and formula:
                btype='Other';notes.append('Nara: mixed breast milk and formula.')
            elif bm:btype='Breast Milk'
            elif formula:btype='Formula'
            else:btype='Other';notes.append('Nara did not specify the milk type.')
            model=FirebaseBottleFeedIntervalData(**kw,mode='bottle',bottleType=btype,amount=amount,units=unit,end_offset=offset,notes='\n'.join(notes) or None)
        else:raise Unmapped('Unsupported feeding category')
        return 'feed','intervals',to_firebase_dict(model)
    if typ=='SLEEP':
        if not isinstance(r.get('endDt'),(int,float)) or r['endDt']<r['beginDt']:raise Unmapped('Incomplete sleep record')
        end=r['endDt']/1000
        end_offset=-datetime.fromtimestamp(end,timezone.utc).astimezone(zone).utcoffset().total_seconds()/60
        model=FirebaseSleepIntervalData(**kw,duration=end-start,end_offset=end_offset,details=FirebaseSleepDetails(notes='\n'.join(notes)) if notes else None)
        return 'sleep','intervals',to_firebase_dict(model)
    if typ=='GROW':
        data={}
        for prefix,field,units in [('weight','weight',{'LB':('kg',Decimal('0.45359237')),'KG':('kg',Decimal(1))}),
                                  ('height','height',{'IN':('cm',Decimal('2.54')),'CM':('cm',Decimal(1))}),
                                  ('headSize','head',{'IN':('hcm',Decimal('2.54')),'CM':('hcm',Decimal(1))})]:
            if prefix+'Num' not in r:continue
            unit=r.get(prefix+'Unit')
            if unit not in units:raise Unmapped('Unknown growth unit')
            dest,factor=units[unit]
            data[field]=float(Decimal(str(number(r,prefix)))*factor);data[field+'Units']=dest
        if not data:raise Unmapped('No growth measurement')
        # Metric avoids ambiguous feet/inches and pounds/ounces compound formats.
        model=FirebaseGrowthData(**kw,mode='growth',**data)
        return 'health','data',to_firebase_dict(model)
    raise Unmapped('No verified Huckleberry destination for '+typ)


def equal(payload,saved):
    return all(saved.get(k)==v for k,v in payload.items() if k!='lastUpdated')


def signature(payload):
    # A conservative candidate fingerprint: conflicts are flagged, never overwritten.
    return (payload.get('mode','sleep'),payload.get('start'))




class MigrationError(Exception):
    pass


@contextlib.contextmanager
def quiet():
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            yield
    finally:
        logging.disable(previous)


def save(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    temp.chmod(0o600)
    temp.replace(path)


def prepare(folder):
    groups = []
    for family in sorted(folder.glob('family-*')):
        if not family.is_dir():
            continue
        children_path, tracks_path = family/'children.json', family/'activities.json'
        if not children_path.exists() or not tracks_path.exists():
            raise MigrationError('Backup lacks child profiles or parsed history. Complete the backup before migrating.')
        children = json.loads(children_path.read_text(encoding='utf-8'))
        tracks = json.loads(tracks_path.read_text(encoding='utf-8'))
        for child_id, profile in children.items():
            if not profile.get('name') or not profile.get('birthDate'):
                raise MigrationError('A source child lacks a name or birth date; automatic matching is unsafe.')
            group = {'family':family.name, 'source_child':child_id, 'profile':profile,
                     'records':[], 'unmapped':[], 'photo_references':[], 'deleted_excluded':0}
            for record_id, record in tracks.items():
                if record.get('childKey') != child_id:
                    continue
                if record.get('deleteDt'):
                    group['deleted_excluded'] += 1
                    continue
                if record.get('photo'):
                    group['photo_references'].append({'source_id':record_id, 'photo':record['photo']})
                try:
                    collection, subcollection, payload = convert(record)
                    # Include family and child identity to avoid collisions across families.
                    digest = hashlib.sha256((family.name+':'+child_id+':'+record_id).encode()).hexdigest()[:20]
                    group['records'].append({'source_id':record_id, 'collection':collection,
                        'subcollection':subcollection, 'document':str(record['beginDt'])+'-'+digest, 'payload':payload})
                except Unmapped as exc:
                    group['unmapped'].append({'source_id':record_id, 'reason':str(exc), 'record':record})
            groups.append(group)
    if not groups:
        raise MigrationError('No child histories found in this backup.')
    return groups


async def snapshot(ref):
    result = {}
    async for doc in ref.stream(timeout=60):
        if not doc.exists or not isinstance(doc.to_dict(), dict):
            raise MigrationError('Unexpected destination history response.')
        result[doc.id] = doc.to_dict()
    return result


def entries(data):
    if data.get('multi'):
        if not isinstance(data.get('data'), dict):
            raise MigrationError('Unexpected batched destination history.')
        return list(data['data'].values())
    return [data]


def classify(records, history):
    pending, existing, conflicts = [], [], []
    for record in records:
        saved = history[(record['collection'],record['subcollection'])]
        payload = record['payload']
        if record['document'] in saved:
            (existing if equal(payload,saved[record['document']]) else conflicts).append(record)
            continue
        candidates = [entry for data in saved.values() for entry in entries(data)
                      if signature(entry) == signature(payload)]
        if not candidates:
            pending.append(record)
        elif any(equal(payload, entry) for entry in candidates):
            existing.append(record)
        else:
            conflicts.append(record)
    return pending, existing, conflicts


def match(groups, destination):
    matches = []
    used = set()
    for group in groups:
        profile = group['profile']
        candidates = [child for child in destination if child['name'].strip().casefold() == profile['name'].strip().casefold()
                      and child['birthdate'] == profile['birthDate']]
        if len(candidates) != 1 or candidates[0]['id'] in used:
            raise MigrationError('Cannot uniquely match %s by name and birth date. Create/check its profile in Huckleberry first.' % profile['name'])
        used.add(candidates[0]['id'])
        matches.append((group,candidates[0]))
    return matches


async def run_migration(folder, groups, email, password, confirm, progress=print):
    api = None
    report = {'all_supported_records_verified':False, 'everything_transferred':False,
              'app_display_verified':False, 'children':[]}
    with quiet():
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30),trust_env=False) as session:
            api = HuckleberryAPI(email,password,'UTC',session)
            email = password = None
            try:
                await api.authenticate()
                user = await asyncio.wait_for(api.get_user(),30)
                if user is None:
                    raise MigrationError('Huckleberry account profile is missing.')
                destination = []
                for ref in user.childList:
                    child = await asyncio.wait_for(api.get_child(ref.cid),30)
                    if child is None:
                        raise MigrationError('Huckleberry child profile is missing.')
                    destination.append({'id':ref.cid,'name':child.childsName or ref.nickname or '', 'birthdate':child.birthdate})
                matches = match(groups,destination)
                db = await api._get_firestore_client()
                prepared = []
                for group,child in matches:
                    locations = {(r['collection'],r['subcollection']): db.collection(r['collection']).document(child['id']).collection(r['subcollection']) for r in group['records']}
                    before = {key:await snapshot(ref) for key,ref in locations.items()}
                    pending,existing,conflicts = classify(group['records'],before)
                    prepared.append((group,child,locations,before,pending,existing,conflicts))
                preview = [{'name':g['profile']['name'],'new_records':len(p),'already_present':len(e),
                            'conflicting_records':len(c),'unmapped_records':len(g['unmapped']),
                            'photo_files_not_transferred':len(g['photo_references'])}
                           for g,_,_,_,p,e,c in prepared]
                # Restore output only for the preview/confirmation callback, never library logging.
                with contextlib.redirect_stdout(__import__('sys').__stdout__), contextlib.redirect_stderr(__import__('sys').__stderr__):
                    approved = confirm(preview)
                if not approved:
                    return {'canceled':True,'children':preview}
                for group,child,locations,before,pending,existing,conflicts in prepared:
                    name = group['profile']['name']
                    child_report = {'name':name,'source_child':group['source_child'],'supported_records':len(group['records']),
                        'already_present':len(existing),'created':0,'verified':0,'conflicts':[r['source_id'] for r in conflicts],
                        'unmapped':group['unmapped'],'photo_references_without_files':group['photo_references'],
                        'deleted_excluded':group['deleted_excluded'],'status':'running'}
                    report['children'].append(child_report)
                    # Persist intended IDs before submission, including uncertain batches.
                    save(folder/'migration-journal.json',{'child':name,'destination_child':child['id'],'pending':pending})
                    try:
                        for start in range(0,len(pending),100):
                            chunk = pending[start:start+100]
                            batch = db.batch()
                            refs = []
                            for rec in chunk:
                                ref = locations[(rec['collection'],rec['subcollection'])].document(rec['document'])
                                refs.append(ref)
                                batch.create(ref,rec['payload'])
                            await batch.commit(timeout=45,retry=None)
                            fresh = {}
                            async for doc in db.get_all(refs,timeout=45):
                                fresh[doc.id] = doc.to_dict() if doc.exists else None
                            if any(fresh.get(r['document']) is None or not equal(r['payload'],fresh[r['document']]) for r in chunk):
                                raise MigrationError('Batch readback mismatch.')
                            child_report['created'] += len(chunk)
                            save(folder/'migration-report.json',report)
                            with contextlib.redirect_stdout(__import__('sys').__stdout__):
                                progress('%s: verified %d of %d new records.' % (name,child_report['created'],len(pending)))
                    except Exception:
                        child_report['status'] = 'submission_or_readback_failed'
                    # Verify actual state even if submission response was lost; no blind retries.
                    after = {key:await snapshot(ref) for key,ref in locations.items()}
                    child_report['existing_history_unchanged'] = all(after[key].get(doc_id)==data for key,docs in before.items() for doc_id,data in docs.items())
                    _, verified, post_conflicts = classify(group['records'],after)
                    child_report['verified'] = len(verified)
                    child_report['status'] = ('supported_records_verified' if len(verified)==len(group['records']) and child_report['existing_history_unchanged'] else 'incomplete')
                    save(folder/'migration-report.json',report)
                    if child_report['status'] != 'supported_records_verified':
                        break
                report['all_supported_records_verified'] = len(report['children'])==len(groups) and all(c['status']=='supported_records_verified' for c in report['children'])
                # Unknown server coverage/photos/profile settings prohibit an exhaustive claim.
                save(folder/'migration-report.json',report)
                return report
            finally:
                if api is not None:
                    api.email=api.password=api.id_token=api.refresh_token=None
                    if api._firestore_client is not None:
                        api._firestore_client.close()


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
    do_migrate = args.migrate or args.backup_dir is not None
    if not args.backup_only and not do_migrate:
        print('1. Back up Nara Baby only\n2. Back up Nara Baby and migrate to Huckleberry')
        choice = input('Choose 1 or 2: ').strip()
        if choice not in ('1','2'):
            raise UserError('Choose 1 or 2.')
        do_migrate = choice == '2'
    if do_migrate:
        if sys.version_info < (3,14):
            raise UserError('Huckleberry migration requires Python 3.14 or newer. Backup-only works with Python 3.9+.')
        ensure_migration_dependencies()
    folder = args.backup_dir
    if folder is None:
        folder = args.output or Path('nara-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        client = Client()
        email,password = credentials('Nara')
        try:
            client.login(email,password)
            email=password=None
            report = export(client,folder)
        finally:
            email=password=None
            client.token=client.uid=None
        print('Backup saved to: '+str(folder.resolve()))
        if report['errors']:
            print('Some backup requests failed. Details are in export-report.json.')
        if not do_migrate:
            print('Compare with official app exports before claiming exhaustive coverage.')
            return 1 if report['errors'] else 0
    if not folder.is_dir():
        raise UserError('Backup folder not found.')
    groups = prepare(folder)
    # Keep unmapped original data available even if login or profile matching fails.
    save(folder/'migration-plan.json',{'children':groups})
    email,password = credentials('Huckleberry')
    try:
        result = asyncio.run(run_migration(folder,groups,email,password,confirm))
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
    except (UserError,ExportError) as exc:
        print('Error: '+str(exc),file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # Do not print upstream exceptions/tracebacks: they can include private payloads.
        if exc.__class__.__name__ == 'MigrationError':
            print('Error: '+str(exc),file=sys.stderr)
        else:
            print('Operation stopped. Check connectivity, login, disk access and saved reports. Resume with --backup-dir; do not delete the backup.',file=sys.stderr)
        sys.exit(1)
