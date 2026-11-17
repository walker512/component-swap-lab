"""Declared constraints, not live compatibility certification or deployment."""
import hashlib,json,os,re,stat
from pathlib import Path
LIMIT=2*1024*1024
REPORT_LIMIT=16*1024*1024
class Invalid(ValueError):pass

def read(path,limit=LIMIT):
    try:
        if not stat.S_ISREG(Path(path).lstat().st_mode):raise Invalid('Regular non-symlink input required.')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise Invalid('Input type or size limit exceeded.')
            with os.fdopen(fd,'rb') as f:fd=None;raw=f.read(limit+1)
        finally:
            if fd is not None:os.close(fd)
        if len(raw)>limit:raise Invalid('File size limit exceeded.')
        raw.decode('utf8');return raw
    except (OSError,UnicodeError):raise Invalid('Cannot safely read bounded UTF-8 input.') from None

def parse(raw):
    def pairs(values):
        out={}
        for k,v in values:
            if k in out:raise Invalid('Duplicate JSON keys.')
            k.encode('utf8');out[k]=v
        return out
    def bad(value):raise Invalid('Non-finite JSON.')
    try:
        if len(raw)>LIMIT:raise Invalid('JSON exceeds 2 MiB.')
        data=json.loads(raw.decode('utf8'),object_pairs_hook=pairs,parse_constant=bad)
        queue=[(data,0)]
        while queue:
            value,depth=queue.pop()
            if isinstance(value,(list,dict)):
                if depth>=16:raise Invalid('JSON depth limit exceeded.')
                queue.extend((x,depth+1) for x in (value.values() if isinstance(value,dict) else value))
            elif isinstance(value,str):value.encode('utf8')
            elif isinstance(value,float):raise Invalid('Floating-point declarations are unsupported; use explicit integer units.')
        return data
    except (UnicodeError,ValueError,RecursionError):raise Invalid('Invalid JSON input.') from None

def identifier(x):
    if not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',x):raise Invalid('Invalid identifier.')
    return x

def text(x):
    if not isinstance(x,str) or not 1<=len(x)<=200 or x!=x.strip() or any(ord(c)<32 for c in x):raise Invalid('Expected bounded plain text.')
    return x

def value(x,unknown=False):
    if x is None and unknown:return x
    if type(x) is bool:return x
    if type(x) is int and abs(x)<=10**12:return x
    if isinstance(x,str):return text(x)
    raise Invalid('Fact values require strings, booleans or bounded integers; null is unknown.')

def components(items):
    if not isinstance(items,list) or not 1<=len(items)<=100:raise Invalid('Expected 1..100 components.')
    out={};edges=0;constraint_count=0
    for item in items:
        if not isinstance(item,dict) or set(item)!={'id','kind','version','facts','requires'}:raise Invalid('Invalid component fields.')
        name=identifier(item['id'])
        if name in out:raise Invalid('Duplicate component ID.')
        if not isinstance(item['kind'],str) or item['kind'] not in {'model','embedding','vector-store','orchestrator','client','other'}:raise Invalid('Unknown component kind.')
        text(item['version'])
        if not isinstance(item['facts'],dict) or len(item['facts'])>30:raise Invalid('At most 30 facts per component.')
        for k,v in item['facts'].items():identifier(k);value(v,True)
        if not isinstance(item['requires'],list) or len(item['requires'])>30:raise Invalid('At most 30 dependency declarations per component.')
        seen=set()
        for edge in item['requires']:
            if not isinstance(edge,dict) or set(edge)!={'provider','constraints'}:raise Invalid('Invalid dependency fields.')
            provider=identifier(edge['provider'])
            if provider==name or provider in seen:raise Invalid('Self or duplicate dependency declaration.')
            seen.add(provider);edges+=1
            if edges>500:raise Invalid('At most 500 dependency edges.')
            rules=edge['constraints']
            if not isinstance(rules,dict) or not 1<=len(rules)<=30:raise Invalid('Dependencies need 1..30 explicit constraints.')
            constraint_count+=len(rules)
            if constraint_count>500:raise Invalid('At most 500 individual constraints.')
            for k,v in rules.items():identifier(k);value(v)
        out[name]=item
    return out

def validate_graph(nodes):
    for node in nodes.values():
        for edge in node['requires']:
            if edge['provider'] not in nodes:raise Invalid('Dependency references a missing component.')

def load_inventory(raw):
    data=parse(raw)
    if not isinstance(data,dict) or set(data)!={'schema','components'} or type(data['schema']) is not int or data['schema']!=1:raise Invalid('Expected inventory schema 1.')
    nodes=components(data['components']);validate_graph(nodes);return nodes

def checks(nodes):
    out={}
    for consumer in sorted(nodes):
        for edge in sorted(nodes[consumer]['requires'],key=lambda x:x['provider']):
            provider=edge['provider'];facts=nodes[provider]['facts']
            for key,required in sorted(edge['constraints'].items()):
                observed=facts.get(key)
                status='unknown' if observed is None else ('declared_match' if type(observed) is type(required) and observed==required else 'mismatch')
                out[(consumer,provider,key)]={'consumer':consumer,'provider':provider,'fact':key,'required':required,'declared':observed,'status':status}
    return out

def overall(rows):
    statuses={r['status'] for r in rows}
    if not statuses:return 'no_constraints'
    return 'mismatch' if 'mismatch' in statuses else 'unknown' if 'unknown' in statuses else 'declared_match'

def affected(nodes,changed):
    result=set(changed)
    while True:
        found={name for name,item in nodes.items() if any(e['provider'] in result for e in item['requires'])}
        new=result|found
        if new==result:return result
        result=new

def plan(inventory_bytes,replacement_bytes):
    before=load_inventory(inventory_bytes);data=parse(replacement_bytes)
    if not isinstance(data,dict) or set(data)!={'schema','replacements'} or type(data['schema']) is not int or data['schema']!=1:raise Invalid('Expected replacement schema 1.')
    replacements=components(data['replacements'])
    if not set(replacements)<=set(before):raise Invalid('Replacement IDs must name existing stable component slots.')
    after=components(list({**before,**replacements}.values()));validate_graph(after)
    changed=sorted(k for k in replacements if canonical(before[k])!=canonical(replacements[k]))
    old,new=checks(before),checks(after);rows=[]
    for key in sorted(set(old)|set(new)):
        a,b=old.get(key),new.get(key)
        if a is None:change='added_constraint'
        elif b is None:change='removed_constraint'
        elif canonical(a)==canonical(b):change='unchanged'
        elif a['required']!=b['required'] or type(a['required']) is not type(b['required']):change='changed_requirement'
        elif a['status']=='declared_match' and b['status']!='declared_match':change='regressed'
        elif a['status']!='declared_match' and b['status']=='declared_match':change='resolved_in_declarations'
        else:change='changed_evidence_or_status'
        rows.append({'consumer':key[0],'provider':key[1],'fact':key[2],'before':a,'after':b,'change':change})
    impacts=sorted(affected(before,changed)|affected(after,changed))
    notes=['All facts and dependency constraints are user declarations, not observations authenticated by this tool.','A declared match is not actual API, semantic, latency, data-migration or deployment compatibility.','Exact typed equality only: no semantic version ranges, unit conversion or schema inference.','Impact is conservative reverse dependency reachability, not a prediction of runtime failure. Cycles are permitted; no execution order is inferred.','Removed or weakened requirements require human review even if the proposed status becomes declared_match.','This plan does not execute changes or prove that rollback can restore stateful data.','The bundle includes complete supplied inventories; identifiers, versions and facts may be sensitive.']
    return {'schema':1,'input_sha256':{'inventory':hashlib.sha256(inventory_bytes).hexdigest(),'replacements':hashlib.sha256(replacement_bytes).hexdigest()},'changed_components':changed,'affected_components':impacts,'baseline_status':overall(old.values()),'proposed_status':overall(new.values()),'constraint_changes':rows,'manual_review_required':True,'handoff_checklist':['Verify each changed component against real integration/conformance tests before deployment.','Review every unknown, mismatch, changed or removed requirement; confirm inventory completeness.','For stateful components, separately test backups, data migration and restoration; this tool does none of them.','Confirm canary, owner, monitoring and abort criteria outside this plan.'],'limits':notes}

def canonical(data):return (json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf8')
def markdown(report):
    # JSON code blocks are escaped to prevent attacker-controlled fence closures.
    safe=json.dumps(report,ensure_ascii=False,indent=2).replace('`','\\u0060').replace('<','\\u003c').replace('>','\\u003e')
    return ('# Component Swap Lab review\n\nDeclared constraints only. No deployment or observed compatibility certification.\n\nBaseline: '+report['baseline_status']+'\n\nProposed: '+report['proposed_status']+'\n\nManual review is always required. Compare before/after rows; a pre-existing mismatch is not automatically caused by this proposal.\n\n```json\n'+safe+'\n```\n').encode('utf8')
def build(inventory,replacements,out):
    raws=[read(inventory),read(replacements)];report=plan(*raws)
    # Serialize and bound every output before creating the destination.
    outputs=dict(zip(('inventory.json','replacements.json'),raws))
    outputs.update({'report.json':canonical(report),'review.md':markdown(report)})
    if any(len(outputs[name])>REPORT_LIMIT for name in ('report.json','review.md')):
        raise Invalid('Generated report size limit exceeded.')
    path=Path(out);path.mkdir(exist_ok=False)
    for name,data in outputs.items():(path/name).write_bytes(data)
    return report

def verify(folder):
    root=Path(folder)
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()}!={'inventory.json','replacements.json','report.json','review.md'}:raise Invalid('Unexpected bundle structure.')
    report=plan(read(root/'inventory.json'),read(root/'replacements.json'))
    if read(root/'report.json',REPORT_LIMIT)!=canonical(report) or read(root/'review.md',REPORT_LIMIT)!=markdown(report):raise Invalid('Bundle differs from deterministic recomputation.')
    return {'verified':True,'proposed_status':report['proposed_status'],'manual_review_required':True,'note':'Internal consistency, not authenticity or observed compatibility.'}
