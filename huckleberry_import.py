"""Optional Huckleberry migration, with preview, create-only writes and readback."""
import asyncio
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path

import aiohttp
from huckleberry_api import HuckleberryAPI
from migration_fields import Unmapped, convert, equal, signature


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


async def migrate(folder, groups, email, password, confirm, progress=print):
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
