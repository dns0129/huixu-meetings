import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pi_bridge

class PiModelSelectionTest(unittest.TestCase):
    def test_selects_account_visible_model_available_in_pi(self):
        with patch.object(pi_bridge,'_account_models',return_value=['gpt-6-sol','gpt-6.1-sol']), patch.object(pi_bridge,'_pi_models',return_value={'gpt-6-sol','gpt-6.1-sol'}):
            self.assertEqual(pi_bridge._select_chat_model(Path('/pi'),Path('/root'),Path('/account'),'openai'),'gpt-6.1-sol')

    def test_empty_intersection_is_reported_without_using_unsupported_model(self):
        with patch.object(pi_bridge,'_account_models',return_value=['account-only']), patch.object(pi_bridge,'_pi_models',return_value={'pi-only'}):
            with self.assertRaisesRegex(ValueError,'GPT-6.1 Sol'):
                pi_bridge._select_chat_model(Path('/pi'),Path('/root'),Path('/account'),'openai')

    def test_incomplete_catalog_uses_only_the_requested_pi_model(self):
        with patch.object(pi_bridge,'_account_models',side_effect=ValueError('目录超时')), patch.object(pi_bridge,'_pi_models',return_value={'gpt-6.1-sol'}):
            self.assertEqual(pi_bridge._select_chat_model(Path('/pi'),Path('/root'),Path('/account'),'openai'),'gpt-6.1-sol')

    def test_account_catalog_uses_bearer_via_stdin_not_arguments(self):
        token='fake-token-for-local-test'
        calls=[]
        def run(args,**kwargs):
            calls.append((args,kwargs))
            if args[1:3]==['auth','print-bearer-token']:
                return SimpleNamespace(returncode=0,stdout=token+'\n',stderr='')
            return SimpleNamespace(returncode=0,stdout=json.dumps({'models':[{'slug':'gpt-6.1-sol','visibility':'list'},{'slug':'hidden','visibility':'hidden'}]})+'\n__HUIXU_HTTP_STATUS__:200',stderr='')
        with patch.object(pi_bridge.subprocess,'run',side_effect=run):
            self.assertEqual(pi_bridge._account_models(Path('/pi'),Path('/root'),Path('/account')),['gpt-6.1-sol'])
        self.assertNotIn(token,' '.join(map(str,calls[1][0])))
        self.assertIn(token,calls[1][1]['input'])

    def test_partial_model_catalog_requires_complete_visible_model_and_http_success(self):
        partial='{"models":[{"slug":"gpt-6.1-sol","visibility":"list"},{"slug":"unfinished'
        def run(args,**kwargs):
            if args[1:3]==['auth','print-bearer-token']:return SimpleNamespace(returncode=0,stdout='fake-token',stderr='')
            return SimpleNamespace(returncode=28,stdout=partial+'\n__HUIXU_HTTP_STATUS__:200',stderr='timeout')
        with patch.object(pi_bridge.subprocess,'run',side_effect=run):
            self.assertEqual(pi_bridge._account_models(Path('/pi'),Path('/root'),Path('/account')),['gpt-6.1-sol'])
        def bad(args,**kwargs):
            if args[1:3]==['auth','print-bearer-token']:return SimpleNamespace(returncode=0,stdout='fake-token',stderr='')
            return SimpleNamespace(returncode=28,stdout=partial+'\n__HUIXU_HTTP_STATUS__:403',stderr='timeout')
        with patch.object(pi_bridge.subprocess,'run',side_effect=bad), self.assertRaises(ValueError):
            pi_bridge._account_models(Path('/pi'),Path('/root'),Path('/account'))

    def test_image_tool_errors_are_classified_without_echoing_secrets(self):
        event={'type':'tool_execution_end','toolName':'codex_generate_image','isError':True,'result':{'content':[{'type':'text','text':'Codex connection failed. token-private-value'}]}}
        message=pi_bridge._image_event_error(json.dumps(event))
        self.assertIn('连接失败',message); self.assertNotIn('token-private-value',message)
        event['result']['content'][0]['text']='Image generation timed out after dispatch. Image quota may have been consumed.'
        self.assertIn('超时',pi_bridge._image_event_error(json.dumps(event)))

    def test_image_policy_forces_model_and_blocks_duplicate(self):
        root=Path(__file__).resolve().parent.parent
        js="""import policy from './extensions/image-policy.ts';let handler;process.env.PI_CODEX_IMAGE_SAVE_DIR='/tmp/job';policy({on(n,cb){handler=cb}});const e={toolName:'codex_generate_image',input:{model:'gpt-6-astra',transport:'images',saveDir:'/tmp/elsewhere',referencedImagePaths:['/tmp/private.png']}};handler(e);if(e.input.model!=='gpt-6.1-sol'||e.input.transport!=='responses'||e.input.saveDir!=='/tmp/job'||e.input.referencedImagePaths)process.exit(1);if(!handler({toolName:'codex_generate_image',input:{}}).block)process.exit(2);"""
        result=__import__('subprocess').run(['node','--input-type=module','-e',js],cwd=root,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_recovers_saved_image_if_agent_fails_after_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); data=root/'data'; data.mkdir()
            def fake_run(pi,ext,root,account,prompt,image=False,output_dir=None):
                (output_dir/'recovered.png').write_bytes(b'png-data')
                raise ValueError('agent reply failed after image was saved')
            with patch.object(pi_bridge,'status',return_value={'image_signed_in':True}), patch.object(pi_bridge,'_run',side_effect=fake_run):
                result=pi_bridge.run(root,data,1,{'title':'测试会议','data':{}},'image',{})
            self.assertEqual(Path(result['path']).read_bytes(),b'png-data')

    def test_analysis_normalizes_date_and_table_card_names(self):
        result=pi_bridge._normalize_analysis({'date':'2027年3月18日（星期四）','guests':'张岚｜示例中心主任\n李明｜示例企业创始人','questions':[]})
        self.assertEqual(result['date'],'2027-03-18')
        self.assertEqual(result['guests'],'张岚\n李明')

    def test_invalid_date_is_left_unset_and_asked(self):
        result=pi_bridge._normalize_analysis({'date':'2027年2月30日','guests':'','questions':[]})
        self.assertEqual(result['date'],'')
        self.assertTrue(any('日期' in str(q) for q in result['questions']))

    def test_run_uses_selected_model(self):
        with tempfile.TemporaryDirectory() as d:
            account=Path(d); (account/'auth.json').write_text(json.dumps({'openai':{'type':'oauth'}}))
            with patch.object(pi_bridge,'_select_chat_model',return_value='gpt-6.1-sol'), patch.object(pi_bridge.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='OK',stderr='')) as command:
                result=pi_bridge._run(Path('/pi'),Path('/ext'),Path('/root'),account,'测试',image=False)
            self.assertEqual(result,'OK'); args=command.call_args.args[0]
            self.assertEqual(args[args.index('--model')+1],'gpt-6.1-sol')
            self.assertNotIn('测试',args); self.assertEqual(command.call_args.kwargs['input'],'测试')

if __name__=='__main__':unittest.main()
