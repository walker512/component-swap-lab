"""Original synthetic declarations; no API, model, vendor or deployment calls."""
import copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from component_swap.core import plan,build,verify,Invalid,read,parse,canonical,markdown
ROOT=Path(__file__).resolve().parents[1]
INV=(ROOT/'examples/inventory.json').read_bytes()
BAD=(ROOT/'examples/mismatch.json').read_bytes()
GOOD=(ROOT/'examples/declared-match.json').read_bytes()
UNKNOWN=(ROOT/'examples/unknown.json').read_bytes()
def raw(data):return json.dumps(data).encode()
class SwapTests(unittest.TestCase):
    def test_mismatch_and_transitive_impact(self):
        r=plan(INV,BAD);self.assertEqual(r['baseline_status'],'declared_match');self.assertEqual(r['proposed_status'],'mismatch')
        self.assertEqual(r['changed_components'],['embedding']);self.assertEqual(r['affected_components'],['answer-service','embedding','index','ui'])
        row=next(x for x in r['constraint_changes'] if x['fact']=='vector.dimension');self.assertEqual(row['change'],'regressed')
    def test_unknown_is_not_compatible(self):
        r=plan(INV,UNKNOWN);self.assertEqual(r['proposed_status'],'unknown');self.assertTrue(r['manual_review_required'])
    def test_match_is_only_declared(self):
        r=plan(INV,GOOD);self.assertEqual(r['proposed_status'],'declared_match');self.assertTrue(r['manual_review_required'])
    def test_existing_problem_not_blamed_on_replacement(self):
        data=json.loads(INV);data['components'][1]['requires'][0]['constraints']['api']='different'
        r=plan(raw(data),GOOD);row=next(x for x in r['constraint_changes'] if x['fact']=='api')
        self.assertEqual(row['change'],'unchanged');self.assertEqual(row['before']['status'],'mismatch')
    def test_bool_not_int_and_changed_component_detected(self):
        data=json.loads(INV);data['components'][0]['facts']['vector.dimension']=1
        data['components'][1]['requires'][0]['constraints']['vector.dimension']=1
        replacement=copy.deepcopy(data['components'][0]);replacement['facts']['vector.dimension']=True
        r=plan(raw(data),raw({'schema':1,'replacements':[replacement]}))
        self.assertEqual(r['changed_components'],['embedding']);self.assertEqual(r['proposed_status'],'mismatch')
    def test_typed_requirement_change_not_hidden(self):
        data=json.loads(INV);data['components'][0]['facts']['vector.dimension']=1
        data['components'][1]['requires'][0]['constraints']['vector.dimension']=1
        replacements=copy.deepcopy(data['components'][:2]);replacements[0]['facts']['vector.dimension']=True;replacements[1]['requires'][0]['constraints']['vector.dimension']=True
        r=plan(raw(data),raw({'schema':1,'replacements':replacements}))
        row=next(x for x in r['constraint_changes'] if x['fact']=='vector.dimension');self.assertEqual(row['change'],'changed_requirement')
    def test_removed_requirement_visible(self):
        data=json.loads(INV);replacement=copy.deepcopy(data['components'][1]);replacement['requires']=[]
        r=plan(INV,raw({'schema':1,'replacements':[replacement]}));self.assertIn('removed_constraint',{x['change'] for x in r['constraint_changes']})
    def test_no_constraints_is_not_a_match(self):
        data=json.loads(INV);node=data['components'][0]
        r=plan(raw({'schema':1,'components':[node]}),raw({'schema':1,'replacements':[node]}));self.assertEqual(r['proposed_status'],'no_constraints')
    def test_cycle_terminates_with_conservative_impact(self):
        data=json.loads(INV);data['components'][0]['requires']=[{'provider':'ui','constraints':{'alive':True}}]
        r=plan(raw(data),BAD);self.assertEqual(len(r['affected_components']),4)
    def test_missing_provider_rejected(self):
        data=json.loads(INV);data['components'][1]['requires'][0]['provider']='absent'
        with self.assertRaises(Invalid):plan(raw(data),GOOD)
    def test_new_replacement_id_rejected(self):
        data=json.loads(GOOD);data['replacements'][0]['id']='new-slot'
        with self.assertRaises(Invalid):plan(INV,raw(data))
    def test_duplicate_component_and_edge_rejected(self):
        data=json.loads(INV);data['components'].append(data['components'][0])
        with self.assertRaises(Invalid):plan(raw(data),GOOD)
        data=json.loads(INV);data['components'][1]['requires']*=2
        with self.assertRaises(Invalid):plan(raw(data),GOOD)
    def test_bad_scalar_values(self):
        for value in [1.0,10**500,[],{}]:
            data=json.loads(GOOD);data['replacements'][0]['facts']['vector.dimension']=value
            with self.subTest(value_type=type(value).__name__),self.assertRaises(Invalid):plan(INV,raw(data))
    def test_unknown_null_fact(self):
        data=json.loads(GOOD);data['replacements'][0]['facts']['vector.dimension']=None
        self.assertEqual(plan(INV,raw(data))['proposed_status'],'unknown')
    def test_duplicate_deep_nonfinite_utf16_json(self):
        for data in [b'{"x":1,"x":2}',b'['*20000+b'0'+b']'*20000,b'{"x":1e999}',b'"\\ud800"','{"x":1}'.encode('utf-16-le')]:
            with self.assertRaises(Invalid):parse(data)
    def test_unknown_fields_rejected(self):
        data=json.loads(INV);data['secret']='not allowed'
        with self.assertRaises(Invalid):plan(raw(data),GOOD)
    def test_boolean_schema_rejected(self):
        data=json.loads(INV);data['schema']=True
        with self.assertRaises(Invalid):plan(raw(data),GOOD)
    def test_md_fence_and_html_escape(self):
        data=json.loads(GOOD);data['replacements'][0]['facts']['api']='```<script>synthetic</script>'
        result=markdown(plan(INV,raw(data)));self.assertNotIn(b'<script>',result);self.assertEqual(result.count(b'```'),2)
    def test_bundle_roundtrip_no_text_writes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'bundle';source=Path(d)/'inventory.json';source.write_bytes(INV.replace(b'\n',b'\r\n'))
            with patch.object(Path,'write_text',side_effect=AssertionError('text translation forbidden')):
                r=build(source,ROOT/'examples/mismatch.json',out)
            self.assertEqual((out/'inventory.json').read_bytes(),source.read_bytes());self.assertEqual((out/'report.json').read_bytes(),canonical(r))
            result=verify(out);self.assertTrue(result['verified']);self.assertEqual(result['proposed_status'],'mismatch')
            with self.assertRaises(FileExistsError):build(source,ROOT/'examples/mismatch.json',out)
    def test_bundle_tampering_and_extra(self):
        for name in ['report.json','review.md','inventory.json','extra.txt']:
            with tempfile.TemporaryDirectory() as d:
                out=Path(d)/'bundle';build(ROOT/'examples/inventory.json',ROOT/'examples/mismatch.json',out)
                p=out/name;p.write_bytes((p.read_bytes() if p.exists() else b'')+b'\n')
                with self.assertRaises(Invalid):verify(out)
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'link'
            try:p.symlink_to(ROOT/'examples/inventory.json')
            except OSError:self.skipTest('OS prohibits symlink creation')
            with self.assertRaises(Invalid):read(p)
    @unittest.skipUnless(hasattr(os,'mkfifo'),'POSIX FIFO unavailable')
    def test_fifo_cli_bounded_and_private_error(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'SYNTHETIC_SECRET';os.mkfifo(p)
            result=subprocess.run([sys.executable,'-m','component_swap','plan',str(p),str(p),'--out',str(Path(d)/'out')],cwd=ROOT,capture_output=True,text=True,timeout=2)
            self.assertEqual(result.returncode,2);self.assertNotIn('SYNTHETIC_SECRET',result.stderr);self.assertNotIn('Traceback',result.stderr)
    def test_maximum_constraint_bundle_self_verifies(self):
        nodes=[];requirements=[];remaining=500
        for i in range(17):
            name='p'+str(i)+'x'*75
            facts={('k'+str(j)+'x'*75):'a'*200 for j in range(30)}
            rules=dict(list(facts.items())[:min(remaining,30)]);remaining-=len(rules)
            nodes.append({'id':name,'kind':'other','version':'a'*200,'facts':facts,'requires':[]})
            requirements.append({'provider':name,'constraints':rules})
        nodes.append({'id':'consumer'+'x'*70,'kind':'client','version':'a'*200,'facts':{},'requires':requirements})
        replacement=copy.deepcopy(nodes[0]);replacement['facts']={k:'b'*200 for k in replacement['facts']}
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);inventory=r/'i.json';proposal=r/'p.json'
            inventory.write_bytes(raw({'schema':1,'components':nodes}));proposal.write_bytes(raw({'schema':1,'replacements':[replacement]}))
            build(inventory,proposal,r/'bundle');self.assertTrue(verify(r/'bundle')['verified'])
    def test_escaped_reports_and_disjoint_thousand_row_union(self):
        # 500 checks in each graph; disjoint keys produce 1,000 report rows.
        # All three Markdown-escaped characters expand sixfold, not just '<'.
        for char in '<>`':
            for disjoint in (False, True):
                with self.subTest(char=char, disjoint=disjoint), tempfile.TemporaryDirectory() as d:
                    nodes=[];edges=[];remaining=500
                    for i in range(17):
                        facts={('old'+str(j)+'x'*70):char*200 for j in range(min(remaining,30))}
                        remaining-=len(facts)
                        name='provider'+str(i)+'x'*65
                        nodes.append({'id':name,'kind':'other','version':'v1','facts':facts,'requires':[]})
                        edges.append({'provider':name,'constraints':dict(facts)})
                    consumer={'id':'consumer','kind':'client','version':'v1','facts':{},'requires':edges}
                    nodes.append(consumer)
                    replacements=copy.deepcopy(nodes)
                    if disjoint:
                        for node in replacements:
                            node['facts']={k.replace('old','new'):v for k,v in node['facts'].items()}
                            for edge in node['requires']:
                                edge['constraints']={k.replace('old','new'):v for k,v in edge['constraints'].items()}
                    root=Path(d);i=root/'i';p=root/'p'
                    i.write_bytes(raw({'schema':1,'components':nodes}))
                    p.write_bytes(raw({'schema':1,'replacements':replacements}))
                    report=build(i,p,root/'bundle')
                    self.assertEqual(len(report['constraint_changes']),1000 if disjoint else 500)
                    self.assertGreater((root/'bundle/review.md').stat().st_size,2*1024*1024)
                    self.assertTrue(verify(root/'bundle')['verified'])
    def test_oversized_report_rejected_before_output_directory(self):
        from unittest.mock import patch
        for serializer in ('canonical','markdown'):
            # Patch only the serialization of the report, not graph comparisons.
            import component_swap.core as core
            original=getattr(core,serializer)
            def oversized(value):
                if 'constraint_changes' in value:return b'x'*(core.REPORT_LIMIT+1)
                return original(value)
            with tempfile.TemporaryDirectory() as d, patch.object(core,serializer,side_effect=oversized):
                out=Path(d)/'out'
                with self.assertRaises(Invalid):build(ROOT/'examples/inventory.json',ROOT/'examples/mismatch.json',out)
                self.assertFalse(out.exists())
    def test_combined_constraint_limit_not_only_replacements(self):
        data=json.loads(INV)
        # Original 100 components each with a dependency can remain within
        # bounds; test the global guard directly with an oversized declaration.
        from component_swap.core import components
        provider=data['components'][0];nodes=[provider]
        for i in range(18):
            nodes.append({'id':'consumer'+str(i),'kind':'client','version':'v1','facts':{},'requires':[{'provider':'embedding','constraints':{'key'+str(j):1 for j in range(30)}}]})
        with self.assertRaises(Invalid):components(nodes)
    def test_cli_plan_verify(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'b'
            for args in [['plan','examples/inventory.json','examples/mismatch.json','--out',str(out)],['verify',str(out)]]:
                result=subprocess.run([sys.executable,'-m','component_swap',*args],cwd=ROOT,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
if __name__=='__main__':unittest.main()
