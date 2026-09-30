"""Conservative Nara-to-Huckleberry field conversion. No network access."""
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
import time
import math
from huckleberry_api.firebase_types import (FirebaseDiaperData, FirebaseBottleFeedIntervalData,
    FirebaseBreastFeedIntervalData, FirebaseSleepIntervalData, FirebaseSleepDetails,
    FirebaseGrowthData, to_firebase_dict)

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


