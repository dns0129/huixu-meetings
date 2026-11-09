from __future__ import annotations
import json
from datetime import date
import os
import re
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from materials import material_dimensions


def paths(root, data, uid):
    return (root/'.pi-runtime/node_modules/.bin/pi',root/'.pi-runtime/node_modules/pi-codex-image-gen/index.ts',data/'pi-accounts'/str(uid))


def status(root,data,uid):
    pi,ext,account=paths(root,data,uid)
    try:
        creds=json.loads((account/'auth.json').read_text())
        # Credential presence is not an entitlement or a network check.
        oauth=lambda k: isinstance(creds.get(k),dict) and creds[k].get('type')=='oauth'
        chat=oauth('openai') or oauth('openai-codex')
        image=oauth('codex-images') or oauth('openai-codex')
    except (OSError,ValueError,TypeError): chat=image=False
    return {'installed':pi.exists(),'extension_installed':ext.exists(),'signed_in':chat,'chat_signed_in':chat,'image_signed_in':image}


def env_for(account):
    env=dict(os.environ)
    # Do not silently fall back to any API key or another local Pi account.
    for name in list(env):
        if name.endswith('_API_KEY') or name in ('ANTHROPIC_AUTH_TOKEN','ANTHROPIC_OAUTH_TOKEN','OPENAI_ORG_ID','OPENAI_PROJECT_ID'):
            env.pop(name,None)
    env['PI_CODING_AGENT_DIR']=str(account)
    env['PI_TELEMETRY']='0'
    return env


def launch_login(root,data,uid):
    pi,ext,account=paths(root,data,uid)
    if not pi.exists() or not ext.exists(): raise ValueError('Pi 或生图插件尚未安装')
    account.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(account,0o700)
    script=account/'连接 ChatGPT.command'
    cmd=' '.join(shlex.quote(str(x)) for x in [pi,'--no-extensions','--no-skills','--no-prompt-templates','--no-context-files','--no-mcp','--no-session','-e',ext])
    body='#!/bin/zsh\nexport PI_CODING_AGENT_DIR='+shlex.quote(str(account))+'\nexport PI_TELEMETRY=0\ncd '+shlex.quote(str(root))+'\nclear\nprintf "\\n请先输入 /login openai 完成文本 AI 登录；再输入 /login codex-images 完成生图登录。\\n登录过程中请在浏览器授权，不要把授权链接或验证码发给他人。\\n完成后回到网页点击刷新状态。\\n\\n"\nexec '+cmd+'\n'
    script.write_text(body); os.chmod(script,0o700)
    if os.uname().sysname != 'Darwin':
        return {'opened':False,'command_path':str(script)}
    subprocess.run(['open',str(script)],check=True,timeout=10,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'opened':True}


def _account_models(pi, root, account):
    """Ask OpenAI for the signed-in account's visible model catalog, without exposing tokens."""
    try:
        auth=subprocess.run([str(pi),'auth','print-bearer-token','--provider','openai'],cwd=root,env=env_for(account),capture_output=True,text=True,timeout=30)
    except (OSError,subprocess.TimeoutExpired):
        raise ValueError('无法读取 Pi 的文字授权，请检查登录状态。')
    token=auth.stdout.strip() if auth.returncode==0 else ''
    if not re.fullmatch(r'[A-Za-z0-9._~+\-/=]+',token):
        raise ValueError('Pi 的文字授权不可用，请重新完成登录。')
    config='url = "https://api.openai.com/v1/models"\nheader = "Authorization: Bearer '+token+'"\nheader = "Accept: application/json"\n'
    try:
        response=subprocess.run(['curl','--silent','--show-error','--fail-with-body','--max-time','12','--write-out','\n__HUIXU_HTTP_STATUS__:%{http_code}','--config','-'],input=config,cwd=root,env=env_for(account),capture_output=True,text=True,timeout=18)
    except (OSError,subprocess.TimeoutExpired):
        raise ValueError('无法读取账号模型目录，请检查网络和登录状态。')
    body_text, marker, http_status=response.stdout.rpartition('\n__HUIXU_HTTP_STATUS__:')
    if not marker or http_status.strip()!='200' or response.returncode not in (0,28):
        raise ValueError('无法读取账号模型目录，请检查网络和 ChatGPT 订阅权限。')
    try:
        body=json.loads(body_text)
        models=body['models']
        if not isinstance(models,list): raise ValueError()
    except (KeyError,TypeError,ValueError):
        # Some connections stall after returning a partial catalog. Accept only
        # fully decoded entries from the models array, and only if the desired
        # visible model itself is present; never infer access from fragments.
        match=re.search(r'"models"\s*:\s*\[',body_text)
        if response.returncode!=28 or not match: raise ValueError('账号模型目录返回格式无法识别，请稍后重试。')
        pos=match.end(); decoder=json.JSONDecoder(); models=[]
        while pos<len(body_text):
            while pos<len(body_text) and body_text[pos] in ' \t\r\n,': pos+=1
            try: item,pos=decoder.raw_decode(body_text,pos)
            except ValueError: break
            models.append(item)
        if not any(isinstance(item,dict) and item.get('slug')=='gpt-6.1-sol' and item.get('visibility')=='list' for item in models):
            raise ValueError('账号模型目录未完整返回，请检查网络后重试。')
    return [item['slug'] for item in models if isinstance(item,dict) and item.get('visibility')=='list' and isinstance(item.get('slug'),str) and re.fullmatch(r'[A-Za-z0-9._-]{1,120}',item['slug'])]


def _pi_models(pi, root, account, provider):
    try:
        result=subprocess.run([str(pi),'--no-extensions','--no-skills','--no-context-files','--no-mcp','--list-models',provider],cwd=root,env=env_for(account),capture_output=True,text=True,timeout=30)
    except (OSError,subprocess.TimeoutExpired):
        raise ValueError('无法读取 Pi 的模型目录，请检查 Pi 安装。')
    if result.returncode!=0: raise ValueError('无法读取 Pi 的模型目录，请检查 Pi 登录状态。')
    lines=[line.split() for line in result.stdout.splitlines()]
    return {parts[1] for parts in lines if len(parts)>=2 and parts[0]==provider}


def _select_chat_model(pi, root, account, provider):
    supported=_pi_models(pi,root,account,provider)
    if provider=='openai':
        try: available=_account_models(pi,root,account)
        except ValueError:
            # A stalled catalog must not block a specifically requested model;
            # the actual model request still enforces account entitlement.
            available=None
    else:
        # Legacy Pi OAuth has a separate provider and no documented account-specific catalog.
        available=['gpt-6.1-sol','gpt-6-sol','gpt-5.6-sol','gpt-6-astra']
    chosen='gpt-6.1-sol'
    if (available is not None and chosen not in available) or chosen not in supported:
        raise ValueError('当前账号或 Pi 暂不支持 GPT-6.1 Sol，请检查授权或更新 Pi。')
    return chosen


def _image_event_error(stream):
    """Classify image-tool events without returning prompts, tokens, or image payloads."""
    called=False
    failures=[]
    completed=False
    for line in stream.splitlines():
        try: event=json.loads(line)
        except (TypeError,ValueError): continue
        if not isinstance(event,dict): continue
        typ=event.get('type')
        if typ=='tool_execution_start' and event.get('toolName')=='codex_generate_image': called=True
        if typ=='tool_execution_end' and event.get('toolName')=='codex_generate_image':
            called=True
            if event.get('isError'):
                result=event.get('result') or {}
                blocks=result.get('content',[]) if isinstance(result,dict) else []
                failures.extend(str(b.get('text',''))[:3000] for b in blocks if isinstance(b,dict) and b.get('type')=='text')
            else: completed=True
        if typ=='message_end':
            message=event.get('message') or {}
            if isinstance(message,dict) and message.get('role')=='assistant' and message.get('stopReason') in ('error','aborted'):
                failures.append(str(message.get('errorMessage',''))[:3000])
    if completed: return None
    detail=' '.join(failures).lower()
    if 'rate limit' in detail or 'quota is unavailable' in detail or 'quota exhausted' in detail or 'usage_limit' in detail or '429' in detail: return '生图额度或请求频率受限，请稍后检查后再试。'
    if 'authentication' in detail or 'unauthorized' in detail or '401' in detail: return '图片授权无效或已过期，请重新完成 Pi 的图片登录。'
    if 'model' in detail and ('not supported' in detail or 'model_not_found' in detail or 'unsupported' in detail): return '图片服务不支持 GPT-6.1 Sol 路由，请检查账号模型权限。'
    if 'cloudflare' in detail or 'connection' in detail or 'fetch failed' in detail: return '图片服务连接失败，请检查网络后再试。'
    if '403' in detail or 'permission' in detail: return '图片服务拒绝了当前账号的请求，请检查订阅与权限。'
    if 'no image' in detail or 'did not return an image' in detail: return '图片服务未返回图片；本次请求可能已消耗额度。'
    if 'timed out' in detail or 'timeout' in detail: return '图片服务请求超时；本次请求可能已消耗额度。'
    if failures: return '图片扩展返回错误；本次请求可能已消耗额度，未自动重试。'
    if not called: return 'Pi 没有调用生图工具，请检查模型和扩展状态。'
    return '生图任务没有返回完成状态；本次请求可能已消耗额度。'


def _run(pi, ext, root, account, prompt, image=False, output_dir=None, reference_path=None):
    try:
        creds=json.loads((account/'auth.json').read_text())
        modern=isinstance(creds.get('openai'),dict) and creds['openai'].get('type')=='oauth'
    except (OSError,ValueError,TypeError): modern=False
    provider='openai' if modern else 'openai-codex'
    model=_select_chat_model(pi,root,account,provider)
    args=[str(pi),'--no-extensions','--no-skills','--no-prompt-templates','--no-context-files','--no-mcp','--no-session','--provider',provider,'--model',model,'--thinking','low','--print']
    if image:
        args+=['--mode','json','-e',str(ext),'-e',str(root/'extensions'/'image-policy.ts'),'--tools','codex_generate_image']
    else:
        args+=['--no-tools']
    env=env_for(account)
    env.pop('MEETING_KV_REFERENCE',None)
    if reference_path is not None: env['MEETING_KV_REFERENCE']=str(reference_path)
    if output_dir:
        env['PI_CODEX_IMAGE_SAVE_MODE']='custom'; env['PI_CODEX_IMAGE_SAVE_DIR']=str(output_dir)
    try:
        proc=subprocess.run(args,input=prompt,text=True,capture_output=True,cwd=root,env=env,timeout=360 if image else 180)
    except subprocess.TimeoutExpired:
        raise ValueError('Pi 请求超时。生图请求可能仍已消耗次数，请检查结果后再试。' if image else 'Pi 请求超时，请稍后重试。')
    # Never echo raw process output: it may contain private content or credentials.
    if proc.returncode != 0:
        diag=(proc.stderr+' '+proc.stdout).lower()
        if 'model_not_found' in diag or 'model is not supported' in diag:
            raise ValueError('当前账号不支持所选模型，请刷新授权并检查账号模型权限。')
        if '429' in diag or 'usage_limit' in diag or 'rate limit' in diag:
            raise ValueError('ChatGPT 当前额度或请求频率受限，请稍后再试。')
        if 'not_eligible' in diag or 'unsupported_capability' in diag or '403' in diag:
            raise ValueError('当前 ChatGPT 账号或订阅暂不支持这项请求，请检查账号权限。')
        if '401' in diag or 'unauthorized' in diag or 'no api key' in diag:
            raise ValueError('Pi 登录状态无效或已过期，请重新完成对应的 ChatGPT 登录。')
        raise ValueError('Pi 调用未成功。请检查 ChatGPT 登录、网络与订阅权限，然后重试。')
    if image:
        image_error=_image_event_error(proc.stdout)
        if image_error: raise ValueError(image_error)
    result=proc.stdout.strip()
    if not result and not image:
        raise ValueError('Pi 没有返回内容。请检查账号权限和网络。')
    return result


def _normalize_analysis(analysis):
    """Normalize fields that the meeting editor stores in a constrained format."""
    result=dict(analysis)
    original=result.get('date')
    if isinstance(original,str) and original.strip():
        match=re.search(r'(?<!\d)(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})(?:日)?',original)
        try:
            result['date']=date(*(int(part) for part in match.groups())).isoformat() if match else ''
        except ValueError:
            result['date']=''
        if not result['date']:
            questions=result.get('questions')
            result['questions']=(questions if isinstance(questions,list) else [])+['请确认会议日期，填写具体年月日。']
    guests=result.get('guests')
    if isinstance(guests,str):
        names=[]
        for line in guests.splitlines():
            name=re.split(r'[|｜]',line,maxsplit=1)[0].strip()
            if name:names.append(name)
        result['guests']='\n'.join(names)
    return result


def run(root,data,uid,meeting,action,extra,*,reference_path=None):
    pi,ext,account=paths(root,data,uid); d=meeting['data']
    if action=='image':
        st=status(root,data,uid)
        if not st['image_signed_in']: raise ValueError('请在 Pi 中执行 /login codex-images 完成生图授权。')
        folder=data/'generated'/str(uid)/uuid.uuid4().hex
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        idea=str(extra.get('prompt','')).strip()[:1500] or '现代商务会议，专业、简洁、有层次的背景纹理与构图'
        kind=extra.get('kind') or 'poster'; width,height=material_dimensions(d,kind)
        task=(f'使用随工具请求提供的参考 KV，将构图调整为宽高比 {width:g}:{height:g}。'
              '沿用原图风格、主色和核心视觉；通过重新布局或延展边缘填满画面，不拉伸主体。尽量保留原有元素，不添加新文字、二维码或 Logo。'
              if reference_path else
              f'会议主题：{meeting["title"]}。画面宽高比：{width:g}:{height:g}，构图尽量贴合该比例。视觉要求：{idea}。'
              '背景铺满画面，重要内容远离画面边缘，留出宽阔清晰的文字区域。不要绘制文字、数字、二维码或 Logo。')
        prompt=('请立即调用 codex_generate_image 工具生成一张背景图，只调用一次。工具参数 model 使用 gpt-6.1-sol、transport 使用 responses、save 使用 custom、outputFormat 使用 png。'
                '请以环境变量指定的目录保存，不要输出 base64。'+task)
        failure=None
        try:
            if reference_path:
                with tempfile.TemporaryDirectory(prefix='huixu-kv-') as temp:
                    ref=Path(temp)/'reference.png'
                    try:
                        with Image.open(reference_path) as source:
                            image=ImageOps.exif_transpose(source).convert('RGBA')
                            image.thumbnail((1600,1600),Image.Resampling.LANCZOS)
                            image.save(ref,format='PNG')
                    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):
                        raise ValueError('无法读取参考 KV，请重新上传。') from None
                    _run(pi,ext,root,account,prompt,image=True,output_dir=folder,reference_path=ref)
            else: _run(pi,ext,root,account,prompt,image=True,output_dir=folder)
        except ValueError as exc: failure=exc
        imgs=sorted((p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg','.webp')),key=lambda p:p.stat().st_mtime,reverse=True)
        if not imgs and failure: raise failure
        if not imgs: raise ValueError('Pi 没有返回可用图片。请求可能已消耗生图次数，不会自动重试。')
        return {'path':str(imgs[0])}
    payload={'会议名称':meeting['title'],'会议资料':d}
    if action=='analyze':
        prompt=('你是会议资料整理助手。只使用用户提供的底稿，绝不编造。把明确存在的信息提取为 JSON，'
          '字段为 date（YYYY-MM-DD）、time、location、organizer、host、subtitle、guests（仅嘉宾姓名，每行一人，不含职务）、agenda（对象数组，字段 time、item、speaker、note）、questions（缺失信息问题字符串数组）。'
          '未知内容留空。结合底稿要求制作的物料和会议环节，检查是否缺少影响制作或现场执行的信息，在 questions 中提出简洁具体的问题；不要重复追问底稿已有的内容。'
          '例如，安排了合影但未说明地点或参与人员时，应询问合影地点和参与范围；需要宣传物料但未说明 Logo 时，可询问是否需要使用 Logo，允许回答不需要。'
          '只问确有必要确认的内容，不能假设缺失信息，不需要确认时返回空数组。不要把现有资料冲掉，不要解释，必须只输出有效 JSON。会议资料如下：\n'+json.dumps(payload,ensure_ascii=False))
        output=_run(pi,ext,root,account,prompt)
        output=re.sub(r'^```(?:json)?\s*|\s*```$','',output.strip())
        try:
            obj=json.loads(output)
            if not isinstance(obj,dict): raise ValueError()
        except ValueError: raise ValueError('AI 返回格式不符合要求，请重新尝试。')
        return {'analysis':_normalize_analysis(obj)}
    if action=='script':
        prompt=('根据以下会议资料撰写中文主持串词，适合正式会议，按现有议程逐环节衔接。'
                '不得编造姓名、职务、时间或活动内容；缺失项用【待确认】标注。只输出串词正文。\n'+json.dumps(payload,ensure_ascii=False))
        return {'script':_run(pi,ext,root,account,prompt)}
    raise ValueError('不支持的 AI 操作')
