"""Version-three meal parsing, isolated from immutable legacy prediction behavior."""
from hashlib import sha256
import json
import re

KEYS=('carbs_g','protein_g','fat_g','fibre_g','energy_kcal')
AMOUNT=re.compile(r'(.*?)\s*(\d+(?:\.\d+)?)\s*(g|ml|kg|pieces?|eggs?|cups?)\s*[.,]?\s*$',re.I)


def key_for_line(english,chinese):
    return sha256(json.dumps([english.strip(),(chinese or '').strip()],ensure_ascii=False).encode()).hexdigest()


def normalize(name):return re.sub(r'\s+',' ',name).strip(' ,;-').lower()


def grams_for(amount,unit,ref,name):
    if unit=='g':return amount,None
    if unit=='kg':return amount*1000,'kg to g'
    portions=ref.get('portions',[])
    if unit=='ml':
        cup=next((p for p in portions if re.fullmatch(r'1 cup(?:, cooked)?',p.get('description','').lower())),None)
        if cup:return amount*cup['gram_weight']/236.5882365,'Reference US cup gram weight / 236.5882365 mL'
        # Explicit food-specific approximations, not a universal mL=g rule.
        if any(x in name for x in ('soup','porridge','congee','coffee','tea','juice','water','beer')):
            return amount,'Assumed prepared aqueous food density 1.0 g/mL; actual solids concentration unknown'
        if any(x in name for x in ('milk','yogurt','latte')):
            return amount*1.03,'Assumed dairy/drink density 1.03 g/mL'
        if name=='cereal':return amount,'Assumed prepared cereal density 1.0 g/mL, not dry cereal'
        if name in ('coke','yellow rice wine','rice wine','syrup','beef and vermicelli',
                    'black sesame and walnut cereal paste','black sesame and walnut paste',
                    'glutinous rice balls in fermented rice wine'):
            return amount,'Assumed prepared beverage/gruel density 1.0 g/mL; recipe concentration and volume displacement uncertain'
        if name=='buckwheat noodles':return amount*140/236.5882365,'Cooked-pasta bulk-volume proxy: USDA 2343841, 140 g per US cup'
        return None,None
    singular={'pieces':'piece','eggs':'egg','cups':'cup'}.get(unit,unit)
    portion=next((p for p in portions if p.get('description','').lower()==f'1 {singular}'),None)
    if portion:return amount*portion['gram_weight'],'Reference serving conversion'
    return None,None


def estimate_meal_v3(payload,catalog):
    raw=payload.get('raw','');alternate=payload.get('alternate_text') or ''
    lines=[x.strip() for x in raw.splitlines() if x.strip()]
    chinese=[x.strip() for x in alternate.splitlines() if x.strip()]
    items=[]
    for i,line in enumerate(lines):
        zh=chinese[i] if len(lines)==len(chinese) else ''
        override=catalog.get('line_overrides',{}).get(key_for_line(line,zh))
        if override and (override['raw'].strip()!=line or (override.get('alternate') or '').strip()!=zh):
            raise ValueError('Food-line override provenance mismatch')
        match=AMOUNT.fullmatch(line)
        name=normalize(match[1]) if match else normalize(line)
        mapping=override.get('mapping') if override else catalog['mappings'].get(name)
        if not mapping:
            reason=catalog.get('unresolved_lines',{}).get(key_for_line(line,zh),{})
            items.append({'raw':line,'food':name,'status':'unmapped_food','alternate':zh,
                'reason':reason.get('reason','No approved mapping'), 'resolution_notes':reason.get('notes',[])});continue
        ref=catalog['references'][mapping['reference']]
        portion=override.get('portion_override') if override else None
        if portion:
            grams=portion['grams'];conversion=portion['provenance']
        elif match:
            grams,conversion=grams_for(float(match[2]),match[3].lower(),ref,name)
        else:grams,conversion=None,None
        if grams is None or grams<=0:
            items.append({'raw':line,'food':name,'status':'unresolved_portion','reference':mapping['reference']});continue
        items.append({'raw':line,'food':override['resolved_description'] if override else name,
            'status':'estimated','grams':grams,'reference':mapping['reference'],'assumed':mapping['assumed'],
            'portion_conversion':bool(conversion),'portion_provenance':conversion,
            'method':mapping.get('preparation','reference_recipe'),'method_source':mapping.get('preparation_evidence'),
            'mapping_note':mapping['note'],'quality_flags':ref.get('quality_flags',[]),
            'nutrients':{k:ref['nutrients_per_100g'][k]*grams/100 for k in KEYS}})
    mapped=[x for x in items if x['status']=='estimated']
    complete=bool(items) and len(mapped)==len(items)
    totals={k:sum(x['nutrients'][k] for x in mapped) for k in KEYS}
    return {'items':items,'mapped_items':len(mapped),'total_items':len(items),'complete':complete,
        'assumed_items':sum(x.get('assumed',False) for x in mapped),
        'portion_conversions':sum(x.get('portion_conversion',False) for x in mapped),
        'nutrients':{k:totals[k] if complete else None for k in KEYS},'known_subtotal':totals}
