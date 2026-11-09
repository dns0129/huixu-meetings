from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash
from PIL import Image, ImageFont, ImageOps, UnidentifiedImageError
from docx import Document
from openpyxl import load_workbook

from materials import agenda_word, agenda_excel, script_word, render_material, card_archive, missing_questions, make_script, agenda_people, material_dimensions, material_size
import pi_bridge
import image_bridge
from kv_materials import agenda_kv, folded_cards

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('MEETING_DATA_DIR', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
SECRET_FILE = DATA / '.secret'
if not SECRET_FILE.exists():
    try:
        fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
app = Flask(__name__, static_folder='static')
app.secret_key = SECRET_FILE.read_text().strip()
app.config.update(MAX_CONTENT_LENGTH=64 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Strict', PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14)
DB_PATH = DATA / 'meetings.sqlite3'
JOBS = {}
JOBS_LOCK = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_db():
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE, password TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS series(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS meetings(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), series_id INTEGER NOT NULL REFERENCES series(id), title TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}', updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), meeting_id INTEGER NOT NULL REFERENCES meetings(id), kind TEXT NOT NULL, original_name TEXT NOT NULL, disk_name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS library_assets(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL, original_name TEXT NOT NULL, disk_name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS library_projects(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, organization TEXT NOT NULL DEFAULT '', logo_asset_id INTEGER REFERENCES library_assets(id));
        CREATE TABLE IF NOT EXISTS library_kvs(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, assets TEXT NOT NULL DEFAULT '{}');
        ''')
        columns={r['name'] for r in conn.execute('PRAGMA table_info(series)')}
        if 'template' not in columns:
            conn.execute("ALTER TABLE series ADD COLUMN template TEXT NOT NULL DEFAULT '{}'")
        for table in ('library_projects','library_kvs'):
            columns={r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
            if 'shared' not in columns: conn.execute(f'ALTER TABLE {table} ADD COLUMN shared INTEGER NOT NULL DEFAULT 0')
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def error(message, code=400):
    return jsonify({'error': message}), code


def auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return error('请先登录', 401)
        return f(*args, **kwargs)
    return wrapper


def meeting_or_404(mid):
    with db() as conn:
        row = conn.execute('SELECT m.*, s.name AS series_name FROM meetings m JOIN series s ON s.id=m.series_id WHERE m.id=? AND m.user_id=? AND s.user_id=?', (mid, session['user_id'], session['user_id'])).fetchone()
    if not row:
        abort(404)
    result = dict(row)
    result['data'] = json.loads(result['data'])
    return result


def get_file(fid, user_id=None, mid=None):
    uid = user_id or session['user_id']
    with db() as conn:
        row = conn.execute('SELECT * FROM files WHERE id=? AND user_id=?', (fid, uid)).fetchone()
    if not row or (mid is not None and row['meeting_id'] != mid):
        abort(404)
    return dict(row)


def file_path(file_row):
    return DATA / 'uploads' / str(file_row['user_id']) / file_row['disk_name']


def validate_data(raw):
    # Known fields only; limit storage and avoid leaking unexpected client-supplied paths.
    if not isinstance(raw, dict):
        raise ValueError('资料格式不正确')
    text_fields = ['date','time','location','organizer','host','subtitle','baseline','guests','script','notes','image_prompt','project_name','association']
    out = {k: str(raw.get(k, '') or '')[:100000 if k == 'baseline' else 30000 if k == 'script' else 3000] for k in text_fields}
    agenda = raw.get('agenda', [])
    if not isinstance(agenda, list) or len(agenda) > 200:
        raise ValueError('日程格式不正确')
    out['agenda'] = [{k: str(row.get(k,'') or '')[:500] for k in ('time','item','speaker','note')} for row in agenda if isinstance(row, dict)]
    final_agenda = raw.get('final_agenda', [])
    if not isinstance(final_agenda,list) or len(final_agenda)>200: raise ValueError('最终日程格式不正确')
    out['final_agenda'] = [{k: str(row.get(k,'') or '')[:500] for k in ('time','item','speaker','note')} for row in final_agenda if isinstance(row,dict)]
    profiles=raw.get('profiles',[])
    if not isinstance(profiles,list) or len(profiles)>200: raise ValueError('嘉宾资料格式不正确')
    out['profiles']=[]
    for profile in profiles:
        if not isinstance(profile,dict): continue
        item={k:str(profile.get(k,'') or '')[:3000 if k=='bio' else 200] for k in ('name','organization','bio')}
        value=profile.get('photo_file_id'); item['photo_file_id']=int(value) if str(value or '').isdigit() else None
        out['profiles'].append(item)
    design = raw.get('design', {}) if isinstance(raw.get('design', {}), dict) else {}
    out['design'] = {}
    for kind in ('poster','banner','card'):
        item = design.get(kind, {}) if isinstance(design.get(kind, {}), dict) else {}
        defaults = {'poster':(210,297), 'banner':(800,2000), 'card':(210,100)}
        w,h=defaults[kind]
        try:
            w=float(item.get('width',w)); h=float(item.get('height',h))
            if not (30 <= w <= 5000 and 30 <= h <= 5000):
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError('尺寸须在 30–5000 毫米之间')
        font = item.get('font', 'hei')
        palette = item.get('palette', 'blue')
        if font not in ('hei','song','round','custom'): font = 'hei'
        if palette not in ('blue','forest','wine'): palette = 'blue'
        out['design'][kind] = {'width': w, 'height': h, 'font':font, 'palette':palette}
        elements=item.get('elements')
        if elements is not None:
            if not isinstance(elements,list) or len(elements)>50: raise ValueError('物料图层格式不正确')
            cleaned=[]
            for layer in elements:
                if not isinstance(layer,dict) or layer.get('type') not in ('text','logo'): raise ValueError('物料图层类型不正确')
                try:
                    x,y,lw,lh=(float(layer.get(k)) for k in ('x','y','w','h'))
                    size=float(layer.get('size',.05))
                    if not (0<=x<=.98 and 0<=y<=.98 and .02<=lw<=1-x+.0001 and .02<=lh<=1-y+.0001 and .008<=size<=.4): raise ValueError()
                except (TypeError,ValueError): raise ValueError('图层位置或尺寸不正确')
                color=str(layer.get('color','#222222'))
                if not re.fullmatch(r'#[0-9a-fA-F]{6}',color): raise ValueError('文字颜色不正确')
                cleaned.append({'type':layer['type'],'text':str(layer.get('text',''))[:2000], 'bind':'guest' if layer.get('bind')=='guest' else '', 'x':x,'y':y,'w':lw,'h':lh,'size':size,'color':color,'align':layer.get('align') if layer.get('align') in ('left','center','right') else 'center'})
            out['design'][kind]['elements']=cleaned
    for key in ('logo_file_id','background_file_id','font_file_id','poster_kv_file_id','banner_kv_file_id','card_kv_file_id','kv_agenda_file_id','kv_slide_file_id','kv_cover_file_id','kv_bio_file_id','kv_card_file_id','library_project_id','library_kv_id'):
        value = raw.get(key)
        out[key] = int(value) if str(value or '').isdigit() else None
    return out


def validate_owned_files(data, mid):
    for key, kind in [('logo_file_id', 'logo'), ('background_file_id','background'), ('font_file_id','font'),('poster_kv_file_id','background'),('banner_kv_file_id','background'),('card_kv_file_id','background'),('kv_agenda_file_id','kv_agenda'),('kv_slide_file_id','kv_slide'),('kv_cover_file_id','kv_cover'),('kv_bio_file_id','kv_bio'),('kv_card_file_id','kv_card')]:
        if data.get(key):
            f = get_file(data[key], mid=mid)
            if f['kind'] != kind:
                raise ValueError('图片类型不匹配')
    for profile in data.get('profiles',[]):
        if profile.get('photo_file_id'):
            f=get_file(profile['photo_file_id'],mid=mid)
            if f['kind']!='portrait': raise ValueError('嘉宾照片类型不匹配')


@app.before_request
def local_origin():
    if request.method in ('POST','PUT','PATCH','DELETE'):
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            return error('请求来源不匹配', 403)


@app.errorhandler(413)
def too_large(_):
    return error('文件过大，单次上传最多 64 MB', 413)


@app.errorhandler(404)
def missing(_):
    return error('内容不存在或无权访问', 404)


@app.get('/')
def index():
    return send_file(ROOT / 'templates' / 'index.html')


@app.get('/api/session')
def session_info():
    return jsonify({'user': {'id':session.get('user_id'), 'username': session.get('username')} if session.get('user_id') else None})


@app.post('/api/register')
def register():
    d=request.get_json(silent=True) or {}
    username=str(d.get('username','')).strip()
    password=str(d.get('password',''))
    if not 2 <= len(username) <= 40 or not 8 <= len(password) <= 128:
        return error('账号请填写 2–40 个字符，密码至少 8 位')
    try:
        with db() as conn:
            cur=conn.execute('INSERT INTO users(username,password) VALUES(?,?)', (username,generate_password_hash(password)))
            uid=cur.lastrowid
    except sqlite3.IntegrityError:
        return error('这个账号已存在，请直接登录')
    session.clear(); session['user_id']=uid; session['username']=username; session.permanent=True
    return jsonify({'user':{'id':uid,'username':username}})


@app.post('/api/login')
def login():
    d=request.get_json(silent=True) or {}
    with db() as conn:
        row=conn.execute('SELECT * FROM users WHERE username=?', (str(d.get('username','')).strip(),)).fetchone()
    if not row or not check_password_hash(row['password'],str(d.get('password',''))):
        return error('账号或密码不正确',401)
    session.clear(); session['user_id']=row['id']; session['username']=row['username']; session.permanent=True
    return jsonify({'user':{'id':row['id'],'username':row['username']}})


@app.post('/api/logout')
def logout():
    session.clear()
    return jsonify({'ok':True})


@app.get('/api/series')
@auth_required
def list_series():
    with db() as conn:
        series = [dict(r) for r in conn.execute('SELECT s.*, COUNT(m.id) AS meeting_count FROM series s LEFT JOIN meetings m ON m.series_id=s.id AND m.user_id=s.user_id WHERE s.user_id=? GROUP BY s.id ORDER BY s.id DESC',(session['user_id'],))]
        meetings = [dict(r) for r in conn.execute('SELECT m.id,m.series_id,m.title,m.data,m.updated_at,s.name AS series_name FROM meetings m JOIN series s ON s.id=m.series_id WHERE m.user_id=? AND s.user_id=? ORDER BY m.id DESC',(session['user_id'],session['user_id']))]
    for m in meetings:
        data=json.loads(m.pop('data')); m['date']=data.get('date',''); m['location']=data.get('location','')
    return jsonify({'series':series,'meetings':meetings})


def read_library_image(incoming):
    if not incoming or not incoming.filename: return None
    name=Path(incoming.filename).name[:200]
    content=incoming.read()
    if not content: raise ValueError('图片文件为空')
    try:
        with Image.open(io.BytesIO(content)) as img:
            if img.format not in ('PNG','JPEG','WEBP') or img.width*img.height>50_000_000:
                raise ValueError('图片请使用不超过 5000 万像素的 PNG、JPG 或 WebP')
            ext={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}[img.format]
            img.verify()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):
        raise ValueError('图片无法读取或尺寸过大') from None
    return name,content,ext


def store_library_image(conn,uid,kind,image):
    if image is None: return None
    name,content,ext=image
    folder=DATA/'uploads'/str(uid); folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    disk=uuid.uuid4().hex+ext
    (folder/disk).write_bytes(content); os.chmod(folder/disk,0o600)
    return conn.execute('INSERT INTO library_assets(user_id,kind,original_name,disk_name) VALUES(?,?,?,?)',(uid,kind,name,disk)).lastrowid


@app.get('/api/library')
@auth_required
def get_library():
    uid=session['user_id']
    with db() as conn:
        projects=[dict(r) for r in conn.execute('SELECT id,user_id,name,organization,logo_asset_id,shared FROM library_projects WHERE user_id=? OR shared=1 ORDER BY id DESC',(uid,))]
        kvs=[dict(r) for r in conn.execute('SELECT id,user_id,name,assets,shared FROM library_kvs WHERE user_id=? OR shared=1 ORDER BY id DESC',(uid,))]
    for item in projects+kvs:
        item['editable']=item.pop('user_id')==uid; item['shared']=bool(item['shared'])
    for kv in kvs: kv['assets']=json.loads(kv['assets'])
    return jsonify({'projects':projects,'kvs':kvs})


@app.route('/api/library/projects',methods=['POST'])
@app.route('/api/library/projects/<int:pid>',methods=['PUT'])
@auth_required
def save_library_project(pid=None):
    uid=session['user_id']; name=str(request.form.get('name','')).strip()[:150]
    organization=str(request.form.get('organization','')).strip()[:150]; shared=int(request.form.get('shared')=='on')
    if not name: return error('请填写项目名称')
    try: logo=read_library_image(request.files.get('logo'))
    except ValueError as e: return error(str(e))
    with db() as conn:
        current=conn.execute('SELECT * FROM library_projects WHERE id=? AND user_id=?',(pid,uid)).fetchone() if pid else None
        if pid and not current: return error('项目不存在',404)
        logo_id=store_library_image(conn,uid,'logo',logo) if logo else (current['logo_asset_id'] if current else None)
        if current:
            conn.execute('UPDATE library_projects SET name=?,organization=?,logo_asset_id=?,shared=? WHERE id=? AND user_id=?',(name,organization,logo_id,shared,pid,uid))
        else:
            pid=conn.execute('INSERT INTO library_projects(user_id,name,organization,logo_asset_id,shared) VALUES(?,?,?,?,?)',(uid,name,organization,logo_id,shared)).lastrowid
    return jsonify({'id':pid})


@app.route('/api/library/kvs',methods=['POST'])
@app.route('/api/library/kvs/<int:kid>',methods=['PUT'])
@auth_required
def save_library_kv(kid=None):
    uid=session['user_id']; name=str(request.form.get('name','')).strip()[:150]; shared=int(request.form.get('shared')=='on')
    if not name: return error('请填写 KV 名称')
    try: images={kind:read_library_image(request.files.get(kind)) for kind in ('agenda','slide','cover','bio','card')}
    except ValueError as e: return error(str(e))
    with db() as conn:
        current=conn.execute('SELECT * FROM library_kvs WHERE id=? AND user_id=?',(kid,uid)).fetchone() if kid else None
        if kid and not current: return error('KV 不存在',404)
        assets=json.loads(current['assets']) if current else {}
        for kind,image in images.items():
            if image: assets[kind]=store_library_image(conn,uid,'kv_'+kind,image)
        if not assets: return error('请至少上传一张 KV 图片')
        if current:
            conn.execute('UPDATE library_kvs SET name=?,assets=?,shared=? WHERE id=? AND user_id=?',(name,json.dumps(assets),shared,kid,uid))
        else:
            kid=conn.execute('INSERT INTO library_kvs(user_id,name,assets,shared) VALUES(?,?,?,?)',(uid,name,json.dumps(assets),shared)).lastrowid
    return jsonify({'id':kid})


@app.get('/api/library/assets/<int:aid>')
@auth_required
def get_library_asset(aid):
    uid=session['user_id']
    with db() as conn:
        row=conn.execute('SELECT * FROM library_assets WHERE id=?',(aid,)).fetchone()
        allowed=bool(row and row['user_id']==uid)
        if row and not allowed:
            allowed=bool(conn.execute('SELECT 1 FROM library_projects WHERE user_id=? AND logo_asset_id=? AND shared=1',(row['user_id'],aid)).fetchone())
            if not allowed:
                allowed=any(aid in json.loads(r['assets']).values() for r in conn.execute('SELECT assets FROM library_kvs WHERE user_id=? AND shared=1',(row['user_id'],)))
    if not row or not allowed: abort(404)
    return send_file(DATA/'uploads'/str(row['user_id'])/row['disk_name'],conditional=True,download_name=row['original_name'])


@app.post('/api/meetings/<int:mid>/library')
@auth_required
def apply_library(mid):
    meeting=meeting_or_404(mid); uid=session['user_id']; body=request.get_json(silent=True) or {}
    if not isinstance(body,dict): return error('请求格式不正确')
    project_id=body.get('project_id'); kv_id=body.get('kv_id')
    for value in (project_id,kv_id):
        if value is not None and value!='' and not str(value).isdigit(): return error('项目或 KV 编号不正确')
    project_id=int(project_id) if str(project_id or '').isdigit() else None
    kv_id=int(kv_id) if str(kv_id or '').isdigit() else None
    if not project_id and not kv_id: return error('请选择项目或 KV')
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        project=conn.execute('SELECT * FROM library_projects WHERE id=? AND (user_id=? OR shared=1)',(project_id,uid)).fetchone() if project_id else None
        kv=conn.execute('SELECT * FROM library_kvs WHERE id=? AND (user_id=? OR shared=1)',(kv_id,uid)).fetchone() if kv_id else None
        if project_id and not project: return error('项目不存在',404)
        if kv_id and not kv: return error('KV 不存在',404)
        data=meeting['data']
        copied=[]
        def attach(aid,kind,owner):
            if not aid: return None
            asset=conn.execute('SELECT * FROM library_assets WHERE id=? AND user_id=? AND kind=?',(aid,owner,kind)).fetchone()
            if not asset: raise ValueError('项目素材不存在，请重新上传')
            disk=asset['disk_name']
            if owner!=uid:
                source=DATA/'uploads'/str(owner)/disk
                folder=DATA/'uploads'/str(uid);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                disk=uuid.uuid4().hex+Path(disk).suffix
                target=folder/disk
                copied.append(target)
                try: shutil.copyfile(source,target);os.chmod(target,0o600)
                except OSError: raise ValueError('共享素材无法读取，请联系素材创建者。') from None
            return conn.execute('INSERT INTO files(user_id,meeting_id,kind,original_name,disk_name) VALUES(?,?,?,?,?)',(uid,mid,kind,asset['original_name'],disk)).lastrowid
        try:
            if project:
                data.update({'library_project_id':project['id'],'project_name':project['name'],'association':project['organization'],
                             'logo_file_id':attach(project['logo_asset_id'],'logo',project['user_id'])})
                if project['organization']: data['organizer']=project['organization']
            if kv:
                assets=json.loads(kv['assets']); data['library_kv_id']=kv['id']
                for kind in ('agenda','slide','cover','bio','card'):
                    data['kv_'+kind+'_file_id']=attach(assets.get(kind),'kv_'+kind,kv['user_id'])
                for kind in ('poster','banner','card'):
                    data[kind+'_kv_file_id']=None
        except ValueError as e:
            conn.rollback()
            for path in copied: path.unlink(missing_ok=True)
            return error(str(e))
        conn.execute('UPDATE meetings SET data=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(json.dumps(data,ensure_ascii=False),mid,uid))
    return jsonify({'ok':True})


@app.post('/api/series')
@auth_required
def create_series():
    d=request.get_json(silent=True) or {}
    name=str(d.get('name','')).strip()[:100]
    if not name: return error('请填写系列名称')
    with db() as conn:
        cur=conn.execute('INSERT INTO series(user_id,name,description) VALUES(?,?,?)',(session['user_id'],name,str(d.get('description','')).strip()[:500]))
        sid=cur.lastrowid
    return jsonify({'id':sid})


@app.post('/api/meetings')
@auth_required
def create_meeting():
    d=request.get_json(silent=True) or {}
    title=str(d.get('title','')).strip()[:150]
    try: sid=int(d.get('series_id'))
    except (ValueError, TypeError): return error('请选择会议系列')
    if not title: return error('请填写会议名称')
    with db() as conn:
        series=conn.execute('SELECT * FROM series WHERE id=? AND user_id=?',(sid,session['user_id'])).fetchone()
        if not series: return error('会议系列不存在',404)
        initial=validate_data({})
        template=json.loads(series['template'] or '{}')
        if isinstance(template.get('design'),dict): initial['design']=template['design']
        for key in ('project_name','association','library_project_id','library_kv_id'):
            if template.get(key) is not None: initial[key]=template[key]
        if template.get('association'): initial['organizer']=template['association']
        cur=conn.execute('INSERT INTO meetings(user_id,series_id,title,data) VALUES(?,?,?,?)',(session['user_id'],sid,title,json.dumps(initial,ensure_ascii=False)))
        mid=cur.lastrowid
        for key in ('logo_file_id','background_file_id','font_file_id','poster_kv_file_id','banner_kv_file_id','card_kv_file_id','kv_agenda_file_id','kv_slide_file_id','kv_cover_file_id','kv_bio_file_id','kv_card_file_id'):
            fid=template.get(key)
            source=conn.execute('SELECT * FROM files WHERE id=? AND user_id=?',(fid,session['user_id'])).fetchone() if fid else None
            if source:
                new_file=conn.execute('INSERT INTO files(user_id,meeting_id,kind,original_name,disk_name) VALUES(?,?,?,?,?)',(session['user_id'],mid,source['kind'],source['original_name'],source['disk_name']))
                initial[key]=new_file.lastrowid
        conn.execute('UPDATE meetings SET data=? WHERE id=?',(json.dumps(initial,ensure_ascii=False),mid))
    return jsonify({'id':mid})


@app.post('/api/series/<int:sid>/template')
@auth_required
def save_series_template(sid):
    payload=request.get_json(silent=True) or {}
    try: mid=int(payload.get('meeting_id'))
    except (TypeError,ValueError): return error('会议编号不正确')
    meeting=meeting_or_404(mid)
    if meeting['series_id'] != sid: return error('会议不属于这个系列',404)
    d=meeting['data']
    try: validate_owned_files(d,mid)
    except ValueError as e: return error(str(e))
    template={k:d.get(k) for k in ('design','logo_file_id','background_file_id','font_file_id','poster_kv_file_id','banner_kv_file_id','card_kv_file_id','project_name','association','library_project_id','library_kv_id','kv_agenda_file_id','kv_slide_file_id','kv_cover_file_id','kv_bio_file_id','kv_card_file_id')}
    with db() as conn:
        conn.execute('UPDATE series SET template=? WHERE id=? AND user_id=?',(json.dumps(template,ensure_ascii=False),sid,session['user_id']))
    return jsonify({'ok':True})


@app.get('/api/meetings/<int:mid>')
@auth_required
def get_meeting(mid):
    item=meeting_or_404(mid)
    with db() as conn:
        files=[dict(r) for r in conn.execute('SELECT id,kind,original_name,created_at FROM files WHERE user_id=? AND meeting_id=? ORDER BY id DESC',(session['user_id'],mid))]
    item['files']=files
    return jsonify(item)


@app.put('/api/meetings/<int:mid>')
@auth_required
def update_meeting(mid):
    meeting_or_404(mid)
    d=request.get_json(silent=True) or {}
    title=str(d.get('title','')).strip()[:150]
    if not title: return error('请填写会议名称')
    try:
        data=validate_data(d.get('data',{})); validate_owned_files(data,mid)
    except (ValueError,TypeError) as e:
        return error(str(e))
    with db() as conn:
        conn.execute('UPDATE meetings SET title=?,data=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(title,json.dumps(data,ensure_ascii=False),mid,session['user_id']))
    return jsonify({'ok':True,'questions':missing_questions(title,data)})


def extract_text(name, content):
    suffix=Path(name).suffix.lower()
    if suffix in ('.txt','.md','.csv'):
        for encoding in ('utf-8-sig','gb18030'):
            try: return content.decode(encoding)[:100000]
            except UnicodeDecodeError: pass
        raise ValueError('无法识别文件编码，请使用 UTF-8 文本')
    if suffix == '.docx':
        doc=Document(io.BytesIO(content))
        parts=[p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            parts.extend(' | '.join(cell.text.replace('\n',' ') for cell in row.cells) for row in table.rows)
        return '\n'.join(parts)[:100000]
    if suffix == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError:
            # The service can also be started directly with the system Python;
            # keep its PDF reader available from this project's own venv.
            site=ROOT/'.venv'/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
            if site.is_dir() and str(site) not in sys.path: sys.path.append(str(site))
            try: from pypdf import PdfReader
            except ImportError: raise ValueError('PDF 支持未安装，请使用“启动会序.command”安装项目依赖。') from None
        reader=PdfReader(io.BytesIO(content))
        if reader.is_encrypted: raise ValueError('请先解除 PDF 的密码保护。')
        if len(reader.pages)>200: raise ValueError('PDF 底稿最多支持 200 页。')
        return '\n'.join((page.extract_text() or '') for page in reader.pages)[:100000]
    if suffix == '.xlsx':
        wb=load_workbook(io.BytesIO(content),read_only=True,data_only=True)
        parts=[]
        for sheet in wb.worksheets:
            parts.append(f'【{sheet.title}】')
            for row in sheet.iter_rows(max_row=min(sheet.max_row,2000),values_only=True):
                line=' | '.join(str(v) if v is not None else '' for v in row).strip(' |')
                if line: parts.append(line)
                if sum(map(len, parts)) > 100000: break
        wb.close()
        return '\n'.join(parts)[:100000]
    raise ValueError('支持 TXT、CSV、PDF、Word（.docx）和 Excel（.xlsx）文件')


@app.post('/api/meetings/<int:mid>/upload')
@auth_required
def upload(mid):
    meeting_or_404(mid)
    kind=request.form.get('kind','source')
    if kind not in ('source','logo','background','font','portrait'): return error('文件类型不正确')
    incoming=request.files.get('file')
    if not incoming or not incoming.filename: return error('请选择文件')
    name=Path(incoming.filename).name[:200]
    content=incoming.read()
    if not content: return error('文件为空')
    text=''
    if kind == 'source':
        try: text=extract_text(name,content)
        except Exception as e: return error('无法读取该底稿：'+str(e)[:160])
        if not text.strip(): return error('文件中没有可读取的文字')
        ext=Path(name).suffix.lower()
    elif kind == 'font':
        ext=Path(name).suffix.lower()
        if ext not in ('.ttf','.otf','.ttc'): return error('字体请使用 TTF、OTF 或 TTC 文件')
        try: ImageFont.truetype(io.BytesIO(content),24)
        except (OSError, ValueError): return error('无法读取这个字体文件')
    else:
        try:
            img=Image.open(io.BytesIO(content)); img.verify()
            if img.format not in ('PNG','JPEG','WEBP'): return error('图片请使用 PNG、JPG 或 WebP')
            ext={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}[img.format]
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            return error('图片格式不正确或尺寸过大')
    folder=DATA / 'uploads' / str(session['user_id']); folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    disk_name=uuid.uuid4().hex+ext
    (folder/disk_name).write_bytes(content)
    os.chmod(folder/disk_name,0o600)
    with db() as conn:
        cur=conn.execute('INSERT INTO files(user_id,meeting_id,kind,original_name,disk_name) VALUES(?,?,?,?,?)',(session['user_id'],mid,kind,name,disk_name))
        fid=cur.lastrowid
    return jsonify({'id':fid,'name':name,'text':text})


@app.get('/api/files/<int:fid>')
@auth_required
def serve_file(fid):
    row=get_file(fid)
    return send_file(file_path(row),conditional=True,download_name=row['original_name'])


def owned_asset(data,key,mid):
    if not data.get(key): return None
    return file_path(get_file(data[key],mid=mid))


def material_background(data,kind,mid):
    keys=[kind+'_kv_file_id']
    if data.get('library_kv_id'):
        keys+=['kv_card_file_id','kv_agenda_file_id','kv_cover_file_id'] if kind=='card' else ['kv_agenda_file_id','kv_cover_file_id']
    else: keys+=['background_file_id']
    return next((owned_asset(data,key,mid) for key in keys if data.get(key)),None)


def kv_pixel_size(path):
    try:
        with Image.open(path) as img:
            return img.size[::-1] if img.getexif().get(274) in (5,6,7,8) else img.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError('无法读取当前 KV，请重新上传。') from None


@app.get('/api/meetings/<int:mid>/kv-fit/<kind>')
@auth_required
def kv_fit(mid,kind):
    if kind not in ('poster','banner','card'): abort(404)
    data=meeting_or_404(mid)['data']
    try:
        width,height=material_dimensions(data,kind)
        width=float(request.args.get('width',width));height=float(request.args.get('height',height))
        if not (30<=width<=5000 and 30<=height<=5000): return error('尺寸须在 30–5000 毫米之间')
        target=material_size({'design':{kind:{'width':width,'height':height}}},kind)[:2]
        path=material_background(data,kind,mid)
        source=kv_pixel_size(path) if path else None
    except ValueError as e: return error(str(e))
    return jsonify({'source':source,'target':target,'needs_adaptation':source is not None and source!=target})


def image_target_signature(data,kind):
    size=material_dimensions(data,kind or 'poster')
    if not kind: return (size,data.get('background_file_id'))
    return (size, *(data.get(key) for key in (kind+'_kv_file_id','library_kv_id','kv_agenda_file_id','kv_cover_file_id','kv_card_file_id','background_file_id')))


@app.get('/api/meetings/<int:mid>/questions')
@auth_required
def questions(mid):
    m=meeting_or_404(mid)
    return jsonify({'questions':missing_questions(m['title'],m['data'])})


@app.get('/api/meetings/<int:mid>/agenda-people')
@auth_required
def suggest_agenda_people(mid):
    m=meeting_or_404(mid)
    return jsonify(agenda_people(m['data']))


@app.post('/api/meetings/<int:mid>/finalize-agenda')
@auth_required
def finalize_agenda(mid):
    m=meeting_or_404(mid); d=m['data']
    if not any(row.get('item','').strip() for row in d.get('agenda',[])):
        return error('请先填写会议日程')
    d['final_agenda']=[dict(row) for row in d['agenda']]
    people=agenda_people(d)
    d['guests']='\n'.join(people['names'])
    with db() as conn:
        conn.execute('UPDATE meetings SET data=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(json.dumps(d,ensure_ascii=False),mid,session['user_id']))
    return jsonify({'ok':True,'people':people})


@app.post('/api/meetings/<int:mid>/draft-script')
@auth_required
def draft_script(mid):
    m=meeting_or_404(mid)
    return jsonify({'script':make_script(m['title'],m['data'])})


@app.get('/api/meetings/<int:mid>/export/<kind>')
@auth_required
def export(mid,kind):
    m=meeting_or_404(mid); data=m['data']; title=m['title']
    if kind == 'agenda.xlsx':
        file=agenda_excel(title,data); mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'; suffix='会议日程.xlsx'
    elif kind == 'agenda.docx':
        file=agenda_word(title,data); mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'; suffix='会议日程.docx'
    elif kind == 'script.docx':
        file=script_word(title,data); mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'; suffix='主持串词.docx'
    elif kind in ('agenda-kv.png','agenda-kv.pdf'):
        try: file=agenda_kv(title,data,owned_asset(data,'kv_agenda_file_id',mid),owned_asset(data,'logo_file_id',mid),fmt=kind.rsplit('.',1)[1])
        except ValueError as e: return error(str(e))
        mime='application/pdf' if kind.endswith('.pdf') else 'image/png'; suffix='KV会议日程.'+kind.rsplit('.',1)[1]
    elif kind == 'final-cards.pdf':
        if not data.get('final_agenda') or data['final_agenda'] != data.get('agenda'):
            return error('日程尚未定稿或定稿后已修改，请重新确认最终日程。')
        try: file=folded_cards(data,owned_asset(data,'kv_card_file_id',mid),owned_asset(data,'logo_file_id',mid))
        except ValueError as e: return error(str(e))
        mime='application/pdf'; suffix='最终日程席卡.pdf'
    elif kind == 'transition.pptx':
        slide=owned_asset(data,'kv_slide_file_id',mid)
        if not slide: return error('请先选择包含串场底图的 KV。')
        if not any(str(row.get('item','')).strip() for row in data.get('agenda',[])): return error('请先填写会议日程。')
        if len(data.get('agenda',[]))>100: return error('单次最多生成 100 个日程环节的串场。')
        with tempfile.TemporaryDirectory(prefix='huixu-slides-') as folder:
            output=Path(folder)/'transition.pptx'
            cover=owned_asset(data,'kv_cover_file_id',mid); bio=owned_asset(data,'kv_bio_file_id',mid); logo=owned_asset(data,'logo_file_id',mid)
            profile_images={}
            for profile in data.get('profiles',[]):
                fid=profile.get('photo_file_id')
                if fid:
                    row=get_file(fid,mid=mid)
                    if row['kind']!='portrait': return error('嘉宾照片类型不匹配')
                    profile_images[str(fid)]=str(file_path(row))
            payload={'meeting':{'title':title,'data':data},'slideBackground':str(slide),
                     'coverBackground':str(cover) if cover else None,'bioBackground':str(bio) if bio else None,'profileImages':profile_images,'logo':str(logo) if logo else None,
                     'divider':str(ROOT/'static'/'assets'/'参考模板-分隔线.png'),'output':str(output)}
            try:
                proc=subprocess.run(['node',str(ROOT/'transition_deck.mjs')],input=json.dumps(payload,ensure_ascii=False),text=True,capture_output=True,cwd=ROOT,timeout=180)
                if proc.returncode or not output.is_file(): raise ValueError()
                file=io.BytesIO(output.read_bytes())
            except (OSError,ValueError,subprocess.TimeoutExpired):
                return error('串场生成失败，请检查 Node.js 和本机演示文稿组件后重试。',503)
        mime='application/vnd.openxmlformats-officedocument.presentationml.presentation'; suffix='会议串场.pptx'
    elif kind in ('poster.png','poster.pdf','banner.png','banner.pdf','card.png','card.pdf','cards.zip'):
        logo=owned_asset(data,'logo_file_id',mid); bg=material_background(data,'card' if kind=='cards.zip' else kind.split('.')[0],mid)
        try:
            if kind == 'cards.zip':
                file=card_archive(title,data,logo,bg,owned_asset(data,'font_file_id',mid)); mime='application/zip'; suffix='桌卡.zip'
            else:
                typ,fmt=kind.split('.')
                name=request.args.get('name','').strip()[:80]
                file=render_material(title,data,typ,logo,bg,fmt=fmt,name=name,font_path=owned_asset(data,'font_file_id',mid))
                mime='application/pdf' if fmt=='pdf' else 'image/png'
                suffix={'poster':'海报','banner':'易拉宝','card':'桌卡'}[typ]+'.'+fmt
        except ValueError as e: return error(str(e))
    else: return error('不支持的文件类型',404)
    return send_file(file,mimetype=mime,as_attachment=True,download_name=title[:60]+'-'+suffix)


@app.get('/api/meetings/<int:mid>/preview/<kind>')
@auth_required
def preview(mid,kind):
    if kind not in ('poster','banner','card','agenda-kv'): abort(404)
    m=meeting_or_404(mid); d=m['data']
    try:
        if kind=='agenda-kv': output=agenda_kv(m['title'],d,owned_asset(d,'kv_agenda_file_id',mid),owned_asset(d,'logo_file_id',mid))
        else: output=render_material(m['title'],d,kind,owned_asset(d,'logo_file_id',mid),material_background(d,kind,mid),fmt='png',preview=True,name=request.args.get('name','')[:80],font_path=owned_asset(d,'font_file_id',mid))
    except ValueError as e: return error(str(e))
    return send_file(output,mimetype='image/png',max_age=0)


@app.get('/api/pi/status')
@auth_required
def pi_status():
    return jsonify(pi_bridge.status(ROOT, DATA, session['user_id']))


@app.post('/api/pi/login')
@auth_required
def pi_login():
    try: return jsonify(pi_bridge.launch_login(ROOT,DATA,session['user_id']))
    except (OSError, ValueError) as e: return error(str(e))


@app.get('/api/image-providers')
@auth_required
def image_provider_status():
    try: return jsonify(image_bridge.status(DATA, session['user_id']))
    except ValueError as e: return error(str(e))


@app.route('/api/image-providers/<tier>', methods=['PUT', 'DELETE'])
@auth_required
def image_provider_settings(tier):
    try:
        if request.method == 'DELETE':
            return jsonify(image_bridge.remove(DATA, session['user_id'], tier))
        values = request.get_json(silent=True)
        return jsonify(image_bridge.save(DATA, session['user_id'], tier, values))
    except ValueError as e:
        return error(str(e))
    except OSError:
        return error('无法保存生图服务配置，请检查本地数据目录权限。', 500)


@app.post('/api/meetings/<int:mid>/ai/<action>')
@auth_required
def ai_action(mid,action):
    if action not in ('analyze','image','script'): abort(404)
    meeting=meeting_or_404(mid)
    extra=request.get_json(silent=True) or {}
    if not isinstance(extra,dict): return error('请求格式不正确')
    tier=extra.get('tier','chatgpt') if action == 'image' else None
    image_kind=extra.get('kind') if action=='image' else None
    if image_kind is not None and image_kind not in ('poster','banner','card'): return error('该物料暂不支持生成 KV')
    image_field=(image_kind+'_kv_file_id') if image_kind else 'background_file_id'
    original_image=image_target_signature(meeting['data'],image_kind) if action=='image' else None
    reference_path=None
    if action=='image' and extra.get('adapt') is True:
        if not image_kind: return error('请先选择要适配的物料。')
        if tier!='chatgpt': return error('KV 尺寸适配请使用 ChatGPT。')
        reference_path=material_background(meeting['data'],image_kind,mid)
        if not reference_path: return error('请先上传或选择 KV。')
        try:
            if kv_pixel_size(reference_path)==material_size(meeting['data'],image_kind)[:2]: return error('当前 KV 已符合物料尺寸。')
        except ValueError as e: return error(str(e))
    provider_credentials=None
    if action == 'image' and tier != 'chatgpt':
        try: provider_credentials=image_bridge.credentials(DATA,session['user_id'],tier)
        except ValueError as e: return error(str(e))
    else:
        stat=pi_bridge.status(ROOT, DATA, session['user_id'])
        if not stat['installed']: return error('Pi 尚未安装，请参照设置页完成安装',503)
        if not stat['chat_signed_in']: return error('尚未检测到 Pi 的 ChatGPT 文本登录，请先连接账号',401)
        if action == 'image' and not stat['image_signed_in']: return error('尚未检测到 Pi 的生图登录，请在终端输入 /login codex-images',401)
    uid=session['user_id']; job_id=uuid.uuid4().hex
    with JOBS_LOCK:
        if action == 'image':
            active=active_image_job(uid)
            if active: return jsonify(active)
        JOBS[job_id]={'user_id':uid,'action':action,'meeting_id':mid,'status':'running','stage':'generating'}
    def work():
        try:
            if action == 'image' and tier != 'chatgpt':
                result={'bytes':image_bridge.generate(meeting,tier,provider_credentials,extra)}
            elif reference_path:
                result=pi_bridge.run(ROOT,DATA,uid,meeting,action,extra,reference_path=reference_path)
            else:
                result=pi_bridge.run(ROOT,DATA,uid,meeting,action,extra)
            if action == 'image':
                with JOBS_LOCK: JOBS[job_id]['stage']='saving'
                source=io.BytesIO(result['bytes']) if 'bytes' in result else Path(result['path'])
                folder=DATA / 'uploads' / str(uid); folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                disk=uuid.uuid4().hex+'.png'
                # Match the export canvas even when the provider returns another ratio.
                width,height,dpi=material_size(meeting['data'],image_kind or 'poster')
                try:
                    with Image.open(source) as img:
                        kv=ImageOps.fit(ImageOps.exif_transpose(img).convert('RGB'),(width,height),method=Image.Resampling.LANCZOS)
                        kv.save(folder/disk,format='PNG',dpi=(dpi,dpi))
                except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                    raise ValueError('生图服务返回的图片无法读取，本次请求可能已产生费用。') from None
                os.chmod(folder/disk,0o600)
                with db() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    cur=conn.execute('INSERT INTO files(user_id,meeting_id,kind,original_name,disk_name) VALUES(?,?,?,?,?)',(uid,mid,'background','AI 生成背景.png',disk))
                    row=conn.execute('SELECT data FROM meetings WHERE id=? AND user_id=?',(mid,uid)).fetchone()
                    if not row: raise ValueError('原会议已不存在，无法保存生成的背景。')
                    current=json.loads(row['data'])
                    applied=image_target_signature(current,image_kind)==original_image
                    if applied:
                        current[image_field]=cur.lastrowid
                        conn.execute('UPDATE meetings SET data=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',
                                     (json.dumps(current,ensure_ascii=False),mid,uid))
                    result={'file_id':cur.lastrowid,'applied':applied,'kind':image_kind}
            with JOBS_LOCK: JOBS[job_id].update(status='done',result=result)
        except ValueError as e:
            with JOBS_LOCK: JOBS[job_id].update(status='error',message=str(e)[:800])
        except Exception:
            with JOBS_LOCK: JOBS[job_id].update(status='error',message='处理失败，请检查服务配置后重试；生图请求可能已产生费用。')
    try: threading.Thread(target=work,daemon=True).start()
    except RuntimeError:
        with JOBS_LOCK: JOBS[job_id].update(status='error',message='无法启动任务，请稍后重试。')
        return error('无法启动任务，请稍后重试。',503)
    return jsonify({'job_id':job_id})


def active_image_job(uid):
    # Caller holds JOBS_LOCK so discovery and job creation cannot race.
    return next(({'job_id':job_id,'stage':entry['stage']} for job_id,entry in JOBS.items()
                 if entry['user_id']==uid and entry['action']=='image' and entry['status']=='running'),None)


@app.get('/api/image-jobs/active')
@auth_required
def image_job_active():
    with JOBS_LOCK:
        return jsonify(active_image_job(session['user_id']) or {})


@app.get('/api/jobs/<job_id>')
@auth_required
def job(job_id):
    with JOBS_LOCK:
        entry=JOBS.get(job_id)
        if not entry or entry['user_id'] != session['user_id']: abort(404)
        return jsonify({k:v for k,v in entry.items() if k != 'user_id'})


if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1',port=int(os.environ.get('MEETING_PORT','8765')),debug=False,threaded=True)
else:
    init_db()
