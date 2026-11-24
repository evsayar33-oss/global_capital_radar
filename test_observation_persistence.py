import subprocess,tempfile,unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parent/"scripts/persist_observations.sh"
def git(root,*args,check=True):
    return subprocess.run(["git","-C",str(root),*args],capture_output=True,text=True,check=check)
class PersistenceTests(unittest.TestCase):
    def run_race(self,overlap):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);remote=r/"remote.git";a=r/"a";b=r/"b"
            git(r,"init","--bare","--initial-branch=main",str(remote))
            git(r,"clone",str(remote),str(a))
            for k,v in [("user.name","test"),("user.email","test@example.com")]:git(a,"config",k,v)
            (a/"code.py").write_text("initial\n");(a/"observation.json").write_text("{}\n")
            git(a,"add",".");git(a,"commit","-m","base");git(a,"push","origin","main")
            git(r,"clone",str(remote),str(b))
            for k,v in [("user.name","test"),("user.email","test@example.com")]:git(b,"config",k,v)
            (a/"observation.json").write_text('{"a":1}\n')
            git(a,"add",".");git(a,"commit","-m","observed")
            (b/("observation.json" if overlap else "code.py")).write_text("remote change\n")
            git(b,"add",".");git(b,"commit","-m","new merge");git(b,"push","origin","main")
            patch=r/"recovery.patch"
            proc=subprocess.run(["bash",str(SCRIPT),str(patch)],cwd=a,capture_output=True,text=True)
            if overlap:
                self.assertNotEqual(proc.returncode,0)
                self.assertTrue(patch.exists())
                self.assertIn("observed",patch.read_text())
            else:
                self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
                self.assertFalse(patch.exists())
                git(b,"pull","--ff-only")
                self.assertEqual((b/"observation.json").read_text(),'{"a":1}\n')
                self.assertEqual((b/"code.py").read_text(),"remote change\n")
    def test_nonoverlap_merge(self):self.run_race(False)
    def test_overlap_preserves_patch(self):self.run_race(True)
