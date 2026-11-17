"""Synthetic bounded BOM projection regressions; no network or runtime execution."""
import copy, hashlib, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from component_swap import core,bom_review as br
ROOT=Path(__file__).resolve().parents[1]
class BomTests(unittest.TestCase):
 def setUp(self):
  files={'inventory':'inventory.json','replacements':'declared-match.json','before':'before-bom.json','after':'after-bom.json'}
  self.sources={k:(ROOT/'examples'/v).read_bytes() for k,v in files.items()};self.mapping=json.loads((ROOT/'examples/bom-mapping.json').read_text())
 def run_review(self):
  self.mapping['sha256']={k:br.digest(v) for k,v in self.sources.items()}
  return br.review(self.sources,core.canonical(self.mapping))
 def edit(self,side,fn):
  d=json.loads(self.sources[side]);fn(d);self.sources[side]=core.canonical(d)
 def test_reuses_native_plan_no_generated_constraints(self):
  native,r=self.run_review();self.assertEqual(native,core.plan(self.sources['inventory'],self.sources['replacements']));self.assertEqual(native['proposed_status'],'declared_match');self.assertTrue(r['manual_review_required'])
 def test_ref_renaming_normalized_only_by_mapping(self):
  _,r=self.run_review();index=next(x for x in r['slots'] if x['slot']=='index');self.assertFalse(index['dependency_declarations_changed']);self.assertEqual(index['dependency_comparison']['before'],[{'slot':'embedding'}])
 def test_same_names_do_not_pair_unmapped_components(self):
  self.mapping['slots']=self.mapping['slots'][:1];self.edit('after',lambda d:d['components'][1].update(name='Synthetic embedding'))
  _,r=self.run_review();self.assertIn('index',r['unmapped_native_slots']);self.assertIn('/components/1',r['coverage']['after']['unmapped_component_paths'])
 def test_missing_graph_unknown_explicit_empty_known(self):
  p=br.projection(self.sources['before']);a=next(n for n in p['components'] if n['bom_ref']=='old-embedding');data=next(n for n in p['components'] if n['type']=='data');self.assertEqual(a['dependency_state'],'declared_empty');self.assertEqual(data['dependency_state'],'unknown_no_graph_record')
 def test_missing_dependsOn_is_unknown_and_provides_not_edge(self):
  self.edit('before',lambda d:d['dependencies'][0].update(provides=['old-index']))
  self.edit('before',lambda d:d['dependencies'][0].pop('dependsOn'))
  p=br.projection(self.sources['before']);a=next(n for n in p['components'] if n['bom_ref']=='old-embedding');self.assertEqual(a['dependency_state'],'unknown_dependsOn_absent');self.assertEqual(a['depends_on'],[]);self.assertIn('/dependencies/0/provides',p['unhandled_field_paths'])
 def test_assembly_not_dependency(self):
  p=br.projection(self.sources['before']);self.assertTrue(p['assemblies']);a=next(n for n in p['components'] if n['bom_ref']=='old-embedding');self.assertEqual(a['depends_on'],[])
 def test_license_expression_raw_ack_and_no_inheritance(self):
  p=br.projection(self.sources['before']);a=next(n for n in p['components'] if n['bom_ref']=='old-embedding');self.assertEqual(a['licenses']['raw'],[{'expression':'Apache-2.0 AND (MIT OR GPL-2.0-only)','acknowledgement':'declared'}]);i=next(n for n in p['components'] if n['bom_ref']=='old-index');self.assertEqual(i['licenses']['state'],'missing')
 def test_license_empty_not_no_obligations(self):
  self.edit('before',lambda d:d['components'][1].update(licenses=[]));p=br.projection(self.sources['before']);self.assertEqual(next(n for n in p['components'] if n['bom_ref']=='old-index')['licenses']['state'],'empty_unspecified')
 def test_model_data_presence_not_semantics(self):
  p=br.projection(self.sources['before']);a=next(n for n in p['components'] if n['bom_ref']=='old-embedding');self.assertTrue(a['modelCard']['present']);self.assertEqual(a['modelCard']['sha256'],br.digest(core.canonical({})));self.assertFalse(a['data']['present'])
 def test_unmapped_consumer_in_reverse_impact(self):
  _,r=self.run_review();self.assertIn('/metadata/component',r['coverage']['before']['potential_impact_from_review_seeds'])
 def test_unresolved_service_dependency_and_top_coverage(self):
  p=br.projection(self.sources['before']);self.assertIn('/services',p['unhandled_field_paths']);a=next(n for n in p['components'] if n['bom_ref']=='old-answer-service');self.assertEqual(a['unresolved_dependencies'],['remote-service']);self.assertTrue(p['dependency_coverage_unknown'])
 def test_all_four_binding_checks(self):
  for k in self.sources:
   s={**self.sources,k:self.sources[k]+b' '}
   with self.assertRaises(core.Invalid):br.review(s,core.canonical(self.mapping))
 def test_invalid_mapping_duplicate_slot_ref_and_missing_ref(self):
  for mutator in [lambda m:m['slots'].append(m['slots'][0]),lambda m:m['slots'][1].update(before_ref='old-embedding'),lambda m:m['slots'][0].update(slot='absent'),lambda m:m['slots'][0].update(after_ref='absent')]:
   m=copy.deepcopy(self.mapping);mutator(m)
   with self.assertRaises(core.Invalid):br.review(self.sources,core.canonical(m))
 def test_null_mapping_preserves_missing_evidence(self):
  self.mapping['slots'][0]['after_ref']=None;_,r=self.run_review();self.assertIsNone(r['slots'][0]['after']);self.assertTrue(r['slots'][0]['bom_component_evidence_changed'])
 def test_duplicate_component_refs_and_bad_refs(self):
  for bad in ['old-embedding',None,False,'line\nbreak']:
   d=json.loads(self.sources['before']);d['components'][1]['bom-ref']=bad
   with self.assertRaises(core.Invalid):br.projection(core.canonical(d))
 def test_missing_component_ref_retained_as_unmapped_path(self):
  self.edit('before',lambda d:d['components'][0]['components'][0].pop('bom-ref'));_,r=self.run_review();self.assertIn('/components/0/components/0',r['coverage']['before']['unmapped_component_paths'])
 def test_bad_graph_and_bounds(self):
  for mutate in [lambda d:d['dependencies'].append(d['dependencies'][0]),lambda d:d['dependencies'][0].update(dependsOn=['old-index','old-index']),lambda d:d['dependencies'][0].update(dependsOn=None),lambda d:d.update(components=[{'type':'library','name':'x'}]*101)]:
   d=json.loads(self.sources['before']);mutate(d)
   with self.assertRaises(core.Invalid):br.projection(core.canonical(d))
 def test_unknown_fields_and_finite_floats_preserved(self):
  self.edit('before',lambda d:d.update(custom={'confidence':0.25}));p=br.projection(self.sources['before']);self.assertIn('/custom',p['unhandled_field_paths']);self.assertEqual(br.parse_bom(self.sources['before'])['custom']['confidence'],0.25)
 def test_nonfinite_duplicate_badunicode_rejected(self):
  for raw in [b'{"bomFormat":"CycloneDX","specVersion":"1.6","x":NaN}',b'{"bomFormat":"CycloneDX","specVersion":"1.6","x":1e999}',b'{"bomFormat":"CycloneDX","specVersion":"1.6","x":"\\ud800"}',b'{"bomFormat":"CycloneDX","bomFormat":"CycloneDX","specVersion":"1.6"}']:
   with self.assertRaises(core.Invalid):br.parse_bom(raw)
 def test_two_versions_only(self):
  for version in ['1.5',1.6,True,None]:
   d=json.loads(self.sources['before']);d['specVersion']=version
   with self.assertRaises(core.Invalid):br.projection(core.canonical(d))
 def test_output_precheck_no_directory(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'out';paths={k:ROOT/'examples'/v for k,v in {'inventory':'inventory.json','replacements':'declared-match.json','before':'before-bom.json','after':'after-bom.json'}.items()}
   with patch.object(core,'REPORT_LIMIT',1):
    with self.assertRaises(core.Invalid):br.build(paths,ROOT/'examples/bom-mapping.json',p)
   self.assertFalse(p.exists())
 def test_real_cli_bytes_and_every_tamper(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);out=p/'out';cmd=[sys.executable,'-m','component_swap.bom_review'];env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
   files=['inventory.json','declared-match.json','before-bom.json','after-bom.json','bom-mapping.json']
   done=subprocess.run(cmd+['plan']+[str(ROOT/'examples'/f) for f in files]+['--out',str(out)],cwd=ROOT,env=env,capture_output=True);self.assertEqual(done.returncode,0,done.stderr)
   for k,n in br.SOURCE_NAMES.items():self.assertEqual((out/n).read_bytes(),self.sources[k])
   v=subprocess.run(cmd+['verify',str(out)],cwd=ROOT,env=env,capture_output=True);self.assertEqual(v.returncode,0,v.stderr)
   for name in br.BUNDLE_NAMES:
    data=(out/name).read_bytes();(out/name).write_bytes(data+b' ')
    with self.assertRaises(core.Invalid):br.verify(out)
    (out/name).write_bytes(data)
   (out/'extra').write_text('x')
   with self.assertRaises(core.Invalid):br.verify(out)
 def test_unmapped_or_unresolved_not_a_definite_change(self):
  _,r=self.run_review();row=next(x for x in r['slots'] if x['slot']=='answer-service');self.assertIsNone(row['dependency_declarations_changed']);self.assertEqual(row['dependency_comparison']['comparison_status'],'unknown_unmapped_or_unresolved');self.assertFalse(row['dependency_comparison']['known_mapped_edges_changed'])
  self.mapping['slots']=[x for x in self.mapping['slots'] if x['slot']!='embedding'];_,r=self.run_review();row=next(x for x in r['slots'] if x['slot']=='index');self.assertIsNone(row['dependency_declarations_changed'])
 def test_missing_graph_comparison_remains_unknown(self):
  self.edit('after',lambda d:d.update(dependencies=[x for x in d['dependencies'] if x['ref']!='new-index']));_,r=self.run_review();row=next(x for x in r['slots'] if x['slot']=='index');self.assertIsNone(row['dependency_declarations_changed']);self.assertTrue(row['dependency_comparison']['coverage_state_changed'])
 def test_cycle_impact_terminates(self):
  self.edit('before',lambda d:d['dependencies'][0].update(dependsOn=['old-ui']));_,r=self.run_review();self.assertIn('/components/3',r['coverage']['before']['potential_impact_from_review_seeds'])
 def test_component_count_combines_metadata_and_nested(self):
  d={'bomFormat':'CycloneDX','specVersion':'1.7','metadata':{'component':{'type':'application','name':'root'}},'components':[{'type':'library','name':'x'}]*99};self.assertEqual(len(br.projection(core.canonical(d))['components']),100);d['components'].append({'type':'library','name':'extra'})
  with self.assertRaises(core.Invalid):br.projection(core.canonical(d))
 def test_special_files_and_limits(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);big=p/'big';big.write_bytes(b' '*(core.LIMIT+1))
   with self.assertRaises(core.Invalid):core.read(big)
   if hasattr(os,'symlink'):
    sy=p/'sy';sy.symlink_to(big)
    with self.assertRaises(core.Invalid):core.read(sy)
   if hasattr(os,'mkfifo'):
    fifo=p/'fifo';os.mkfifo(fifo)
    with self.assertRaises(core.Invalid):core.read(fifo)
 def test_markdown_escaping_and_unicode(self):
  self.edit('before',lambda d:d['components'][0].update(name='<script>`|😀'));_,r=self.run_review();md=br.markdown(r).decode();self.assertNotIn('<script>',md);self.assertIn('&lt;script&gt;',md);self.assertIn('😀',md)
 def test_explicit_markdown_payloads_in_all_source_fields_are_text(self):
  payload='![tracker](https://example.invalid/pixel?private=sentinel) [link](https://example.invalid/link) **bold** _em_ `code` \\!<img src=x>'
  for field in ('name','license','ref','unhandled','unresolved','native_version'):
   with self.subTest(field=field):
    self.setUp()
    d=json.loads(self.sources['before'])
    if field=='name':d['components'][0]['name']=payload
    elif field=='license':d['components'][0]['licenses']=[{'license':{'name':payload}}]
    elif field=='ref':
     old=d['components'][0]['bom-ref'];d['components'][0]['bom-ref']=payload
     self.mapping['slots'][0]['before_ref']=payload
     for row in d['dependencies']:
      if row['ref']==old:row['ref']=payload
      if 'dependsOn' in row:row['dependsOn']=[payload if x==old else x for x in row['dependsOn']]
    elif field=='unhandled':d[payload]={'retained':True}
    elif field=='unresolved':d['dependencies'].append({'ref':payload,'dependsOn':[]})
    elif field=='native_version':
     native=json.loads(self.sources['inventory']);native['components'][0]['version']=payload
     self.sources['inventory']=core.canonical(native)
    self.sources['before']=core.canonical(d)
    _,r=self.run_review();md=br.markdown(r).decode()
    self.assertNotIn('![tracker]',md);self.assertNotIn('[link](',md);self.assertNotIn('<img',md)
    self.assertNotIn('**bold**',md);self.assertNotIn('_em_',md);self.assertNotIn('`code`',md)
    self.assertIn('&#33;&#91;tracker&#93;&#40;',md)
    self.assertIn('&#91;link&#93;&#40;',md)
    self.assertIn('&#92;',md)
    if field=='unhandled':self.assertIn(payload,json.loads(self.sources['before']))
    else:self.assertIn(payload,json.dumps(r,ensure_ascii=False).replace('\\\\','\\'))
 def test_literal_entity_cannot_reintroduce_markup(self):
  self.edit('before',lambda d:d['components'][0].update(name='&#33;&#91;x&#93;(https://example.invalid)'))
  _,r=self.run_review();md=br.markdown(r).decode()
  self.assertIn('&amp;&#35;33;&amp;&#35;91;x&amp;&#35;93;&#40;',md)
  self.assertNotIn('![x]',md)
if __name__=='__main__':unittest.main()
