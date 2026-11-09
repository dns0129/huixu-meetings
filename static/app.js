const $ = s => document.querySelector(s);
const app = $('#app'), modalRoot = $('#modal-root');
const state = {user:null,series:[],meetings:[],view:'home',seriesId:null,meeting:null,tab:'source',materialTab:'preview',kind:'poster',dirty:false,aiQuestions:[],busy:false,pi:null,imageProviders:null,imageTier:'chatgpt',questionsCollapsed:false,layerIndex:0,library:{projects:[],kvs:[]}};
const icons = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const delay = ms => new Promise(r=>setTimeout(r,ms));
async function api(path, options={}){
  const init={method:options.method||'GET',headers:{},credentials:'same-origin',signal:options.signal};
  if(options.body instanceof FormData) init.body=options.body;
  else if(options.body!==undefined){init.headers['Content-Type']='application/json';init.body=JSON.stringify(options.body)}
  const res=await fetch(path,init); let value; try{value=await res.json()}catch{value={error:'服务器返回了无法识别的内容'}}
  if(!res.ok){const err=Error(value.error||`请求失败（${res.status}）`);err.status=res.status;throw err} return value;
}
function toast(s){const el=$('#toast');el.textContent=s;el.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.remove('show'),3500)}
function modal(content,wide=false){modalRoot.innerHTML=`<div class="modal-backdrop"><div class="modal ${wide?'wide':''}" role="dialog" aria-modal="true">${content}</div></div>`;setTimeout(()=>modalRoot.querySelector('input,textarea,button')?.focus(),30)}
function closeModal(){modalRoot.innerHTML=''}
function modalHead(title,desc=''){return `<div class="modal-head"><div><h2>${esc(title)}</h2><p>${esc(desc)}</p></div><button class="icon-btn" data-action="close-modal" aria-label="关闭">${icons('close')}</button></div>`}
function authView(mode='login',message=''){
  const register=mode==='register'; state.view='auth';
  app.innerHTML=`<div class="auth-screen"><section class="auth-art"><div class="brand"><div class="logo-mark">序</div><div><strong>会序</strong><small>MEETING STUDIO</small></div></div><div class="auth-copy"><span class="eyebrow">为每一次相聚，做好准备</span><h1>一份底稿，<br>一整套会议素材。</h1><p>从会议日程到现场物料，把零散的信息整理成有序、统一的表达。</p><div class="paper-stack"><div class="paper one"></div><div class="paper two"></div><div class="paper three"></div></div></div><div class="auth-art-footer">会序 · 让会议准备更从容</div></section><section class="auth-form-side"><div class="auth-box"><h2>${register?'创建你的工作空间':'欢迎回来'}</h2><p>${register?'创建本机账号，开始整理你的会议资料。':'登录你的账号，继续准备下一场会议。'}</p><form id="auth-form"><div class="field"><label for="username">账号名称</label><input id="username" name="username" autocomplete="username" placeholder="请输入账号名称" required maxlength="40"></div><div class="field"><label for="password">密码</label><input id="password" name="password" type="password" autocomplete="${register?'new-password':'current-password'}" placeholder="${register?'至少 8 位':'请输入密码'}" required minlength="8" maxlength="128"></div><p class="auth-message">${esc(message)}</p><button class="btn block" type="submit">${register?'创建账号':'登录工作台'} ${icons('arrow')}</button></form><div class="auth-switch">${register?'已有账号？':'还没有账号？'} <button class="text-button" data-action="auth-switch" data-mode="${register?'login':'register'}">${register?'直接登录':'创建账号'}</button></div></div></section></div>`;
  $('#auth-form').addEventListener('submit',async e=>{e.preventDefault();const btn=e.target.querySelector('button');btn.disabled=true;try{const body=Object.fromEntries(new FormData(e.target));const r=await api(register?'/api/register':'/api/login',{method:'POST',body});state.user=r.user;await refreshList();state.view='home';await resumeImageTask();render()}catch(err){$('.auth-message').textContent=err.message}finally{btn.disabled=false}});
}
async function refreshList(){const [result,library]=await Promise.all([api('/api/series'),api('/api/library')]);state.series=result.series;state.meetings=result.meetings;state.library=library}
function shell(content,crumb='工作台'){
  const series=state.series.map(s=>`<button class="side-link ${state.view==='series'&&state.seriesId===s.id?'active':''}" data-action="open-series" data-id="${s.id}"><span class="series-dot"></span><span class="side-series-name">${esc(s.name)}</span></button>`).join('');
  return `<div class="shell"><aside class="sidebar"><div class="brand"><div class="logo-mark">序</div><div><strong>会序</strong><small>MEETING STUDIO</small></div></div><div class="side-nav"><button class="side-link ${state.view==='home'?'active':''}" data-action="home">${icons('grid')} 工作台</button><button class="side-link ${state.view==='library'?'active':''}" data-action="library">${icons('folder')} 项目与 KV</button><button class="side-link ${state.view==='settings'?'active':''}" data-action="settings">${icons('settings')} AI 连接设置</button><div class="side-label"><span>我的会议系列</span><button class="icon-btn" data-action="new-series" aria-label="新建系列">${icons('plus')}</button></div>${series||'<div class="side-label">还没有系列</div>'}</div><div class="sidebar-spacer"></div><div class="sidebar-bottom"><div class="avatar">${esc(state.user.username.slice(0,1).toUpperCase())}</div><div><div class="account-name">${esc(state.user.username)}</div><div class="account-caption">本地工作空间</div></div><button class="icon-btn" data-action="logout" title="退出登录" aria-label="退出登录">${icons('arrow')}</button></div></aside><main class="app-main"><header class="topbar"><div class="topbar-title"><span>会序</span><span>/</span><strong>${esc(crumb)}</strong></div><div class="topbar-actions"><button class="btn ghost sm mobile-menu" data-action="home">工作台</button><button class="btn ghost sm mobile-menu" data-action="settings">AI 设置</button><span class="status-text small muted"><span class="online-dot"></span>本地工作空间</span></div></header><div class="main-content">${content}</div></main></div>`;
}
function meetingRow(m){return `<button class="meeting-row" data-action="open-meeting" data-id="${m.id}"><div><strong>${esc(m.title)}</strong><small>${esc(m.series_name)}</small></div><span>${esc(m.date||'日期待补充')}</span><span>${esc(m.location||'地点待补充')}</span>${icons('arrow')}</button>`}
function dashboard(){
  const selected=state.series.find(s=>s.id===state.seriesId), seriesList=state.view==='series'&&selected?[selected]:state.series;
  const meetings=state.view==='series'&&selected?state.meetings.filter(m=>m.series_id===selected.id):state.meetings.slice(0,8);
  const cards=seriesList.map(s=>`<button class="series-card" data-action="open-series" data-id="${s.id}"><div class="card-top"><div class="folder-icon">${icons('folder')}</div><span class="card-count">${s.meeting_count} 场会议</span></div><h3>${esc(s.name)}</h3><p>${esc(s.description||'把同一系列的会议集中管理')}</p></button>`).join('');
  return shell(`<div class="page-head"><div><h1>${selected&&state.view==='series'?esc(selected.name):'你好，'+esc(state.user.username)}</h1><p>${selected&&state.view==='series'?esc(selected.description||'管理这个系列下的会议及素材。'):'准备好开始下一场会议了吗？'}</p></div><button class="btn" data-action="new-meeting">${icons('plus')} 新建会议</button></div>${state.view==='home'?`<section class="hero"><div class="hero-copy"><div class="hero-label">从一份底稿开始</div><h2>让会议准备，更有条理。</h2><p>整理会议资料，一次生成日程、海报、串词与现场物料。</p><button class="btn" data-action="new-meeting">创建第一场会议 ${icons('arrow')}</button></div><div class="hero-art" aria-hidden="true"><div class="sheet a"></div><div class="sheet b"></div><div class="sheet c"></div></div></section>`:''}<div class="section-head"><div><h2>会议系列</h2><p>将同类型会议放在一起，方便管理</p></div>${state.view==='series'?'<button class="text-button" data-action="home">查看全部</button>':''}</div><div class="cards">${cards}<button class="new-card" data-action="new-series">${icons('plus')} 新建会议系列</button></div><div class="section-head"><div><h2>${state.view==='series'?'系列会议':'最近的会议'}</h2><p>从这里继续编辑会议内容</p></div>${!state.meetings.length?'<button class="text-button" data-action="demo">载入示例会议</button>':''}</div><div class="meeting-list">${meetings.length?meetings.map(meetingRow).join(''):'<div class="empty">还没有会议。新建会议，或载入一份示例了解工作流程。</div>'}</div>`,selected&&state.view==='series'?selected.name:'工作台');
}
function rowField(label,key,placeholder='',type='text'){let v=state.meeting.data[key]||'';return `<div class="field"><label for="field-${key}">${label}</label><input id="field-${key}" data-field="${key}" type="${type}" value="${esc(v)}" placeholder="${esc(placeholder)}"></div>`}
function localQuestions(){const d=state.meeting.data;const checks=[['date','会议在哪一天举行？','所有物料'],['time','会议从几点开始？','日程、海报、易拉宝'],['location','会议地点和具体地址是什么？','海报、易拉宝、日程'],['organizer','主办方名称是什么？','海报、易拉宝'],['host','主持人是谁？','主持串词'],['guests','需要制作桌卡的嘉宾有哪些？','桌卡']];const q=checks.filter(x=>!String(d[x[0]]||'').trim()).map(([field,question,applies_to])=>({field,question,applies_to}));const rows=(d.agenda||[]).filter(x=>String(x.item||'').trim());if(!rows.length)q.push({field:'agenda',question:'会议有哪些环节？请补充时间、内容和发言人。',applies_to:'日程、主持串词'});else rows.forEach((r,i)=>{if(!String(r.time||'').trim())q.push({field:'agenda',question:`第 ${i+1} 个议程环节的时间是什么？`,applies_to:'日程、主持串词'})});return q}
function questionsPanel(){if(state.questionsCollapsed)return `<button class="btn secondary sm" data-action="toggle-questions">展开资料完整度</button>`;const q=localQuestions();const done=Math.max(0,7-q.length);let ai=state.aiQuestions.length?`<div class="question-heading">AI 还想确认</div>${state.aiQuestions.slice(0,8).map(x=>`<div class="question"><div class="question-mark">?</div><div><p>${esc(x)}</p><span>底稿识别建议，请核对</span></div></div>`).join('')}`:'';return `<div class="panel side-panel"><div class="readiness-top"><button class="text-button collapse-questions" data-action="toggle-questions">收起</button><div class="readiness-icon">${icons('check')}</div><div class="readiness-title"><strong>资料完整度</strong><span>${q.length?'还有 '+q.length+' 项建议确认':'基础资料已填写'}</span></div></div><div class="progress-track"><div class="progress-fill" style="width:${Math.max(4,Math.min(100,done/7*100))}%"></div></div><div class="question-heading">${q.length?'待补充信息':'准备就绪'}</div>${q.length?q.slice(0,10).map(x=>`<div class="question"><div class="question-mark">?</div><div><p>${esc(x.question)}</p><span>${esc(x.applies_to)}</span></div></div>`).join(''):'<div class="question"><p class="small muted">可以继续制作会议素材了。</p></div>'}${ai}<div class="helper-note">这是本地基础检查。连接 AI 后，可根据底稿进一步识别内容并提出问题。</div></div>`}
function sourcePanel(){const m=state.meeting;return `<div><section class="panel"><div class="panel-heading"><div><h2>会议底稿</h2><p>上传会议底稿，系统会读取文件用于整理会议资料。</p></div><button class="btn subtle sm" data-action="ai-analyze">${icons('spark')} AI 整理底稿</button></div><div class="source-upload"><label class="btn" for="source-file">${icons('upload')} 上传会议底稿</label><input id="source-file" type="file" accept=".txt,.md,.csv,.docx,.xlsx,.pdf" data-upload="source" hidden><p class="field-hint">支持 Word、Excel、PDF、TXT、CSV。</p></div>${m.files?.filter(x=>x.kind==='source').length?`<p class="field-hint">已上传：${m.files.filter(x=>x.kind==='source').map(x=>esc(x.original_name)).join('、')}</p>`:''}</section></div>`}
function agendaPanel(){const rows=state.meeting.data.agenda||[];return `<div>${meetingInfoPanel()}<section class="panel"><div class="panel-heading"><div><h2>会议日程</h2><p>按顺序填写各个环节，将用于日程表和主持串词。</p></div></div><div class="table-scroll"><table class="agenda-table"><thead><tr><th style="width:21%">时间</th><th style="width:32%">环节内容</th><th style="width:20%">发言人</th><th>备注</th><th></th></tr></thead><tbody>${rows.map((r,i)=>`<tr>${['time','item','speaker','note'].map((k,j)=>`<td><input data-agenda="${i}" data-key="${k}" value="${esc(r[k]||'')}" placeholder="${['09:00–09:30','例如 开幕致辞','姓名','选填'][j]}"></td>`).join('')}<td><button class="icon-btn" data-action="remove-row" data-index="${i}" aria-label="删除此环节">${icons('close')}</button></td></tr>`).join('')}</tbody></table></div>${rows.length?'':'<div class="empty">还没有日程环节，点击下方按钮添加。</div>'}<div class="agenda-actions"><button class="btn secondary sm" data-action="add-row">${icons('plus')} 添加环节</button><div><button class="btn secondary sm" data-action="export" data-file="agenda.xlsx">${icons('download')} Excel</button> <button class="btn secondary sm" data-action="export" data-file="agenda.docx">${icons('download')} Word</button></div></div></section><section class="panel"><div class="panel-heading"><div><h2>嘉宾与桌卡名单</h2><p>每行填写一位嘉宾姓名，用于批量制作桌卡。</p></div></div><div class="field"><label for="field-guests">嘉宾姓名</label><textarea id="field-guests" data-field="guests" rows="6" placeholder="例如：&#10;张明&#10;李华">${esc(state.meeting.data.guests||'')}</textarea></div></section>${agendaWorkflow()}</div>`}
const kinds={poster:{label:'海报',desc:'会议宣传海报'},banner:{label:'易拉宝 / 展架',desc:'现场迎宾与导视'},card:{label:'桌卡',desc:'嘉宾席位标识'}};
function materialPanel(){return materialEditorPanel()}
function scriptPanel(){const d=state.meeting.data;return `<div><section class="panel"><div class="panel-heading"><div><h2>主持串词</h2><p>基于会议资料和日程生成草稿，也可以直接编辑。</p></div><div><button class="btn secondary sm" data-action="draft-script">生成模板串词</button> <button class="btn subtle sm" data-action="ai-script">${icons('spark')} AI 撰写</button></div></div><div class="field"><label for="field-script">串词内容</label><textarea id="field-script" data-field="script" rows="20" placeholder="点击“生成模板串词”或“AI 撰写”，然后在这里修改。">${esc(d.script||'')}</textarea><span class="field-hint">请核对姓名、职务与现场流程，尤其是标记为待确认的内容。</span></div><button class="btn secondary sm" data-action="export" data-file="script.docx">${icons('download')} 导出 Word</button></section></div>`}
function workspace(){const m=state.meeting,tabs=[['source','会议底稿'],['agenda','会议日程'],['transition','现场串场'],['materials','物料工坊'],['script','主持串词']];const panel={source:sourcePanel,agenda:agendaPanel,materials:materialPanel,script:scriptPanel,transition:transitionPanel}[state.tab]();return shell(`<div class="workspace"><div class="work-header"><div class="work-title"><button class="back-button" data-action="back" aria-label="返回">${icons('back')}</button><div><h1>${esc(m.title)}</h1><p>${esc(m.series_name)} <span class="muted"> / </span> 会议工作区</p></div></div><div class="topbar-actions"><span class="small muted save-state">${state.dirty?'有未保存的修改':'所有修改已保存'}</span><button class="btn sm" data-action="save">保存资料</button></div></div><nav class="tabs" aria-label="会议工作区">${tabs.map(([key,label])=>`<button class="tab ${state.tab===key?'active':''}" data-action="tab" data-tab="${key}">${label}</button>`).join('')}</nav><div class="workspace-grid ${state.questionsCollapsed?'questions-collapsed':''}">${panel}<div id="questions">${questionsPanel()}</div></div></div>`,m.series_name+' / '+m.title)}
function imageSettings(){
  const p=state.imageProviders||{}, fast=p.fast||{}, advanced=p.advanced||{};
  const badge=ok=>ok?'<span class="status-pill good">已保存配置</span>':'<span class="status-pill">未配置</span>';
  return `<section class="panel" style="max-width:780px"><div class="panel-heading"><div><h2>国产生图服务</h2><p>密钥只保存在当前本机账号中，不会再次显示。生成请求按服务商标准计费。</p></div><span class="tag">API 连接</span></div>
  <form class="provider-form" data-provider-form="fast"><div class="provider-heading"><div><h3>快速档 · Seedream 5.0 Flash</h3><p>火山引擎 · 适合快速生成会议背景</p></div>${badge(fast.configured)}</div><div class="field"><label for="fast-api-key">火山方舟 API Key</label><input id="fast-api-key" name="api_key" type="password" autocomplete="off" spellcheck="false" placeholder="${fast.configured?'已保存，留空表示保持不变':'请输入火山方舟 API Key'}"></div><div class="provider-actions"><button class="btn secondary sm" type="submit">保存快速档</button>${fast.configured?'<button class="text-button" type="button" data-action="remove-image-provider" data-tier="fast">移除配置</button>':''}<a class="text-button" href="https://ark.volcengine.com/region:cn-beijing/apikey" target="_blank" rel="noopener noreferrer">获取 API Key ↗</a></div><p class="provider-error" role="alert"></p></form>
  <form class="provider-form" data-provider-form="advanced"><div class="provider-heading"><div><h3>进阶档 · Qwen-Image 3.0 Pro</h3><p>阿里云百炼 · 适合精细背景与复杂画面</p></div>${badge(advanced.configured)}</div><div class="field"><label for="advanced-api-key">百炼 API Key（北京地域）</label><input id="advanced-api-key" name="api_key" type="password" autocomplete="off" spellcheck="false" placeholder="${advanced.configured?'已保存，留空表示保持不变':'请输入百炼 API Key'}"></div><div class="field"><label for="advanced-workspace">百炼业务空间 ID（北京地域）</label><input id="advanced-workspace" name="workspace_id" value="${esc(advanced.workspace_id||'')}" autocomplete="off" spellcheck="false" placeholder="例如 llm-xxxxxxxx" required><span class="field-hint">在百炼控制台的业务空间详情中查看，填写 ID，不要填写完整网址。</span></div><div class="provider-actions"><button class="btn secondary sm" type="submit">保存进阶档</button>${advanced.configured?'<button class="text-button" type="button" data-action="remove-image-provider" data-tier="advanced">移除配置</button>':''}<a class="text-button" href="https://help.aliyun.com/zh/model-studio/beijing-access-information" target="_blank" rel="noopener noreferrer">查看获取方式 ↗</a></div><p class="provider-error" role="alert"></p></form>
  <div class="helper-note">“已保存配置”仅表示密钥已保存，实际可用性取决于对应账号的模型权限、余额和网络。生图时会把会议名称与画面要求发送给所选服务商。</div></section>`
}
async function refreshConnections(){const [pi,providers]=await Promise.all([api('/api/pi/status'),api('/api/image-providers')]);state.pi=pi;state.imageProviders=providers}
function settings(){const p=state.pi||{};const status=(yes)=>yes?'<span class="status-pill good">已发现授权</span>':'<span class="status-pill">未连接</span>';return shell(`<div class="page-head"><div><h1>AI 连接设置</h1><p>分别配置文字 AI 和图片生成服务。</p></div><button class="btn secondary sm" data-action="refresh-pi">刷新状态</button></div><section class="panel" style="max-width:780px"><div class="panel-heading"><div><h2>Pi Agent · ChatGPT</h2><p>授权信息保存在当前本机账号的独立目录中，不会显示在网页上。</p></div><span class="tag">本机连接</span></div><div class="status-row"><div class="folder-icon">${icons('spark')}</div><div><strong>Pi Agent 与生图扩展</strong><span>项目内安装，无需更改全局环境</span></div><span class="status-pill ${p.installed&&p.extension_installed?'good':''}">${p.installed&&p.extension_installed?'已安装':'未安装'}</span></div><div class="status-row"><div class="folder-icon">${icons('spark')}</div><div><strong>GPT-6.1 Sol</strong><span>文字处理与图片请求路由；图片模型由服务方决定</span></div><span class="status-pill good">已指定</span></div><div class="status-row"><div class="folder-icon">${icons('file')}</div><div><strong>文字 AI 授权</strong><span>用于识别底稿和生成主持串词</span></div>${status(p.chat_signed_in)}</div><div class="status-row"><div class="folder-icon">${icons('image')}</div><div><strong>图片生成授权</strong><span>用于制作会议背景图</span></div>${status(p.image_signed_in)}</div><div class="helper-note">显示“已发现授权”只代表本机存在登录信息；具体模型和生图权限以实际请求结果为准。</div><div style="margin-top:24px"><h3 style="font-size:14px">如何连接</h3><div class="step"><b>1</b><div>点击下方按钮打开终端，进入 Pi。</div></div><div class="step"><b>2</b><div>在终端输入 <code>/login openai</code>，按提示在浏览器登录并同意使用 ChatGPT 订阅。</div></div><div class="step"><b>3</b><div>再输入 <code>/login codex-images</code> 完成单独的图片授权，然后回到这里刷新状态。</div></div><div class="step"><b>4</b><div>授权完成后，在会议底稿或物料工坊中使用相应 AI 按钮。</div></div><button class="btn" data-action="launch-pi">${icons('spark')} 打开 Pi 登录</button> <button class="btn ghost" data-action="refresh-pi">我已完成，刷新状态</button><p class="export-note">请在浏览器及 Pi 终端中完成登录，不要将授权链接、验证码或凭据粘贴到聊天中。订阅额度和账户可用性由服务方决定。</p></div></section>${imageSettings()}`,'AI 连接设置')}
function render(){if(!state.user)return authView();app.innerHTML=state.view==='library'?libraryPage():state.view==='settings'?settings():state.view==='meeting'?workspace():dashboard();if(state.view==='meeting'&&state.tab==='materials'&&state.materialTab==='generate')void refreshKVFit()}
function markDirty(){state.dirty=true;const s=$('.save-state');if(s)s.textContent='有未保存的修改';if($('#questions'))$('#questions').innerHTML=questionsPanel()}
async function saveCurrent(silent=false){if(!state.meeting)return;const m=state.meeting;if(!m.title.trim())throw Error('请填写会议名称');await api(`/api/meetings/${m.id}`,{method:'PUT',body:{title:m.title,data:m.data}});state.dirty=false;const s=$('.save-state');if(s)s.textContent='所有修改已保存';if(!silent)toast('会议资料已保存')}
async function downloadExport(file){
  await saveCurrent(true);toast('正在准备导出文件…');
  const response=await fetch(`/api/meetings/${state.meeting.id}/export/${encodeURIComponent(file)}`,{credentials:'same-origin'});
  if(!response.ok){let result={};try{result=await response.json()}catch{}throw Error(result.error||`导出失败（${response.status}）`)}
  const disposition=response.headers.get('Content-Disposition')||'';
  const encoded=disposition.match(/filename\*=UTF-8''([^;]+)/i),plain=disposition.match(/filename="?([^";]+)"?/i);
  let name=state.meeting.title+'-'+file;
  if(encoded){try{name=decodeURIComponent(encoded[1])}catch{}}
  else if(plain)name=plain[1];
  const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');
  link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  toast('文件已生成');
}
async function openMeeting(id){if(state.dirty)await saveCurrent(true);state.meeting=await api(`/api/meetings/${id}`);state.aiQuestions=[];state.tab='source';state.kind='poster';state.dirty=false;state.view='meeting';render()}
async function leaveMeeting(){if(state.dirty)await saveCurrent(true);state.meeting=null;await refreshList()}
function newSeriesModal(){modal(`${modalHead('新建会议系列','把同一主题或客户的会议放在一个系列中。')}<form id="series-form"><div class="field"><label for="series-name">系列名称</label><input id="series-name" name="name" required maxlength="100" placeholder="例如：小微企业交流会"></div><div class="field"><label for="series-desc">系列说明（选填）</label><input id="series-desc" name="description" maxlength="500" placeholder="简单描述这个系列"></div><div class="modal-error"></div><div class="modal-actions"><button class="btn ghost" type="button" data-action="close-modal">取消</button><button class="btn" type="submit">创建系列</button></div></form>`);$('#series-form').onsubmit=async e=>{e.preventDefault();try{const r=await api('/api/series',{method:'POST',body:Object.fromEntries(new FormData(e.target))});await refreshList();closeModal();state.seriesId=r.id;state.view='series';render();toast('会议系列已创建')}catch(err){$('.modal-error').textContent=err.message}}}
function newMeetingModal(){if(!state.series.length){toast('请先创建一个会议系列');newSeriesModal();return}modal(`${modalHead('新建会议','每场会议拥有独立的底稿、日程和素材。')}<form id="meeting-form"><div class="field"><label for="meeting-series">所属系列</label><select id="meeting-series" name="series_id">${state.series.map(s=>`<option value="${s.id}" ${state.seriesId===s.id?'selected':''}>${esc(s.name)}</option>`).join('')}</select></div><div class="field"><label for="new-meeting-title">会议名称</label><input id="new-meeting-title" name="title" required maxlength="150" placeholder="例如：2027 春季企业交流会"></div><div class="modal-error"></div><div class="modal-actions"><button class="btn ghost" type="button" data-action="close-modal">取消</button><button class="btn" type="submit">创建并开始</button></div></form>`);$('#meeting-form').onsubmit=async e=>{e.preventDefault();try{const r=await api('/api/meetings',{method:'POST',body:Object.fromEntries(new FormData(e.target))});closeModal();await refreshList();await openMeeting(r.id);toast('会议已创建')}catch(err){$('.modal-error').textContent=err.message}}}
async function createDemo(){const s=await api('/api/series',{method:'POST',body:{name:'示例｜小微企业交流',description:'这是一份演示数据，可新建自己的系列。'}});const m=await api('/api/meetings',{method:'POST',body:{series_id:s.id,title:'小微企业成长交流会（示例）'}});const data={date:'2027-03-18',time:'09:00',location:'上海 · 城市会客厅',organizer:'示例主办单位',host:'王老师',subtitle:'连接 · 分享 · 共成长',baseline:'这是一份示例底稿：小微企业成长交流会，旨在交流经营经验。以上信息均为演示，请以真实底稿替换。',guests:'张明\n李华\n陈晓',agenda:[{time:'09:00–09:15',item:'签到入场',speaker:'',note:''},{time:'09:15–09:30',item:'开场致辞',speaker:'张明',note:''},{time:'09:30–10:15',item:'企业经验分享',speaker:'李华',note:''},{time:'10:15–10:45',item:'交流讨论',speaker:'',note:''}],design:{poster:{width:210,height:297,font:'hei',palette:'blue'},banner:{width:800,height:2000,font:'hei',palette:'blue'},card:{width:210,height:100,font:'hei',palette:'blue'}}};await api(`/api/meetings/${m.id}`,{method:'PUT',body:{title:'小微企业成长交流会（示例）',data}});await refreshList();await openMeeting(m.id);toast('已创建示例会议')}
async function uploadFile(el){const file=el.files[0];if(!file)return;const kind=el.dataset.upload,form=new FormData();form.append('file',file);form.append('kind',kind==='material-kv'?'background':kind);toast('正在读取文件…');const r=await api(`/api/meetings/${state.meeting.id}/upload`,{method:'POST',body:form});if(kind==='source'){state.meeting.data.baseline=(state.meeting.data.baseline?state.meeting.data.baseline+'\n\n':'')+`【${r.name}】\n${r.text}`;state.meeting.files.unshift({id:r.id,kind:'source',original_name:r.name})}else {state.meeting.data[kind==='material-kv'?state.kind+'_kv_file_id':kind==='logo'?'logo_file_id':kind==='font'?'font_file_id':'background_file_id']=r.id;if(kind==='font')state.meeting.data.design[state.kind].font='custom'}markDirty();await saveCurrent(true);render();toast(kind==='source'?'底稿已读取并保存':'图片已上传并保存')}
async function aiJob(action,extra={}){await saveCurrent(true);const {job_id}=await api(`/api/meetings/${state.meeting.id}/ai/${action}`,{method:'POST',body:extra});for(let i=0;i<280;i++){await delay(2500);const r=await api(`/api/jobs/${job_id}`);if(r.status==='done')return r.result;if(r.status==='error')throw Error(r.message)}throw Error('等待超时，请稍后检查结果。')}
const imageDialog=$('#image-task-dialog');
const imagePhases={preparing:[0,'正在准备生成请求…'],generating:[1,'AI 正在生成图片，可能需要几分钟…'],saving:[2,'正在按物料尺寸裁切并保存…'],done:[3,'KV 已保存。']};
imageDialog.addEventListener('cancel',e=>e.preventDefault());
function imageProgress(phase,reconnecting=false){
  const [step,label]=imagePhases[phase]||imagePhases.generating;
  const status=$('#image-task-status'),message=reconnecting?'连接暂时中断，正在确认任务状态…':label;
  if(status.textContent!==message)status.textContent=message;
  const bar=imageDialog.querySelector('[role="progressbar"]');
  bar.setAttribute('aria-valuenow',step);bar.setAttribute('aria-valuetext',message);
  bar.querySelectorAll('span').forEach((segment,i)=>{segment.classList.toggle('complete',i<step);segment.classList.toggle('current',i===step)});
}
async function pollImageTask(path,phase){
  for(;;){
    try{return await api(path,{signal:AbortSignal.timeout(10000)})}
    catch(err){if([401,403,404].includes(err.status))throw err;imageProgress(phase,true);await delay(1500)}
  }
}
function reportAIError(err){
  toast(err.message);
  if(/登录|授权|API Key|业务空间/.test(err.message)){
    modal(`${modalHead('需要连接 AI',err.message)}<div class="helper-note">请前往 AI 连接设置，配置所选服务的账号。</div><div class="modal-actions"><button class="btn secondary" data-action="close-modal">稍后再说</button><button class="btn" data-action="settings-from-modal">前往连接</button></div>`)
  }
}
async function handleImage(extra,active=null){
  if(state.busy)return;
  const meetingId=state.meeting?.id;
  let phase=active?.stage||'preparing',notice='',failure;
  state.busy=true;closeModal();$('#image-task-title').textContent=extra?.adapt?'正在适配 KV 尺寸':'正在生成 KV';imageProgress(phase);
  document.documentElement.classList.add('image-task-locked');app.inert=true;modalRoot.inert=true;imageDialog.showModal();
  try{
    if(!active){
      await saveCurrent(true);
      try{active=await api(`/api/meetings/${meetingId}/ai/image`,{method:'POST',body:extra})}
      catch(err){
        if(err.status)throw err;
        active=await pollImageTask('/api/image-jobs/active',phase);
        if(!active.job_id)throw err;
      }
    }
    phase=active.stage||'generating';imageProgress(phase);
    for(;;){
      const job=await pollImageTask(`/api/jobs/${active.job_id}`,phase);
      if(job.status==='error')throw Error(job.message||'KV 生成失败，请重试。');
      if(job.status==='done'){
        const result=job.result;
        if(result.applied!==false&&state.meeting?.id===job.meeting_id){state.meeting.data[result.kind?result.kind+'_kv_file_id':'background_file_id']=result.file_id}
        notice=result.applied===false?'物料设置已变更，生成结果未覆盖当前 KV':'AI KV 已生成并应用';
        imageProgress('done');await delay(250);break;
      }
      phase=job.stage||phase;imageProgress(phase);await delay(1200);
    }
  }catch(err){failure=err}
  finally{
    state.busy=false;imageDialog.close();app.inert=false;modalRoot.inert=false;document.documentElement.classList.remove('image-task-locked');render();
    app.querySelector('[data-action="ai-image"]')?.focus({preventScroll:true});
  }
  if(failure)reportAIError(failure);else toast(notice);
}
async function resumeImageTask(){
  const active=await api('/api/image-jobs/active',{signal:AbortSignal.timeout(5000)}).catch(()=>null);
  if(active?.job_id)void handleImage(null,active);
}
async function handleAI(action,extra={}){
  if(action==='image')return handleImage(extra);
  if(state.busy)return;
  const meetingId=state.meeting.id;
  state.busy=true;
  toast('AI 正在处理，请稍候…');
  try{
    const result=await aiJob(action,extra);
    if(state.meeting?.id!==meetingId){toast('任务已完成，请回到原会议查看结果');return}
    const d=state.meeting.data;
    if(action==='analyze'){
      const a=result.analysis||{};let count=0;
      for(const k of ['date','time','location','organizer','host','subtitle','guests'])if(!String(d[k]||'').trim()&&typeof a[k]==='string'&&a[k].trim()){d[k]=a[k];count++}
      if(!(d.agenda||[]).some(x=>String(x.item||'').trim())&&Array.isArray(a.agenda)){d.agenda=a.agenda.filter(x=>x&&typeof x==='object').map(x=>Object.fromEntries(['time','item','speaker','note'].map(k=>[k,String(x[k]||'')])));if(d.agenda.length)count++}
      state.aiQuestions=Array.isArray(a.questions)?a.questions.filter(x=>typeof x==='string'):[];markDirty();await saveCurrent(true);render();toast(`AI 已填入 ${count} 项资料，请核对`)
    }else if(action==='script'){d.script=result.script||'';markDirty();await saveCurrent(true);render();toast('AI 串词已生成，请核对')}
  }catch(err){reportAIError(err)}finally{state.busy=false}
}
async function imagePromptModal(){
  state.imageProviders=await api('/api/image-providers');
  const p=state.imageProviders, chosen=state.imageTier;
  const option=(value,label,configured)=>`<option value="${value}" ${chosen===value?'selected':''}>${label}${configured?'':'（未配置）'}</option>`;
  modal(`${modalHead('AI 生成 KV','生成无 Logo 的底图，并应用到当前物料。')}<form id="image-form"><div class="field"><label for="image-tier">生图档位</label><select id="image-tier" name="tier">${option('chatgpt','ChatGPT · 原有订阅',true)}${option('fast','快速档 · Seedream 5.0 Flash',p.fast.configured)}${option('advanced','进阶档 · Qwen-Image 3.0 Pro',p.advanced.configured)}</select><span class="field-hint">快速档与进阶档按服务商标准计费。<button class="text-button" type="button" data-action="settings-from-modal">配置生图服务</button></span></div><div class="field"><label for="image-prompt">画面要求</label><textarea id="image-prompt" name="prompt" rows="5" placeholder="例如：医学会议主题，紫色科技感，柔和光影，中间留出文字区域"></textarea><span class="field-hint">系统会叠加会议文字和 Logo；会议名称与画面要求会发送给所选服务商。</span></div><div class="modal-actions"><button class="btn ghost" data-action="close-modal" type="button">取消</button><button class="btn" type="submit">${icons('spark')} 开始生成</button></div></form>`);
  $('#image-form').onsubmit=e=>{e.preventDefault();const form=new FormData(e.target), tier=form.get('tier');state.imageTier=tier;closeModal();handleAI('image',{prompt:form.get('prompt'),tier,kind:state.kind})}
}
document.addEventListener('submit',async e=>{
  const form=e.target;if(!form.matches('[data-provider-form]'))return;
  e.preventDefault();const button=form.querySelector('button[type="submit"]'), error=form.querySelector('.provider-error');
  button.disabled=true;error.textContent='';
  try{const tier=form.dataset.providerForm;state.imageProviders=await api(`/api/image-providers/${tier}`,{method:'PUT',body:Object.fromEntries(new FormData(form))});render();toast('配置已保存，尚未验证服务权限')}
  catch(err){error.textContent=err.message;button.disabled=false}
});
document.addEventListener('input',e=>{if(!state.meeting||state.view!=='meeting')return;const el=e.target,d=state.meeting.data;if(el.hasAttribute('data-title')){state.meeting.title=el.value;markDirty()}else if(el.dataset.field){d[el.dataset.field]=el.value;markDirty()}else if(el.dataset.agenda!==undefined){d.agenda[Number(el.dataset.agenda)][el.dataset.key]=el.value;markDirty()}else if(el.dataset.design){d.design[state.kind][el.dataset.design]=el.type==='number'?Number(el.value):el.value;markDirty()}});
document.addEventListener('change',async e=>{const el=e.target;if(el.dataset.upload){try{await uploadFile(el)}catch(err){toast(err.message)}}else if(el.dataset.design){state.meeting.data.design[state.kind][el.dataset.design]=el.type==='number'?Number(el.value):el.value;markDirty();if(state.materialTab==='generate'&&['width','height'].includes(el.dataset.design))void refreshKVFit()}});
document.addEventListener('click',async e=>{const btn=e.target.closest('[data-action]');if(!btn)return;const a=btn.dataset.action;try{
 if(a==='auth-switch')return authView(btn.dataset.mode);if(a==='close-modal')return closeModal();if(a==='home'){if(state.meeting)await leaveMeeting();state.view='home';state.seriesId=null;return render()}if(a==='back'){await leaveMeeting();state.view='home';return render()}if(a==='logout'){if(state.dirty)await saveCurrent(true);await api('/api/logout',{method:'POST'});state.user=null;state.meeting=null;state.series=[];state.meetings=[];return authView()}
 if(a==='new-series')return newSeriesModal();if(a==='new-meeting')return newMeetingModal();if(a==='demo')return createDemo();if(a==='open-series'){if(state.meeting)await leaveMeeting();state.seriesId=Number(btn.dataset.id);state.view='series';return render()}if(a==='open-meeting')return openMeeting(Number(btn.dataset.id));
 if(a==='settings'||a==='settings-from-modal'){closeModal();if(state.dirty)await saveCurrent(true);await refreshConnections();state.view='settings';return render()}if(a==='refresh-pi'){await refreshConnections();render();return toast('连接状态已刷新')}if(a==='launch-pi'){const r=await api('/api/pi/login',{method:'POST'});return toast(r.opened?'已打开 Pi 终端，请按提示登录':'请打开 '+r.command_path)}
 if(a==='remove-image-provider'){if(!confirm('移除该档位已保存的 API 配置？'))return;state.imageProviders=await api(`/api/image-providers/${btn.dataset.tier}`,{method:'DELETE'});render();return toast('配置已移除')}
 if(a==='save'){await saveCurrent();return}if(a==='tab'){if(state.dirty)await saveCurrent(true);state.tab=btn.dataset.tab;return render()}if(a==='add-row'){state.meeting.data.agenda.push({time:'',item:'',speaker:'',note:''});markDirty();return render()}if(a==='remove-row'){state.meeting.data.agenda.splice(Number(btn.dataset.index),1);markDirty();return render()}
 if(a==='material-kind'){if(state.dirty)await saveCurrent(true);state.kind=btn.dataset.kind;state.layerIndex=0;return render()}if(a==='palette'){state.meeting.data.design[state.kind].palette=btn.dataset.palette;markDirty();await saveCurrent(true);return render()}if(a==='refresh-preview'){await saveCurrent(true);render();return toast('预览已更新')}if(a==='remove-logo'||a==='remove-background'){state.meeting.data[a==='remove-logo'?'logo_file_id':'background_file_id']=null;markDirty();await saveCurrent(true);return render()}
 if(a==='material-section'){state.materialTab=btn.dataset.section;return render()}
 if(a==='adapt-kv')return handleImage({kind:state.kind,tier:'chatgpt',adapt:true});
 if(a==='save-series-template'){await saveCurrent(true);await api(`/api/series/${state.meeting.series_id}/template`,{method:'POST',body:{meeting_id:state.meeting.id}});return toast('已保存系列默认版式，新会议将自动沿用')}
 if(a==='export'){await downloadExport(btn.dataset.file);return}
 if(a==='draft-script'){if(state.meeting.data.script&&!confirm('将替换当前串词内容，继续吗？'))return;await saveCurrent(true);const r=await api(`/api/meetings/${state.meeting.id}/draft-script`,{method:'POST'});state.meeting.data.script=r.script;markDirty();await saveCurrent(true);render();return toast('模板串词已生成，请核对')}
 if(a==='ai-analyze')return handleAI('analyze');if(a==='ai-script'){if(state.meeting.data.script&&!confirm('将替换当前串词内容，继续吗？'))return;return handleAI('script')}if(a==='ai-image')return imagePromptModal();
 }catch(err){toast(err.message)}});
(async()=>{try{const r=await api('/api/session');state.user=r.user;if(state.user){await refreshList();await resumeImageTask();render()}else authView()}catch(e){app.innerHTML=`<div class="initial-loader">无法连接本地服务：${esc(e.message)}</div>`}})();
