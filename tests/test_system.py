import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from unittest import mock

_tmp = tempfile.TemporaryDirectory(prefix='huixu-test-')
os.environ['MEETING_DATA_DIR'] = _tmp.name
import app as server
from docx import Document
from openpyxl import Workbook, load_workbook
from PIL import Image

class MeetingSystemTest(unittest.TestCase):
    def setUp(self):
        self.a=server.app.test_client(); self.b=server.app.test_client()
        self.suffix=str(time.time_ns())
        for client,name in ((self.a,'A'+self.suffix),(self.b,'B'+self.suffix)):
            self.assertEqual(client.post('/api/register',json={'username':name,'password':'password-test-123'}).status_code,200)
        self.sid=self.a.post('/api/series',json={'name':'成长交流系列'}).json['id']
        self.mid=self.a.post('/api/meetings',json={'series_id':self.sid,'title':'小微企业成长交流会'}).json['id']
        self.data={'date':'2027-03-18','time':'09:00','location':'上海会客厅','organizer':'示例协会','host':'陈老师','subtitle':'携手成长','baseline':'这是本次会议底稿。','guests':'张明\n李华','agenda':[{'time':'09:00','item':'开幕致辞','speaker':'张明','note':'主会场'},{'time':'09:30','item':'专题交流','speaker':'李华','note':''}], 'design':{'poster':{'width':210,'height':297,'font':'hei','palette':'blue'},'banner':{'width':800,'height':2000,'font':'song','palette':'forest'},'card':{'width':210,'height':100,'font':'hei','palette':'blue'}}}
        response=self.a.put(f'/api/meetings/{self.mid}',json={'title':'小微企业成长交流会','data':self.data})
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))

    def test_ownership_and_auth(self):
        self.assertEqual(self.b.get(f'/api/meetings/{self.mid}').status_code,404)
        self.assertEqual(self.b.get(f'/api/meetings/{self.mid}/export/agenda.xlsx').status_code,404)
        self.assertEqual(self.b.post('/api/meetings',json={'series_id':self.sid,'title':'无权创建'}).status_code,404)
        self.assertEqual(self.a.post(f'/api/meetings/{self.mid}/ai/analyze',json={}).status_code,401)
        self.assertEqual(self.a.post('/api/logout').status_code,200)
        self.assertEqual(self.a.get('/api/series').status_code,401)

    def test_word_excel_and_script(self):
        x=self.a.get(f'/api/meetings/{self.mid}/export/agenda.xlsx'); self.assertEqual(x.status_code,200)
        sheet=load_workbook(io.BytesIO(x.data)).active
        self.assertIn('成长交流会',sheet['A1'].value); self.assertEqual(sheet['B5'].value,'开幕致辞')
        w=self.a.get(f'/api/meetings/{self.mid}/export/agenda.docx'); self.assertEqual(w.status_code,200)
        doc=Document(io.BytesIO(w.data)); self.assertIn('开幕致辞',doc.tables[0].cell(1,1).text)
        script=self.a.post(f'/api/meetings/{self.mid}/draft-script').json['script']; self.assertIn('专题交流',script); self.assertIn('李华',script)
        output=self.a.get(f'/api/meetings/{self.mid}/export/script.docx'); self.assertEqual(output.status_code,200)
        doc=Document(io.BytesIO(output.data)); self.assertIn('开幕致辞','\n'.join(p.text for p in doc.paragraphs))

    def test_kv_editor_keeps_background_and_persists_editable_layers(self):
        image=io.BytesIO();Image.new('RGB',(210,297),(220,180,140)).save(image,'PNG');image.seek(0)
        upload=self.a.post(f'/api/meetings/{self.mid}/upload',data={'kind':'background','file':(image,'kv.png')},content_type='multipart/form-data')
        self.assertEqual(upload.status_code,200)
        self.data['poster_kv_file_id']=upload.json['id']
        self.data['design']['poster']['elements']=[{'type':'text','text':'测试文字','x':.1,'y':.3,'w':.8,'h':.2,'size':.05,'color':'#000000','align':'center'}]
        result=self.a.put(f'/api/meetings/{self.mid}',json={'title':'会议','data':self.data});self.assertEqual(result.status_code,200,result.json)
        saved=self.a.get(f'/api/meetings/{self.mid}').json['data']
        self.assertEqual(saved['design']['poster']['elements'][0]['text'],'测试文字')
        result=self.a.get(f'/api/meetings/{self.mid}/export/poster.png');self.assertEqual(result.status_code,200)
        rendered=Image.open(io.BytesIO(result.data));self.assertEqual(rendered.getpixel((10,10)),(220,180,140))
        saved['design']['poster']['elements'][0]['x']=1.2
        self.assertEqual(self.a.put(f'/api/meetings/{self.mid}',json={'title':'会议','data':saved}).status_code,400)

    def test_selected_library_kv_appears_in_material_preview(self):
        image=io.BytesIO();Image.new('RGB',(210,297),(25,140,190)).save(image,'PNG');image.seek(0)
        kid=self.a.post('/api/library/kvs',data={'name':'测试 KV','agenda':(image,'kv.png')},content_type='multipart/form-data').json['id']
        self.assertEqual(self.a.post(f'/api/meetings/{self.mid}/library',json={'kv_id':kid}).status_code,200)
        saved=self.a.get(f'/api/meetings/{self.mid}').json['data']
        saved['design']['poster']['elements']=[]
        self.assertEqual(self.a.put(f'/api/meetings/{self.mid}',json={'title':'会议','data':saved}).status_code,200)
        result=self.a.get(f'/api/meetings/{self.mid}/preview/poster')
        self.assertEqual(result.status_code,200)
        self.assertEqual(Image.open(io.BytesIO(result.data)).getpixel((10,10)),(25,140,190))

    def test_visual_and_batch_exports(self):
        for kind in ('poster','banner','card'):
            response=self.a.get(f'/api/meetings/{self.mid}/preview/{kind}')
            self.assertEqual(response.status_code,200,(kind,response.data[:200]))
            img=Image.open(io.BytesIO(response.data)); self.assertEqual(img.format,'PNG'); self.assertGreater(img.width,50)
            if kind=='card': self.assertGreater(img.width,img.height)
            else: self.assertGreater(img.height,img.width)
        png=self.a.get(f'/api/meetings/{self.mid}/export/poster.png'); self.assertEqual(png.status_code,200); self.assertEqual(Image.open(io.BytesIO(png.data)).format,'PNG')
        pdf=self.a.get(f'/api/meetings/{self.mid}/export/card.pdf'); self.assertEqual(pdf.status_code,200); self.assertTrue(pdf.data.startswith(b'%PDF'))
        z=self.a.get(f'/api/meetings/{self.mid}/export/cards.zip'); self.assertEqual(z.status_code,200)
        with zipfile.ZipFile(io.BytesIO(z.data)) as archive:
            names=archive.namelist(); self.assertEqual(len(names),2); self.assertTrue(any('张明' in n for n in names))

    def test_import_and_validation(self):
        doc=Document(); doc.add_paragraph('底稿：开会地点在上海')
        buf=io.BytesIO(); doc.save(buf); buf.seek(0)
        r=self.a.post(f'/api/meetings/{self.mid}/upload',data={'kind':'source','file':(buf,'资料.docx')},content_type='multipart/form-data')
        self.assertEqual(r.status_code,200,r.get_data(as_text=True)); self.assertIn('上海',r.json['text'])
        self.assertEqual(self.b.get('/api/files/'+str(r.json['id'])).status_code,404)
        wb=Workbook(); wb.active.append(['时间','环节']); wb.active.append(['09:00','签到']); buf=io.BytesIO();wb.save(buf);buf.seek(0)
        r=self.a.post(f'/api/meetings/{self.mid}/upload',data={'kind':'source','file':(buf,'日程.xlsx')},content_type='multipart/form-data')
        self.assertEqual(r.status_code,200); self.assertIn('签到',r.json['text'])
        invalid=dict(self.data); invalid['design']={'poster':{'width':99999}}
        self.assertEqual(self.a.put(f'/api/meetings/{self.mid}',json={'title':'会议','data':invalid}).status_code,400)

    def test_series_template_reuses_design_without_copying_content(self):
        logo=io.BytesIO(); Image.new('RGBA',(50,25),'#67aabc').save(logo,'PNG'); logo.seek(0)
        uploaded=self.a.post(f'/api/meetings/{self.mid}/upload',data={'kind':'logo','file':(logo,'logo.png')},content_type='multipart/form-data')
        self.assertEqual(uploaded.status_code,200); self.data['logo_file_id']=uploaded.json['id']
        font_path='/System/Library/Fonts/Hiragino Sans GB.ttc'
        with open(font_path,'rb') as f:
            uploaded_font=self.a.post(f'/api/meetings/{self.mid}/upload',data={'kind':'font','file':(io.BytesIO(f.read()),'custom.ttc')},content_type='multipart/form-data')
        self.assertEqual(uploaded_font.status_code,200); self.data['font_file_id']=uploaded_font.json['id']; self.data['design']['poster']['font']='custom'
        self.a.put(f'/api/meetings/{self.mid}',json={'title':'原会议','data':self.data})
        self.assertEqual(self.a.post(f'/api/series/{self.sid}/template',json={'meeting_id':self.mid}).status_code,200)
        created=self.a.post('/api/meetings',json={'series_id':self.sid,'title':'下一场会议'}).json['id']
        result=self.a.get(f'/api/meetings/{created}').json['data']
        self.assertEqual(result['design']['poster']['font'],'custom'); self.assertNotEqual(result['logo_file_id'],self.data['logo_file_id'])
        self.assertTrue(result['font_file_id']); self.assertEqual(result['baseline'],''); self.assertEqual(result['agenda'],[])
        self.assertEqual(self.a.get(f'/api/meetings/{created}/preview/poster').status_code,200)
        self.assertEqual(self.b.get(f"/api/files/{result['logo_file_id']}").status_code,404)

    def test_ai_job_saves_image_and_respects_account_scope(self):
        image_path=os.path.join(_tmp.name,'fake-generated.png'); Image.new('RGB',(60,100),'navy').save(image_path)
        with mock.patch.object(server.pi_bridge,'status',return_value={'installed':True,'chat_signed_in':True,'image_signed_in':True}), mock.patch.object(server.pi_bridge,'run',return_value={'path':image_path}):
            r=self.a.post(f'/api/meetings/{self.mid}/ai/image',json={'prompt':'蓝色背景'})
            self.assertEqual(r.status_code,200); job=r.json['job_id']
            for _ in range(50):
                status=self.a.get(f'/api/jobs/{job}').json
                if status['status']!='running': break
                time.sleep(.05)
            self.assertEqual(status['status'],'done',status)
            download=self.a.get('/api/files/'+str(status['result']['file_id'])); self.assertEqual(download.status_code,200); download.close()
            self.assertEqual(self.b.get(f'/api/jobs/{job}').status_code,404)

    def test_generated_kv_targets_selected_material_and_does_not_overwrite_new_upload(self):
        import threading
        image_path=os.path.join(_tmp.name,'kv-job.png'); Image.new('RGB',(60,100),'navy').save(image_path)
        entered=threading.Event(); release=threading.Event()
        def generate(*args):
            entered.set(); self.assertTrue(release.wait(5)); return {'path':image_path}
        with mock.patch.object(server.pi_bridge,'status',return_value={'installed':True,'chat_signed_in':True,'image_signed_in':True}), mock.patch.object(server.pi_bridge,'run',side_effect=generate):
            start=self.a.post(f'/api/meetings/{self.mid}/ai/image',json={'kind':'banner'})
            self.assertEqual(start.status_code,200); self.assertTrue(entered.wait(3))
            image=io.BytesIO();Image.new('RGB',(30,40),'red').save(image,'PNG');image.seek(0)
            upload=self.a.post(f'/api/meetings/{self.mid}/upload',data={'kind':'background','file':(image,'new.png')},content_type='multipart/form-data')
            current=self.a.get(f'/api/meetings/{self.mid}').json['data'];current['banner_kv_file_id']=upload.json['id']
            self.a.put(f'/api/meetings/{self.mid}',json={'title':'会议','data':current});release.set()
            for _ in range(100):
                job=self.a.get('/api/jobs/'+start.json['job_id']).json
                if job['status']!='running':break
                time.sleep(.02)
            self.assertEqual(job['status'],'done',job);self.assertFalse(job['result']['applied'])
            self.assertEqual(self.a.get(f'/api/meetings/{self.mid}').json['data']['banner_kv_file_id'],upload.json['id'])

    def test_domestic_image_tiers_do_not_require_pi_and_apply_to_original_meeting(self):
        image=io.BytesIO(); Image.new('RGB',(60,100),'navy').save(image,'PNG')
        self.assertEqual(self.a.put('/api/image-providers/fast',json={'api_key':'fast-test-secret'}).status_code,200)
        self.assertEqual(self.a.put('/api/image-providers/advanced',json={'api_key':'advanced-test-secret','workspace_id':'llm-test'}).status_code,200)
        settings=self.a.get('/api/image-providers').get_data(as_text=True)
        self.assertNotIn('test-secret',settings)
        self.assertFalse(self.b.get('/api/image-providers').json['fast']['configured'])
        for tier in ('fast','advanced'):
            with mock.patch.object(server.pi_bridge,'status',side_effect=AssertionError('domestic tiers must not require Pi')), mock.patch.object(server.image_bridge,'generate',return_value=image.getvalue()) as generate:
                r=self.a.post(f'/api/meetings/{self.mid}/ai/image',json={'prompt':'蓝色背景','tier':tier,'kind':'poster'})
                self.assertEqual(r.status_code,200,r.get_data(as_text=True)); job=r.json['job_id']
                for _ in range(100):
                    result=self.a.get(f'/api/jobs/{job}').json
                    if result['status']!='running': break
                    time.sleep(.02)
                self.assertEqual(result['status'],'done',result)
                self.assertEqual(generate.call_args.args[1],tier)
                self.assertEqual(self.a.get(f'/api/meetings/{self.mid}').json['data']['poster_kv_file_id'],result['result']['file_id'])
                self.assertEqual(self.b.get(f'/api/jobs/{job}').status_code,404)
                self.assertEqual(self.b.get('/api/files/'+str(result['result']['file_id'])).status_code,404)
        self.assertEqual(self.a.post(f'/api/meetings/{self.mid}/ai/image',json={'tier':['invalid']}).status_code,400)
        self.assertEqual(self.b.post(f'/api/meetings/{self.mid}/ai/image',json={'tier':'fast'}).status_code,404)

    def test_question_and_formula_safety(self):
        incomplete={'agenda':[{'item':'分享'}]}
        r=self.a.put(f'/api/meetings/{self.mid}',json={'title':'会议','data':incomplete}); self.assertEqual(r.status_code,200)
        self.assertTrue(any('地点' in q['question'] for q in r.json['questions']))
        data=dict(self.data);data['agenda']=[{'time':'09:00','item':'=1+1','speaker':'','note':''}]
        self.a.put(f'/api/meetings/{self.mid}',json={'title':'会议','data':data})
        excel=self.a.get(f'/api/meetings/{self.mid}/export/agenda.xlsx')
        self.assertEqual(load_workbook(io.BytesIO(excel.data)).active['B5'].value,"'=1+1")

    def test_library_assets_are_isolated_and_meeting_uses_snapshot(self):
        def png():
            output=io.BytesIO(); Image.new('RGB',(40,60),'#ddddee').save(output,'PNG'); output.seek(0); return output
        project=self.a.post('/api/library/projects',data={'name':'示例项目','organization':'示例协会','logo':(png(),'logo.png')},content_type='multipart/form-data')
        self.assertEqual(project.status_code,200,project.get_data(as_text=True)); pid=project.json['id']
        kv=self.a.post('/api/library/kvs',data={'name':'固定视觉','agenda':(png(),'agenda.png'),'slide':(png(),'slide.png'),'bio':(png(),'bio.png'),'card':(png(),'card.png')},content_type='multipart/form-data')
        self.assertEqual(kv.status_code,200,kv.get_data(as_text=True)); kid=kv.json['id']
        library=self.a.get('/api/library').json; aid=library['projects'][0]['logo_asset_id']
        self.assertEqual(self.b.get('/api/library').json['projects'],[])
        self.assertEqual(self.b.get(f'/api/library/assets/{aid}').status_code,404)
        self.assertEqual(self.b.post(f'/api/meetings/{self.mid}/library',json={'project_id':pid,'kv_id':kid}).status_code,404)
        self.assertEqual(self.a.post(f'/api/meetings/{self.mid}/library',json={'project_id':pid,'kv_id':kid}).status_code,200)
        saved=self.a.get(f'/api/meetings/{self.mid}').json['data']
        self.assertEqual(saved['project_name'],'示例项目'); self.assertEqual(saved['organizer'],'示例协会')
        self.assertTrue(saved['logo_file_id']); self.assertTrue(saved['kv_agenda_file_id']); self.assertTrue(saved['kv_slide_file_id'])
        changed=self.a.put(f'/api/library/projects/{pid}',data={'name':'修改后的项目','organization':'新机构'},content_type='multipart/form-data')
        self.assertEqual(changed.status_code,200)
        snapshot=self.a.get(f'/api/meetings/{self.mid}').json['data']
        self.assertEqual(snapshot['project_name'],'示例项目'); self.assertEqual(snapshot['logo_file_id'],saved['logo_file_id'])
        portrait=self.a.post(f'/api/meetings/{self.mid}/upload',data={'kind':'portrait','file':(png(),'speaker.png')},content_type='multipart/form-data')
        self.assertEqual(portrait.status_code,200)
        snapshot['profiles']=[{'name':'张明','organization':'示例单位','bio':'这是示例简介。','photo_file_id':portrait.json['id']}]
        self.assertEqual(self.a.put(f'/api/meetings/{self.mid}',json={'title':'会议','data':snapshot}).status_code,200)
        self.assertEqual(self.a.get(f'/api/meetings/{self.mid}/preview/agenda-kv').status_code,200)
        ppt=self.a.get(f'/api/meetings/{self.mid}/export/transition.pptx')
        self.assertEqual(ppt.status_code,200,ppt.json if ppt.is_json else '')
        with zipfile.ZipFile(io.BytesIO(ppt.data)) as archive:
            slides=[n for n in archive.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
            self.assertEqual(len(slides),4)
            media=[n for n in archive.namelist() if n.startswith('ppt/media/')]
            self.assertTrue(media); self.assertTrue(all(archive.getinfo(n).file_size>0 for n in media))
            self.assertIn('开幕致辞',archive.read('ppt/slides/slide2.xml').decode())
            self.assertIn('示例简介',archive.read('ppt/slides/slide3.xml').decode())

    def test_final_agenda_drives_people_and_stale_agenda_blocks_seat_cards(self):
        self.data['host']='张明'
        self.data['agenda']=[{'time':'09:00','item':'主持人：张明 教授 示例医院','speaker':'','note':''},
          {'time':'09:15','item':'讨论','speaker':'王 强 教授、李华 教授','note':'主持人张明引导讨论'},
          {'time':'10:00','item':'茶歇','speaker':'全体','note':''}]
        self.a.put(f'/api/meetings/{self.mid}',json={'title':'测试会议','data':self.data})
        people=self.a.get(f'/api/meetings/{self.mid}/agenda-people').json
        self.assertEqual(people['names'],['张明','王强','李华'])
        final=self.a.post(f'/api/meetings/{self.mid}/finalize-agenda').json
        self.assertEqual(final['people']['names'],people['names'])
        saved=self.a.get(f'/api/meetings/{self.mid}').json['data']
        self.assertEqual(saved['guests'],'张明\n王强\n李华')
        self.assertEqual(saved['agenda'],saved['final_agenda'])
        saved['agenda'][1]['speaker']='新老师'
        self.a.put(f'/api/meetings/{self.mid}',json={'title':'测试会议','data':saved})
        denied=self.a.get(f'/api/meetings/{self.mid}/export/final-cards.pdf')
        self.assertEqual(denied.status_code,400); self.assertIn('重新确认',denied.json['error'])

    def test_explicitly_shared_library_is_selectable_but_meetings_remain_private(self):
        def png():
            output=io.BytesIO(); Image.new('RGB',(50,70),'#b4c8e0').save(output,'PNG');output.seek(0);return output
        p=self.a.post('/api/library/projects',data={'name':'共享项目','organization':'共享协会','logo':(png(),'logo.png')},content_type='multipart/form-data').json['id']
        k=self.a.post('/api/library/kvs',data={'name':'共享 KV','agenda':(png(),'agenda.png')},content_type='multipart/form-data').json['id']
        self.assertEqual(self.b.get('/api/library').json['projects'],[])
        self.assertEqual(self.a.put(f'/api/library/projects/{p}',data={'name':'共享项目','organization':'共享协会','shared':'on'},content_type='multipart/form-data').status_code,200)
        self.assertEqual(self.a.put(f'/api/library/kvs/{k}',data={'name':'共享 KV','shared':'on'},content_type='multipart/form-data').status_code,200)
        visible=self.b.get('/api/library').json
        self.assertEqual(visible['projects'][0]['name'],'共享项目');self.assertFalse(visible['projects'][0]['editable'])
        response=self.b.get('/api/library/assets/'+str(visible['projects'][0]['logo_asset_id']))
        self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(self.b.put(f'/api/library/projects/{p}',data={'name':'不能修改'},content_type='multipart/form-data').status_code,404)
        sid=self.b.post('/api/series',json={'name':'员工自己的系列'}).json['id']
        mid=self.b.post('/api/meetings',json={'series_id':sid,'title':'员工会议'}).json['id']
        self.assertEqual(self.b.post(f'/api/meetings/{mid}/library',json={'project_id':p,'kv_id':k}).status_code,200)
        copied=self.b.get(f'/api/meetings/{mid}').json['data']
        self.assertEqual(copied['project_name'],'共享项目');self.assertTrue(copied['logo_file_id']);self.assertTrue(copied['kv_agenda_file_id'])
        self.assertEqual(self.a.get(f'/api/meetings/{mid}').status_code,404)
        self.a.put(f'/api/library/projects/{p}',data={'name':'共享项目','organization':'共享协会'},content_type='multipart/form-data')
        self.a.put(f'/api/library/kvs/{k}',data={'name':'共享 KV'},content_type='multipart/form-data')
        self.assertEqual(self.b.get('/api/library').json['projects'],[])
        self.assertEqual(self.b.get('/api/library/assets/'+str(visible['projects'][0]['logo_asset_id'])).status_code,404)
        response=self.b.get('/api/files/'+str(copied['logo_file_id']))
        self.assertEqual(response.status_code,200);response.close()

if __name__=='__main__': unittest.main(verbosity=2)
