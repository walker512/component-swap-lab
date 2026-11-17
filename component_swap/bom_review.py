"""Bounded CycloneDX projection bound to an unchanged native replacement plan."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from . import core

SOURCE_NAMES={'inventory':'inventory.json','replacements':'replacements.json','before':'before-bom.json','after':'after-bom.json'}
BUNDLE_NAMES=set(SOURCE_NAMES.values())|{'mapping.json','native-plan.json','bom-review.json','review.md'}

def digest(raw):return hashlib.sha256(raw).hexdigest()
def fail(message='Unsupported or malformed bounded BOM projection.'):
    raise core.Invalid(message)
def exact(obj,keys):
    if not isinstance(obj,dict) or set(obj)!=set(keys):fail()
def string(value):
    if not isinstance(value,str) or not 1<=len(value)<=1024 or any(ord(c)<32 for c in value):fail()
    return value

def parse_bom(raw):
    def pairs(entries):
        out={}
        for k,v in entries:
            if k in out:fail('Duplicate JSON key.')
            k.encode('utf8');out[k]=v
        return out
    def bad(value):fail('Non-finite JSON number.')
    try:
        if len(raw)>core.LIMIT:fail('BOM exceeds 2 MiB.')
        value=json.loads(raw.decode('utf8'),object_pairs_hook=pairs,parse_constant=bad)
        pending=[(value,0)]
        while pending:
            v,depth=pending.pop()
            if isinstance(v,(dict,list)):
                if depth>=24:fail('BOM depth exceeded.')
                pending.extend((x,depth+1) for x in (v.values() if isinstance(v,dict) else v))
            elif isinstance(v,str):v.encode('utf8')
            elif isinstance(v,float) and not math.isfinite(v):fail('Non-finite number.')
        if not isinstance(value,dict) or value.get('bomFormat')!='CycloneDX' or value.get('specVersion') not in ('1.6','1.7'):fail('Only CycloneDX JSON 1.6/1.7 projections supported.')
        return value
    except (UnicodeError,ValueError,RecursionError):fail('Invalid bounded BOM JSON.')

def pointer(key):return key.replace('~','~0').replace('/','~1')
def projection(raw):
    bom=parse_bom(raw);nodes=[];refs={};unhandled=[];assemblies=[]
    def skipped(obj,handled,path):
        unhandled.extend(path+'/'+pointer(k) for k in sorted(obj) if k not in handled)
    def visit(obj,path,parent=None):
        if not isinstance(obj,dict) or len(nodes)>=100:fail('At most 100 projected components.')
        ref=obj.get('bom-ref')
        if 'bom-ref' in obj and ref is None:fail('Null component bom-ref.')
        if ref is not None:
            string(ref)
            if ref in refs:fail('Duplicate consumed component bom-ref.')
            refs[ref]=path
        for k in ('type','name'):
            if k not in obj:fail('Component type/name required in projection.')
            string(obj[k])
        if 'version' in obj:string(obj['version'])
        if 'licenses' in obj and not isinstance(obj['licenses'],list):fail('Licenses must be an array; full license grammar is not validated.')
        licenses={'state':'missing' if 'licenses' not in obj else 'empty_unspecified' if not obj['licenses'] else 'supplied_uninterpreted','path':path+'/licenses','raw':obj.get('licenses')}
        opaque={}
        for key in ('modelCard','data'):
            opaque[key]={'present':key in obj,'path':path+'/'+key,'sha256':digest(core.canonical(obj[key])) if key in obj else None,'semantics':'uninterpreted; no training-data license inference'}
        node={'path':path,'bom_ref':ref,'type':obj['type'],'name':obj['name'],'version':obj.get('version'),'licenses':licenses,**opaque,'dependency_state':'unknown_no_graph_record','depends_on':[],'unresolved_dependencies':[]}
        nodes.append(node)
        if parent is not None:assemblies.append({'parent':parent,'child':path,'semantics':'assembly_not_dependency'})
        skipped(obj,{'bom-ref','type','name','version','licenses','modelCard','data','components'},path)
        if 'components' in obj:
            if not isinstance(obj['components'],list):fail()
            for i,child in enumerate(obj['components']):visit(child,path+'/components/'+str(i),path)
    if 'metadata' in bom:
        if not isinstance(bom['metadata'],dict):fail()
        if 'component' in bom['metadata']:visit(bom['metadata']['component'],'/metadata/component')
        skipped(bom['metadata'],{'component'},'/metadata')
    if 'components' in bom:
        if not isinstance(bom['components'],list):fail()
        for i,obj in enumerate(bom['components']):visit(obj,'/components/'+str(i))
    skipped(bom,{'bomFormat','specVersion','components','metadata','dependencies'},'')
    dependencies=bom.get('dependencies',[])
    if not isinstance(dependencies,list) or len(dependencies)>500:fail('At most 500 dependency records.')
    bypath={n['path']:n for n in nodes};seen=set();unresolved_records=[];edge_count=0
    for i,record in enumerate(dependencies):
        p='/dependencies/'+str(i)
        if not isinstance(record,dict):fail()
        ref=string(record.get('ref'))
        if ref in seen:fail('Ambiguous duplicate dependency record.')
        seen.add(ref);targets=record.get('dependsOn')
        if targets is not None:
            if not isinstance(targets,list):fail()
            for x in targets:string(x)
            if len(set(targets))!=len(targets):fail('Repeated dependency target.')
            edge_count+=len(targets)
            if edge_count>500:fail('At most 500 dependency edges.')
        elif 'dependsOn' in record:fail('Null dependsOn is not an array.')
        skipped(record,{'ref','dependsOn'},p)
        if ref not in refs:
            unresolved_records.append({'path':p,'ref':ref,'depends_on':targets,'reason':'source_not_a_projected_component'});continue
        node=bypath[refs[ref]]
        node['dependency_state']='unknown_dependsOn_absent' if targets is None else 'declared_empty' if not targets else 'declared_edges'
        node['depends_on']=[refs[x] for x in (targets or []) if x in refs]
        node['unresolved_dependencies']=[x for x in (targets or []) if x not in refs]
    return {'spec_version':bom['specVersion'],'components':nodes,'assemblies':assemblies,'unhandled_field_paths':sorted(unhandled),'unresolved_dependency_records':unresolved_records,'dependency_coverage_unknown':bool(unresolved_records) or any(n['dependency_state'].startswith('unknown') or n['unresolved_dependencies'] for n in nodes),'coverage':'Bounded component projection, not full CycloneDX schema validation. Services, provides, external references and unhandled fields are preserved in original bytes, not analyzed. License content is retained but not interpreted; modelCard/data are presence and content-hash evidence only.'}

def reach(proj,seeds):
    found=set(seeds)
    while True:
        expanded=found|{n['path'] for n in proj['components'] if set(n['depends_on'])&found}
        if expanded==found:return sorted(found)
        found=expanded

def review(sources,mapping_raw):
    native=core.plan(sources['inventory'],sources['replacements'])
    inventory=core.load_inventory(sources['inventory']);replacement_data=core.parse(sources['replacements']);after_native={**inventory,**{c['id']:c for c in replacement_data['replacements']}}
    m=core.parse(mapping_raw);exact(m,['schema','sha256','slots'])
    if type(m['schema']) is not int or m['schema']!=1:fail()
    exact(m['sha256'],SOURCE_NAMES)
    if any(m['sha256'][k]!=digest(sources[k]) for k in SOURCE_NAMES):fail('Four-source binding differs.')
    if not isinstance(m['slots'],list) or not 1<=len(m['slots'])<=100:fail('Expected 1..100 explicit slot mappings.')
    projections={k:projection(sources[k]) for k in ('before','after')}
    byref={k:{n['bom_ref']:n for n in p['components'] if n['bom_ref'] is not None} for k,p in projections.items()}
    slotset=set();maps={'before':{},'after':{}};rows=[];seeds={'before':set(),'after':set()}
    for row in m['slots']:
        exact(row,['slot','before_ref','after_ref']);slot=core.identifier(row['slot'])
        if slot not in inventory or slot in slotset:fail('Slot must be unique and exist in native inventory.')
        slotset.add(slot);values={}
        for side in ('before','after'):
            ref=row[side+'_ref']
            if ref is not None:
                string(ref)
                if ref not in byref[side] or ref in maps[side]:fail('Mapped component ref missing or repeated.')
                maps[side][ref]=slot
            values[side]=byref[side].get(ref)
        comparable=lambda n:None if n is None else {k:n[k] if k not in ('licenses','modelCard','data') else n[k]['raw'] if k=='licenses' else {'present':n[k]['present'],'sha256':n[k]['sha256']} for k in ('type','name','version','licenses','modelCard','data')}
        changed=core.canonical(comparable(values['before']))!=core.canonical(comparable(values['after']))
        if changed or slot in native['changed_components']:
            for side in seeds:
                if values[side]:seeds[side].add(values[side]['path'])
        rows.append({'slot':slot,'before_ref':row['before_ref'],'after_ref':row['after_ref'],'before':values['before'],'after':values['after'],'bom_component_evidence_changed':changed,'native_before':{'kind':inventory[slot]['kind'],'version':inventory[slot]['version']},'native_after':{'kind':after_native[slot]['kind'],'version':after_native[slot]['version']},'identity_status':'explicit_human_mapping_not_authenticated','compatibility_status':'not_inferred_from_BOM'})
    def edges(side,node):
        if node is None:return None
        proj=projections[side];bypath={n['path']:n for n in proj['components']};out=[]
        for path in node['depends_on']:
            ref=bypath[path]['bom_ref'];out.append({'slot':maps[side][ref]} if ref in maps[side] else {'unmapped_side':side,'path':path,'ref':ref})
        out.extend({'unresolved_side':side,'ref':r} for r in node['unresolved_dependencies'])
        return sorted(out,key=lambda x:json.dumps(x,sort_keys=True))
    for row in rows:
        e={side:edges(side,row[side]) for side in ('before','after')}
        row['dependency_comparison']={'before':e['before'],'after':e['after'],'correspondence':'Only explicit mapped slots are paired; unmapped/unresolved endpoints remain side-specific.'}
        states={side:(row[side] or {}).get('dependency_state') for side in ('before','after')}
        declared=all(states[side] in ('declared_edges','declared_empty') for side in states)
        unpaired=any(any('slot' not in edge for edge in (e[side] or [])) for side in e)
        known_changed=(core.canonical([x for x in e['before'] if 'slot' in x])!=core.canonical([x for x in e['after'] if 'slot' in x])) if declared else None
        uncertain=not declared or unpaired
        changed=None if uncertain else known_changed
        row['dependency_declarations_changed']=changed
        row['dependency_comparison'].update(comparison_status='unknown_unmapped_or_unresolved' if uncertain else 'compared_explicit_mapped_edges',known_mapped_edges_changed=known_changed,coverage_state_changed=states['before']!=states['after'])
        row['dependency_impact_seed_reason']='unknown_dependency_correspondence_requires_review' if uncertain else 'known_mapped_edges_changed' if changed else None
        if uncertain or changed:
            for side in seeds:
                if row[side]:seeds[side].add(row[side]['path'])
    coverage={}
    for side,proj in projections.items():
        coverage[side]={'unmapped_component_paths':[n['path'] for n in proj['components'] if n['bom_ref'] not in maps[side]],'unknown_dependency_paths':[n['path'] for n in proj['components'] if n['dependency_state'].startswith('unknown')],'potential_impact_from_review_seeds':reach(proj,seeds[side]),'impact_seeds':sorted(seeds[side]),'impact_limit':'Traversal includes all projected components, including unmapped consumers. Unknown or unprojected relationships can hide further impact. Unmapped components are not automatically paired across BOMs.'}
    report={'schema':1,'sha256':{**{k:digest(v) for k,v in sources.items()},'mapping':digest(mapping_raw)},'slots':rows,'unmapped_native_slots':sorted(set(inventory)-slotset),'projections':projections,'coverage':coverage,'manual_review_required':True,'scope':'BOM evidence linked to native declared-constraint plan only. No generated constraints, runtime tests, legal interpretation, remote fetches or deployment. Missing/empty licenses do not mean no obligations. A declared match from the native plan is not BOM-derived compatibility.'}
    return native,report

def markdown(report):
    # Encode explicit Markdown delimiters rather than relying on JSON quotes.
    # Entity expansion is text, not a second Markdown parse. Bare-URL autolinking
    # is renderer-dependent; this is not a general-purpose URL sanitizer.
    def esc(value):
        named={'&':'&amp;','<':'&lt;','>':'&gt;'}
        delimiters=set('\\`|![]()*_{}#+-=~')
        return ''.join(named.get(c, '&#'+str(ord(c))+';' if c in delimiters else c) for c in str(value))
    lines=['# Component Swap Lab: BOM evidence review','',report['scope'],'','**Bounded projection only, not a CycloneDX schema validator.** Read bom-review.json for every component, raw license structure, unhandled path, unknown graph and binding.','No license expression is evaluated. AND / OR / WITH stay as supplied. Component, model, data and BOM-document licenses are not interchangeable.','Complete inventories and BOMs are bundled; review private architecture, names, URLs and license text before sharing.','']
    for row in report['slots']:
        lines+=['## Slot '+esc(row['slot']),'Identity: explicit human mapping, not authenticated. Native kind/version and BOM type/name/version must be reconciled by a human.']
        for side in ('before','after'):
            n=row[side]
            lines.append(side+': '+('explicitly missing' if n is None else esc(json.dumps({'ref':n['bom_ref'],'type':n['type'],'name':n['name'],'version':n['version'],'license_state':n['licenses']['state'],'licenses':n['licenses']['raw'],'dependencies':n['dependency_state']},ensure_ascii=False))))
        lines+=['Native declarations: '+esc(json.dumps({'before':row['native_before'],'after':row['native_after']},ensure_ascii=False)),'BOM evidence changed: '+str(row['bom_component_evidence_changed'])+'; dependency declarations changed: '+str(row['dependency_declarations_changed']),'']
    for side in ('before','after'):
        lines+=['## '+side+' coverage',esc(json.dumps(report['coverage'][side],ensure_ascii=False)), 'Unhandled fields: '+esc(json.dumps(report['projections'][side]['unhandled_field_paths'],ensure_ascii=False)),'Unresolved dependency records: '+esc(json.dumps(report['projections'][side]['unresolved_dependency_records'],ensure_ascii=False)),'']
    lines+=['## Required human checks','Review unmapped identities and unknown dependencies. Confirm each claimed API/model behavior with real integration tests. Review exact license terms and model/data provenance with the responsible reviewer; this tool gives no legal conclusion. Validate migration, rollback and deployment separately.','Hashes and recomputation detect inconsistency, not truthful declarations or coordinated source replacement.','']
    return '\n'.join(lines).encode('utf8')

def generated(sources,mapping):
    native,report=review(sources,mapping)
    files={SOURCE_NAMES[k]:v for k,v in sources.items()};files.update({'mapping.json':mapping,'native-plan.json':core.canonical(native),'bom-review.json':core.canonical(report),'review.md':markdown(report)})
    if any(len(v)>core.REPORT_LIMIT for v in files.values()):fail('Generated report exceeds limit.')
    return files,report

def build(paths,mapping,out):
    files,report=generated({k:core.read(v) for k,v in paths.items()},core.read(mapping));root=Path(out);root.mkdir(exist_ok=False)
    for name,data in files.items():(root/name).write_bytes(data)
    return report

def verify(folder):
    root=Path(folder)
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()}!=BUNDLE_NAMES:fail('Unexpected bundle structure.')
    files,report=generated({k:core.read(root/n) for k,n in SOURCE_NAMES.items()},core.read(root/'mapping.json'))
    if any(core.read(root/n,core.REPORT_LIMIT)!=v for n,v in files.items()):fail('Bundle differs from recomputation.')
    return report

def main():
    p=argparse.ArgumentParser(description='Bind bounded CycloneDX evidence to a native replacement plan without inferring compatibility.')
    sub=p.add_subparsers(dest='command',required=True);a=sub.add_parser('plan')
    for name in SOURCE_NAMES:a.add_argument(name)
    a.add_argument('mapping');a.add_argument('--out',required=True);v=sub.add_parser('verify');v.add_argument('bundle');args=p.parse_args()
    try:
        r=build({k:getattr(args,k) for k in SOURCE_NAMES},args.mapping,args.out) if args.command=='plan' else verify(args.bundle)
        print(json.dumps({'consistent':True,'manual_review_required':True,'mapped_slots':len(r['slots'])}));return 0
    except (core.Invalid,OSError,ValueError,TypeError,RecursionError):
        print('Invalid bounded inputs, binding, projection, bundle or filesystem. Source contents are not echoed.',file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
