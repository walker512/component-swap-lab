import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from component_swap import contracts as c
from component_swap.core import Invalid, canonical

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / 'examples' / 'contracts'


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.spec = json.loads((EX / 'contract.json').read_text())
        self.spec['cases'] = [{'id':'answer','input':{'answer':1},'expected':1}]
        self.spec['timeout_ms'] = 500
        self.specfile = self.root / 'c.json'
        self.baseline = self.root / 'a.py'
        self.candidate = self.root / 'b.py'
        self.baseline.write_text('print(1)\n')
        self.candidate.write_text('print(1)\n')

    def tearDown(self):
        self.temp.cleanup()

    def run_contract(self, **kw):
        self.specfile.write_bytes(canonical(self.spec))
        return c.run(EX/'inventory.json',EX/'replacement.json',self.specfile,
                     self.baseline,self.candidate,self.root/'bundle',**kw)

    def test_real_json_and_sqlite_adapters(self):
        report = c.run(EX/'inventory.json',EX/'replacement.json',EX/'contract.json',
                       EX/'json_store.py',EX/'sqlite_store.py',self.root/'bundle',True)
        self.assertTrue(report['baseline_all_passed'])
        self.assertTrue(report['candidate_all_passed'])
        self.assertEqual(len(report['cases']),3)
        self.assertEqual(report['affected_components'],['client','store'])
        self.assertTrue(c.verify(self.root/'bundle')['verified'])
        self.assertFalse((self.root/'store.sqlite').exists())

    def test_trust_gate_runs_nothing(self):
        with patch.object(c,'execute',side_effect=AssertionError('must not run')):
            with self.assertRaises(Invalid): self.run_contract()
        self.assertFalse((self.root/'bundle').exists())

    def test_typed_comparison_true_is_not_one(self):
        self.candidate.write_text('print("true")')
        report=self.run_contract(trusted=True)
        self.assertFalse(report['candidate_all_passed'])
        self.assertEqual(report['cases'][0]['change'],'regression')

    def test_same_wrong_answer_is_not_success(self):
        self.baseline.write_text('print(2)')
        self.candidate.write_text('print(2)')
        r=self.run_contract(trusted=True)
        self.assertEqual(r['cases'][0]['change'],'neither_satisfies_contract')

    def test_preexisting_failure_not_candidate_regression(self):
        self.baseline.write_text('print(2)')
        r=self.run_contract(trusted=True)
        self.assertEqual(r['cases'][0]['change'],'candidate_resolves_case')

    def test_process_error_even_with_correct_stdout(self):
        self.candidate.write_text('import sys; print(1); sys.exit(3)')
        self.assertEqual(self.run_contract(trusted=True)['cases'][0]['candidate'],'process_error')

    def test_timeout(self):
        self.candidate.write_text('import time; time.sleep(5)')
        self.spec['timeout_ms']=100
        self.assertEqual(self.run_contract(trusted=True)['cases'][0]['candidate'],'timeout')

    def test_stdout_limit(self):
        self.candidate.write_text('print("x"*100000)')
        self.assertEqual(self.run_contract(trusted=True)['cases'][0]['candidate'],'output_limit')

    def test_stderr_limit(self):
        self.candidate.write_text('import sys; print("x"*100000,file=sys.stderr); print(1)')
        self.assertEqual(self.run_contract(trusted=True)['cases'][0]['candidate'],'output_limit')

    def test_invalid_output(self):
        for source in ['print("NaN")','print("1.0")','print("1\\n1")','print(\'{"a":1,"a":2}\')','import sys; sys.stdout.buffer.write(b"\\xff")']:
            with self.subTest(source=source):
                record=c.execute(source.encode(),{},500)
                self.assertEqual(c.outcome(record,1),'invalid_output')

    def test_empty_output_is_invalid(self):
        self.assertEqual(c.outcome(c.execute(b'pass',{},500),None),'invalid_output')

    def test_fresh_cwd_and_environment(self):
        script=b'import os,json; from pathlib import Path; print(json.dumps({"present":Path("prior").exists(),"secret":os.environ.get("CONTRACT_PRIVATE_TOKEN")})); Path("prior").write_text("x")'
        with patch.dict(os.environ,{'CONTRACT_PRIVATE_TOKEN':'synthetic-secret'}):
            for _ in range(2):
                self.assertEqual(c.outcome(c.execute(script,{},500),{'present':False,'secret':None}),'passed')

    def test_schema_validation_before_execution(self):
        changes=[('schema',True),('slot','missing'),('timeout_ms',True),('timeout_ms',99),('timeout_ms',10001),('cases',[])]
        for key,val in changes:
            original=self.spec[key]; self.spec[key]=val
            with self.subTest(key=key,val=val),patch.object(c,'execute',side_effect=AssertionError('must not run')):
                with self.assertRaises(Invalid):self.run_contract(trusted=True)
            self.spec[key]=original

    def test_duplicate_cases_rejected(self):
        self.spec['cases']*=2
        with self.assertRaises(Invalid):self.run_contract(trusted=True)

    def test_unknown_case_fields_rejected(self):
        self.spec['cases'][0]['extra']=0
        with self.assertRaises(Invalid):self.run_contract(trusted=True)

    def test_oversized_case_rejected(self):
        self.spec['cases'][0]['input']='x'*17000
        with self.assertRaises(Invalid):self.run_contract(trusted=True)

    def test_overwrite_preflight_does_not_execute(self):
        (self.root/'bundle').mkdir()
        with patch.object(c,'execute',side_effect=AssertionError('must not run')):
            with self.assertRaises(Invalid):self.run_contract(trusted=True)

    def test_all_bundle_files_bound(self):
        self.run_contract(trusted=True)
        folder=self.root/'bundle'
        for f in folder.iterdir():
            original=f.read_bytes()
            f.write_bytes(original+b' ')
            with self.subTest(name=f.name),self.assertRaises(Invalid): c.verify(folder)
            f.write_bytes(original)

    def test_verify_does_not_execute(self):
        self.run_contract(trusted=True)
        with patch.object(c,'execute',side_effect=AssertionError('must not run')):
            self.assertTrue(c.verify(self.root/'bundle')['verified'])

    def test_missing_extra_files(self):
        self.run_contract(trusted=True)
        folder=self.root/'bundle'
        (folder/'extra').write_text('x')
        with self.assertRaises(Invalid):c.verify(folder)
        (folder/'extra').unlink();(folder/'baseline.py').unlink()
        with self.assertRaises(Invalid):c.verify(folder)

    def test_reordered_evidence(self):
        self.run_contract(trusted=True)
        f=self.root/'bundle'/'observations.json'
        obj=json.loads(f.read_text());obj['rows'].reverse();f.write_bytes(canonical(obj))
        with self.assertRaises(Invalid):c.verify(f.parent)

    def test_record_validation(self):
        rec=c.execute(b'print(1)',{},500)
        for k,v in [('execution','fake'),('returncode',True),('stderr_bytes',True),('stderr_bytes',20000),('stderr_sha256','bad'),('stdout','%%%')]:
            with self.subTest(key=k),self.assertRaises(Invalid):c.outcome({**rec,k:v},1)

    def test_incomplete_baseline_never_claims_resolution(self):
        self.specfile.write_bytes(canonical(self.spec))
        good=c.execute(b'print(1)',{},500)
        incomplete={**good,'execution':'launch_error','returncode':None}
        with patch.object(c,'execute',side_effect=[incomplete,good]):
            r=self.run_contract(trusted=True)
        self.assertTrue(r['candidate_all_passed'])
        self.assertFalse(r['comparison_complete'])
        self.assertEqual(r['cases'][0]['change'],'candidate_passed_baseline_not_verified')
        self.assertFalse(c.verify(self.root/'bundle')['comparison_complete'])

    def test_incomplete_baseline_cli_returns_two(self):
        self.baseline.write_text('import time;time.sleep(5)')
        self.spec['timeout_ms']=100
        self.specfile.write_bytes(canonical(self.spec))
        args=[sys.executable,'-m','component_swap.contracts','run',str(EX/'inventory.json'),str(EX/'replacement.json'),str(self.specfile),str(self.baseline),str(self.candidate),'--out',str(self.root/'bundle'),'--trust-adapters']
        result=subprocess.run(args,cwd=ROOT,capture_output=True)
        self.assertEqual(result.returncode,2,result.stderr)
        report=json.loads(result.stdout)
        self.assertTrue(report['candidate_all_passed'])
        self.assertFalse(report['comparison_complete'])


    def test_symlink_input_rejected(self):
        link=self.root/'link.py'
        try:link.symlink_to(self.baseline)
        except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
        self.baseline=link
        with self.assertRaises(Invalid):self.run_contract(trusted=True)

    def test_cli_exit_and_offline_verify(self):
        self.specfile.write_bytes(canonical(self.spec))
        args=[sys.executable,'-m','component_swap.contracts','run',str(EX/'inventory.json'),str(EX/'replacement.json'),str(self.specfile),str(self.baseline),str(self.candidate),'--out',str(self.root/'bundle')]
        denied=subprocess.run(args,cwd=ROOT,capture_output=True)
        self.assertEqual(denied.returncode,2)
        good=subprocess.run(args+['--trust-adapters'],cwd=ROOT,capture_output=True)
        self.assertEqual(good.returncode,0,good.stderr)
        check=subprocess.run([sys.executable,'-m','component_swap.contracts','verify',str(self.root/'bundle')],cwd=ROOT,capture_output=True)
        self.assertEqual(check.returncode,0,check.stderr)


if __name__=='__main__':unittest.main()
