// Project, KV and final-agenda workflow. Loaded before app.js; handlers run
// only after the application has initialized its shared state.
function libraryPage(){
  const {projects,kvs}=state.library;
  const projectRows=projects.map(p=>`<div class="library-row"><div class="library-thumb">${p.logo_asset_id?`<img src="/api/library/assets/${p.logo_asset_id}" alt="">`:'<span>无 Logo</span>'}</div><div class="library-info"><strong>${esc(p.name)}</strong><span>${esc(p.organization||'机构待填写')}${p.shared?' · 本机共享':''}</span></div>${p.editable?`<button class="btn secondary sm" data-action="edit-project" data-id="${p.id}">编辑</button>`:'<span class="status-pill">仅可使用</span>'}</div>`).join('');
  const labels={agenda:'日程',slide:'串场',cover:'串场封面',bio:'嘉宾简介',card:'双面席卡'};
  const kvRows=kvs.map(k=>`<div class="library-row"><div class="library-thumb">${k.assets.agenda?`<img src="/api/library/assets/${k.assets.agenda}" alt="">`:'<span>KV</span>'}</div><div class="library-info"><strong>${esc(k.name)}</strong><span>${Object.entries(labels).filter(([key])=>k.assets[key]).map(([,label])=>label).join('、')||'尚无底图'}${k.shared?' · 本机共享':''}</span></div>${k.editable?`<button class="btn secondary sm" data-action="edit-kv" data-id="${k.id}">编辑</button>`:'<span class="status-pill">仅可使用</span>'}</div>`).join('');
  return shell(`<div class="page-head"><div><h1>项目与 KV</h1><p>保存项目对应的机构 Logo 和固定底图，制作会议时直接选择。</p></div>${state.meeting?'<button class="btn secondary" data-action="back-to-meeting">返回当前会议</button>':''}</div><div class="library-layout"><section class="panel"><div class="panel-heading"><div><h2>项目与机构</h2><p>一个项目关联一个机构和 Logo。</p></div><button class="btn secondary sm" data-action="new-project">${icons('plus')} 新增项目</button></div>${projectRows||'<div class="empty">还没有项目，先添加项目名称与 Logo。</div>'}</section><section class="panel"><div class="panel-heading"><div><h2>固定 KV</h2><p>分别保存日程、串场和双面席卡底图。</p></div><button class="btn secondary sm" data-action="new-kv">${icons('plus')} 新增 KV</button></div>${kvRows||'<div class="empty">还没有 KV，可上传无 Logo 的固定底图。</div>'}</section></div>`, '项目与 KV');
}
function templatePicker(){
  const d=state.meeting.data,{projects,kvs}=state.library;
  const options=(items,id)=>items.map(x=>`<option value="${x.id}" ${x.id===id?'selected':''}>${esc(x.name)}</option>`).join('');
  return `<section class="panel"><div class="panel-heading"><div><h2>项目与固定 KV</h2><p>选择项目后应用对应机构和 Logo；KV 保持原样，仅叠加会议内容。</p></div><button class="text-button" data-action="library">管理项目与 KV</button></div><div class="two-col"><div class="field"><label for="project-select">项目名称</label><select id="project-select"><option value="">请选择项目</option>${options(projects,d.library_project_id)}</select></div><div class="field"><label for="kv-select">固定 KV</label><select id="kv-select"><option value="">请选择 KV</option>${options(kvs,d.library_kv_id)}</select></div></div><button class="btn secondary sm" data-action="apply-library">应用到本场会议</button><span class="field-hint"> 应用后会保存本场会议的素材快照。</span></section>`;
}
function agendaWorkflow(){
  const d=state.meeting.data,final=Array.isArray(d.final_agenda)&&d.final_agenda.length&&JSON.stringify(d.final_agenda)===JSON.stringify(d.agenda);
  return `<section class="panel"><div class="panel-heading"><div><h2>定稿与席卡</h2><p>先按当前日程制作串场，最终确认后再核对老师名单并生成席卡。</p></div><span class="status-pill ${final?'good':''}">${final?'日程已确认':'日程待确认'}</span></div><div class="workflow-actions"><button class="btn secondary sm" data-action="extract-people">从日程提取老师</button><button class="btn secondary sm" data-action="finalize-agenda">确认日程并生成名单</button><button class="btn sm" data-action="export" data-file="final-cards.pdf">${icons('download')} 双面席卡 PDF</button></div><div class="field-hint">确认会根据日程重新生成名单，请在上方核对修改；日程变更后需要重新确认。</div></section>${d.kv_agenda_file_id?`<section class="panel"><div class="panel-heading"><div><h2>KV 日程预览</h2><p>固定底图保持不变，预览基于上一次保存的资料。</p></div></div><img class="agenda-kv-preview" src="/api/meetings/${state.meeting.id}/preview/agenda-kv?t=${Date.now()}" alt="当前 KV 日程预览" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><div class="empty" hidden>暂时无法预览，请填写并保存日程，或检查内容是否超出页面。</div><div class="workflow-actions"><button class="btn secondary sm" data-action="export" data-file="agenda-kv.png">导出 PNG</button><button class="btn secondary sm" data-action="export" data-file="agenda-kv.pdf">导出 PDF</button></div></section>`:''}`;
}
function transitionPanel(){
  const d=state.meeting.data,rows=(d.agenda||[]).filter(x=>String(x.item||'').trim()),profiles=d.profiles||[];
  const person=(p,i)=>`<div class="profile-editor"><div class="profile-header"><strong>嘉宾 ${i+1}</strong><button class="text-button" data-action="remove-profile" data-index="${i}">移除</button></div><div class="two-col"><div class="field"><label for="profile-name-${i}">姓名</label><input id="profile-name-${i}" data-profile="${i}" data-profile-key="name" value="${esc(p.name||'')}"></div><div class="field"><label for="profile-org-${i}">单位／职务</label><input id="profile-org-${i}" data-profile="${i}" data-profile-key="organization" value="${esc(p.organization||'')}"></div></div><div class="field"><label for="profile-bio-${i}">简介</label><textarea id="profile-bio-${i}" data-profile="${i}" data-profile-key="bio" rows="4">${esc(p.bio||'')}</textarea></div><div class="field"><label for="profile-photo-${i}">照片</label><input id="profile-photo-${i}" type="file" data-portrait="${i}" accept="image/png,image/jpeg,image/webp">${p.photo_file_id?`<div class="profile-photo"><img src="/api/files/${p.photo_file_id}" alt="${esc(p.name||'嘉宾')}照片"><button class="text-button" data-action="remove-portrait" data-index="${i}">移除照片</button></div>`:''}</div></div>`;
  return `<div><section class="panel"><div class="panel-heading"><div><h2>现场串场</h2><p>按照当前日程依次生成切换页；讨论备注会生成相应说明页。</p></div></div>${rows.length?`<ol class="transition-order">${rows.map(x=>`<li><span>${esc(x.time||'时间待定')}</span><strong>${esc(x.item)}</strong><small>${esc(x.speaker||'')}</small></li>`).join('')}</ol>`:'<div class="empty">先填写会议日程，再生成串场。</div>'}<div class="workflow-actions"><button class="btn" data-action="export" data-file="transition.pptx">${icons('download')} 生成串场 PPT</button></div><div class="helper-note">导出基于当前日程；修改日程或嘉宾资料后请重新导出。</div></section><section class="panel"><div class="panel-heading"><div><h2>嘉宾介绍页</h2><p>需要照片和简介页吗？填写资料后会在对应环节自动加入；没有资料时仅生成环节页。</p></div></div><div class="workflow-actions"><button class="btn secondary sm" data-action="suggest-profiles">按日程添加嘉宾</button><button class="btn secondary sm" data-action="add-profile">添加嘉宾</button></div>${profiles.length?profiles.map(person).join(''):'<div class="empty">尚未填写嘉宾资料，可按日程添加后补充照片与简介。</div>'}</section></div>`;
}
function projectModal(id){
  const p=state.library.projects.find(x=>x.id===id);
  modal(`${modalHead(p?'编辑项目':'新增项目','项目名称与对应机构 Logo 可在制作会议时选择。')}<form id="project-form"><div class="field"><label for="project-name">项目名称</label><input id="project-name" name="name" required maxlength="150" value="${esc(p?.name||'')}"></div><div class="field"><label for="project-org">学协会／基金会</label><input id="project-org" name="organization" maxlength="150" value="${esc(p?.organization||'')}"></div><div class="field"><label for="project-logo">机构 Logo</label><input id="project-logo" type="file" name="logo" accept="image/png,image/jpeg,image/webp"><span class="field-hint">${p?.logo_asset_id?'留空保持原 Logo。':'支持透明 PNG、JPG、WebP。'}</span></div><label class="share-option"><input type="checkbox" name="shared" ${p?.shared?'checked':''}> 允许本机其他账号选择此项目和 Logo</label><div class="modal-error"></div><div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn" type="submit">保存项目</button></div></form>`);
  $('#project-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('[type=submit]');button.disabled=true;try{await api('/api/library/projects'+(p?'/'+p.id:''),{method:p?'PUT':'POST',body:new FormData(e.target)});state.library=await api('/api/library');closeModal();render();toast('项目已保存')}catch(err){$('.modal-error').textContent=err.message;button.disabled=false}};
}
function kvModal(id){
  const k=state.library.kvs.find(x=>x.id===id);
  const file=(key,label,hint)=>`<div class="field"><label for="kv-${key}">${label}${k?.assets[key]?'（已上传）':''}</label><input id="kv-${key}" type="file" name="${key}" accept="image/png,image/jpeg,image/webp"><span class="field-hint">${hint}${k?.assets[key]?' 留空保持原图。':''}</span></div>`;
  modal(`${modalHead(k?'编辑固定 KV':'新增固定 KV','上传无 Logo 的底图；不同用途可使用同一视觉的不同尺寸。')}<form id="kv-form"><div class="field"><label for="kv-name">KV 名称</label><input id="kv-name" name="name" required maxlength="150" value="${esc(k?.name||'')}"></div>${file('agenda','日程底图','建议 A4 竖版，保留日程信息区域。')}${file('slide','串场切换页底图','建议 16:9 横版，保留文字区域。')}${file('cover','串场封面底图','建议 16:9 横版。')}${file('bio','嘉宾简介页底图','建议 16:9 横版，保留照片与简介区域。')}${file('card','双面席卡底图','建议 A4 竖版，上部留白，中段倒置、下段正向。')}<label class="share-option"><input type="checkbox" name="shared" ${k?.shared?'checked':''}> 允许本机其他账号选择此 KV</label><div class="modal-error"></div><div class="modal-actions"><button type="button" class="btn ghost" data-action="close-modal">取消</button><button class="btn" type="submit">保存 KV</button></div></form>`,true);
  $('#kv-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('[type=submit]');button.disabled=true;try{await api('/api/library/kvs'+(k?'/'+k.id:''),{method:k?'PUT':'POST',body:new FormData(e.target)});state.library=await api('/api/library');closeModal();render();toast('KV 已保存')}catch(err){$('.modal-error').textContent=err.message;button.disabled=false}};
}
document.addEventListener('click',async e=>{
  const button=e.target.closest('[data-action]');if(!button)return;
  const action=button.dataset.action;
  if(!['library','back-to-meeting','new-project','edit-project','new-kv','edit-kv','apply-library','extract-people','finalize-agenda','suggest-profiles','add-profile','remove-profile','remove-portrait'].includes(action))return;
  try{
    if(action==='library'){if(state.dirty)await saveCurrent(true);state.library=await api('/api/library');state.view='library';render();return}
    if(action==='back-to-meeting'){state.view='meeting';render();return}
    if(action==='new-project'||action==='edit-project'){projectModal(Number(button.dataset.id));return}
    if(action==='new-kv'||action==='edit-kv'){kvModal(Number(button.dataset.id));return}
    if(action==='add-profile'){(state.meeting.data.profiles ||= []).push({name:'',organization:'',bio:'',photo_file_id:null});markDirty();render();return}
    if(action==='remove-profile'){if(!confirm('移除这位嘉宾的资料？'))return;state.meeting.data.profiles.splice(Number(button.dataset.index),1);markDirty();render();return}
    if(action==='remove-portrait'){state.meeting.data.profiles[Number(button.dataset.index)].photo_file_id=null;markDirty();render();return}
    if(action==='suggest-profiles'){
      await saveCurrent(true);const people=await api(`/api/meetings/${state.meeting.id}/agenda-people`),profiles=state.meeting.data.profiles ||= [];
      let added=0;for(const name of people.names)if(!profiles.some(p=>p.name===name)){profiles.push({name,organization:'',bio:'',photo_file_id:null});added++}
      markDirty();await saveCurrent(true);render();toast(`已添加 ${added} 位嘉宾，请补充资料`);return;
    }
    if(action==='apply-library'){
      await saveCurrent(true);const project_id=Number($('#project-select').value)||null,kv_id=Number($('#kv-select').value)||null;
      await api(`/api/meetings/${state.meeting.id}/library`,{method:'POST',body:{project_id,kv_id}});
      state.meeting=await api(`/api/meetings/${state.meeting.id}`);render();toast('项目与 KV 已应用');return;
    }
    if(action==='extract-people'){
      if(state.meeting.data.guests.trim()&&!confirm('用日程中的姓名替换当前名单？'))return;
      await saveCurrent(true);const result=await api(`/api/meetings/${state.meeting.id}/agenda-people`);
      state.meeting.data.guests=result.names.join('\n');markDirty();await saveCurrent(true);render();
      if(result.unresolved.length)modal(`${modalHead('请核对老师名单','部分日程人员描述无法自动识别，请检查并手动补充。')}<p>${result.unresolved.map(esc).join('<br>')}</p><div class="modal-actions"><button class="btn" data-action="close-modal">知道了</button></div>`);
      else toast(`已提取 ${result.names.length} 位，请核对名单`);return;
    }
    if(action==='finalize-agenda'){
      await saveCurrent(true);const result=await api(`/api/meetings/${state.meeting.id}/finalize-agenda`,{method:'POST'});
      state.meeting=await api(`/api/meetings/${state.meeting.id}`);render();
      if(result.people.unresolved.length)modal(`${modalHead('请核对老师名单','以下人员描述无法自动识别，请在名单中手动补充。')}<p>${result.people.unresolved.map(esc).join('<br>')}</p><div class="modal-actions"><button class="btn" data-action="close-modal">知道了</button></div>`);
      else toast('最终日程已确认，请核对老师名单');return;
    }
  }catch(err){toast(err.message)}
});
document.addEventListener('input',e=>{
  const el=e.target;if(el.dataset.profile===undefined||!state.meeting)return;
  const item=state.meeting.data.profiles?.[Number(el.dataset.profile)];
  if(item&&['name','organization','bio'].includes(el.dataset.profileKey)){item[el.dataset.profileKey]=el.value;markDirty()}
});
document.addEventListener('change',async e=>{
  const el=e.target;if(el.dataset.portrait===undefined||!state.meeting||!el.files[0])return;
  try{const form=new FormData();form.append('kind','portrait');form.append('file',el.files[0]);
    const result=await api(`/api/meetings/${state.meeting.id}/upload`,{method:'POST',body:form});
    state.meeting.data.profiles[Number(el.dataset.portrait)].photo_file_id=result.id;markDirty();await saveCurrent(true);render();toast('嘉宾照片已保存');
  }catch(err){toast(err.message)}
});
document.addEventListener('change',async e=>{
  const el=e.target;if(!['project-select','kv-select'].includes(el.id)||!el.value||!state.meeting)return;
  el.disabled=true;
  try{
    await saveCurrent(true);
    const body=el.id==='kv-select'?{kv_id:Number(el.value)}:{project_id:Number(el.value)};
    await api(`/api/meetings/${state.meeting.id}/library`,{method:'POST',body});
    state.meeting=await api(`/api/meetings/${state.meeting.id}`);render();toast(el.id==='kv-select'?'KV 已应用到本场会议':'项目和 Logo 已应用');
  }catch(err){el.disabled=false;toast(err.message)}
});
