import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
PI=ROOT/'.pi-runtime/node_modules/.bin/pi'
EXT=ROOT/'.pi-runtime/node_modules/pi-codex-image-gen/index.ts'

class PiRuntimeSmokeTest(unittest.TestCase):
    @unittest.skipUnless(PI.exists() and EXT.exists(),'Pi runtime not installed')
    def test_extension_loads_without_calling_ai_or_real_credentials(self):
        with tempfile.TemporaryDirectory(prefix='huixu-pi-') as directory:
            env={k:v for k,v in os.environ.items() if not k.endswith('_API_KEY')}
            env.update(PI_CODING_AGENT_DIR=directory,PI_TELEMETRY='0',PI_OFFLINE='1',OPENAI_API_KEY='not-a-real-key')
            args=[str(PI),'--mode','rpc','--no-extensions','--no-skills','--no-prompt-templates','--no-context-files','--no-mcp','--no-session','--provider','openai','--model','gpt-5.5','-e',str(EXT)]
            p=subprocess.run(args,input='{"type":"get_commands"}\n',text=True,capture_output=True,env=env,cwd=ROOT,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr[:200])
            self.assertTrue(json.loads(p.stdout)['success'])
            self.assertIn('image-artifacts',p.stdout)
            self.assertNotIn('Extension error',p.stderr)

if __name__=='__main__': unittest.main()
