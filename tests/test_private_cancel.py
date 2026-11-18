"""Synthetic real process and output permission regression, no remote services."""
import os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from component_swap import contracts as c,core,bom_review as b
from component_swap.lifecycle import Cancelled,cancellation
ROOT=Path(__file__).resolve().parents[1];EX=ROOT/'examples';CX=EX/'contracts'

@unittest.skipUnless(os.name=='posix','POSIX permissions and cancellation checks')
class Safety(unittest.TestCase):
    def test_all_bundle_permissions(self):
        for mask in (0o022,0o000):
            with self.subTest(mask=mask),tempfile.TemporaryDirectory() as td:
                before=os.umask(mask)
                try:
                    root=Path(td)
                    core.build(EX/'inventory.json',EX/'declared-match.json',root/'native')
                    b.build({k:EX/v for k,v in {'inventory':'inventory.json','replacements':'declared-match.json','before':'before-bom.json','after':'after-bom.json'}.items()},EX/'bom-mapping.json',root/'bom')
                    c.run(CX/'inventory.json',CX/'replacement.json',CX/'contract.json',CX/'json_store.py',CX/'sqlite_store.py',root/'contracts',True)
                    for directory in root.iterdir():
                        self.assertEqual(directory.stat().st_mode&0o777,0o700)
                        for f in directory.iterdir():self.assertEqual(f.stat().st_mode&0o777,0o600,f.name)
                    self.assertEqual(os.umask(mask),mask)
                finally:os.umask(before)

    def test_active_cancel(self):
        for sig in (signal.SIGINT,signal.SIGTERM):
            with self.subTest(sig=sig),tempfile.TemporaryDirectory() as td:
                root=Path(td);pid=root/'pid';late=root/'late';folder=root/'cwd';adapter=root/'a.py'
                adapter.write_text(f'import os,time,pathlib\npathlib.Path({str(folder)!r}).write_text(os.getcwd())\npathlib.Path({str(pid)!r}).write_text(str(os.getpid()))\ntime.sleep(1)\npathlib.Path({str(late)!r}).write_text("unexpected")\ntime.sleep(20)\n')
                p=subprocess.Popen([sys.executable,'-m','component_swap.contracts','run',str(CX/'inventory.json'),str(CX/'replacement.json'),str(CX/'contract.json'),str(adapter),str(adapter),'--out',str(root/'out'),'--trust-adapters'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                try:
                    until=time.monotonic()+5
                    while not pid.exists() and time.monotonic()<until:time.sleep(.01)
                    self.assertTrue(pid.exists());child=int(pid.read_text());p.send_signal(sig)
                    _,err=p.communicate(timeout=5);self.assertEqual(p.returncode,128+sig,err)
                    with self.assertRaises(ProcessLookupError):os.kill(child,0)
                    self.assertFalse(Path(folder.read_text()).exists())
                    time.sleep(1.1);self.assertFalse(late.exists());self.assertFalse((root/'out').exists())
                finally:
                    if p.poll() is None:p.kill();p.wait()
                    if pid.exists():
                        try:os.killpg(int(pid.read_text()),signal.SIGKILL)
                        except ProcessLookupError:pass
                    p.stderr.close()

    def test_spawn_handle_race(self):
        real=subprocess.Popen;children=[]
        def inject(*a,**kw):
            p=real(*a,**kw);children.append(p);os.kill(os.getpid(),signal.SIGTERM);return p
        old=signal.getsignal(signal.SIGTERM)
        with patch.object(c.subprocess,'Popen',inject):
            with self.assertRaises(Cancelled):c.execute(b'import time;time.sleep(20)',{},500)
        self.assertEqual(signal.getsignal(signal.SIGTERM),old)
        with self.assertRaises(ProcessLookupError):os.kill(children[0].pid,0)

    def test_thread_start_race(self):
        real=c.threading.Thread.start
        def inject(thread):
            real(thread);os.kill(os.getpid(),signal.SIGTERM)
        with patch.object(c.threading.Thread,'start',inject):
            with self.assertRaises(Cancelled):c.execute(b'import time;time.sleep(20)',{},500)

    def test_postcleanup_cancel(self):
        original=c.digest
        def inject(raw):
            os.kill(os.getpid(),signal.SIGTERM);return original(raw)
        with patch.object(c,'digest',inject):
            with self.assertRaises(Cancelled):c.execute(b'print(1)',{},500)

    def test_deferred_cancel(self):
        with self.assertRaises(Cancelled):
            with cancellation() as state:
                state['cleaning']=True;os.kill(os.getpid(),signal.SIGTERM)
        with self.assertRaisesRegex(RuntimeError,'original'):
            with cancellation() as state:
                state['cleaning']=True;os.kill(os.getpid(),signal.SIGTERM);raise RuntimeError('original')

    def test_private_write_exclusive_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);target=root/'target';target.write_text('unchanged');link=root/'link';link.symlink_to(target)
            for p in (target,link):
                with self.assertRaises(FileExistsError):core.private_write(p,b'new')
            self.assertEqual(target.read_text(),'unchanged')

    def test_private_write_failure(self):
        real=core.private_write;count=[0]
        def inject(p,data):
            count[0]+=1
            if count[0]==2:raise OSError('synthetic disk failure')
            real(p,data)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out'
            with patch.object(core,'private_write',inject):
                with self.assertRaises(OSError):core.build(EX/'inventory.json',EX/'declared-match.json',out)
            self.assertEqual(out.stat().st_mode&0o777,0o700)
            for f in out.iterdir():self.assertEqual(f.stat().st_mode&0o777,0o600)
            with self.assertRaises(core.Invalid):core.verify(out)

    def test_main_thread_required(self):
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            with self.assertRaises(ValueError):pool.submit(c.execute,b'print(1)',{},500).result()
