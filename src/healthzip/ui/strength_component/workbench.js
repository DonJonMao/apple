/* Local Streamlit v1 component. All facts are acknowledged by TrainingService. */
(() => {
  'use strict';
  const app = document.getElementById('app');
  app.dataset.testid = 'strength-app';
  const icons = {
    back:'M15 18l-6-6 6-6', close:'M6 6l12 12M18 6L6 18', plus:'M12 5v14M5 12h14',
    check:'M5 12l4 4L19 6', more:'M5 12h.01M12 12h.01M19 12h.01',
    next:'M9 6l6 6-6 6', search:'M21 21l-4.4-4.4M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0',
    dumbbell:'M6 5v14M3 8v8M18 5v14M21 8v8M6 12h12',
    clock:'M12 8v4l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
    note:'M8 6h12v15H4V6h4M9 3h6v5H9zM8 12h8M8 16h6',
    history:'M3 3v6h6M3.5 9a9 9 0 1 1 .2 7M12 7v5l3 2',
    settings:'M4 6h16M7 3v6M4 18h16M17 15v6M4 12h16M12 9v6',
    copy:'M9 9h12v12H9zM15 9V3H3v12h6', trash:'M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7',
    calendar:'M4 5h16v16H4zM8 3v4M16 3v4M4 10h16', edit:'M4 20l4-1L21 6l-4-4L4 15v5M14 5l4 4',
    star:'M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z',
    info:'M12 11v6M12 7h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
    undo:'M3 4v6h6M3 10a8 8 0 1 1 3 10', play:'M8 4l12 8-12 8z'
  };
  const I = name => `<svg class="hz-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${(icons[name]||icons.info).split(/(?=M)/).filter(Boolean).map(d=>`<path d="${d}"/>`).join('')}</svg>`;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  const sessionScales={cr10:'CR-10（0–10）',borg6_20:'Borg（6–20）',rir_rpe10:'RIR-RPE（1–10）',Foster_modified_CR10:'Foster 修改 CR-10（回顾整场）'};
  const stateNames = {draft:'草稿',in_progress:'进行中',paused:'已暂停',completed:'已完成',aborted:'已中断',skipped:'已跳过',deleted:'已删除'};
  let snap = {}, receipt = null, scope = '', loaded = false, searchTimer = null, pending = null, notice = null;
  const initialUI = () => ({view:'home',expanded:null,query:'',region:'',equipment:'',catalogView:'all',offset:0,menus:{},collapsed:{},editing:{},drafts:{},start:{name:'',region:'',template_id:''},finish:{},scroll:{}});
  let ui = initialUI();
  let returnView = 'workbench', lastHeight = 0, clockOffset = 0, catalogLoadedAt = 0;
  const st = (type, extra={}) => window.parent.postMessage({isStreamlitMessage:true,type,...extra},'*');
  const storeKey = () => `healthzip.strength.v1:${scope}`;
  function persist(){if(!scope)return;try{const data=JSON.stringify({...ui,pending});sessionStorage.setItem(storeKey(),data);localStorage.setItem(storeKey(),data);}catch(_){notice={kind:'error',text:'浏览器未能保存本地输入，请先保存草稿后再离开。'};}}
  function load(){try{const data=JSON.parse(sessionStorage.getItem(storeKey())||localStorage.getItem(storeKey())||'null');if(data){pending=data.pending||null;delete data.pending;ui={...ui,...data,drafts:data.drafts||{}};}}catch(_){notice={kind:'error',text:'本地恢复不可用，数据库中已保存的记录仍然保留。'};}}
  function resize(){const h=Math.max(120,Math.ceil(app.getBoundingClientRect().height)+4);if(Math.abs(h-lastHeight)>1){lastHeight=h;st('streamlit:setFrameHeight',{height:h});}}
  const current = () => snap.session;
  const sid = () => current()?.id;
  const instances = () => (current()?.exercises||[]).filter(x=>!x.deleted_at);
  const sets = inst => (inst.sets||[]).filter(x=>!x.deleted_at);
  const countComplete = inst => sets(inst).filter(x=>x.completion_state==='completed').length;
  const mode = inst => inst.condition?.measurement_mode||inst.exercise?.recording_mode||'repetitions';
  const measureField = inst => ({repetitions:'reps',duration:'duration_s',distance:'distance_m'}[mode(inst)]||'reps');
  const measureLabel = inst => ({repetitions:'次数',duration:'秒数',distance:'距离（米）'}[mode(inst)]||'次数');
  const loadLabel = inst => ({bodyweight_no_external:'外部负荷（可空）',added_load_kg:'额外负重',assistance_setting:'助力',machine_setting:'刻度',plates_per_side_kg:'单边重量',per_dumbbell_kg:'单只重量'}[inst.condition?.load_basis]||'重量');
  const instance = id => instances().find(x=>String(x.id)===String(id));
  const rowById = id => instances().flatMap(x=>sets(x)).find(x=>String(x.set_uuid)===String(id));
  const sessionNotes = s => s?.notes||s?.feedback?.notes||'';
  const displayName = inst => inst.exercise?.name||inst.exercise?.name_zh||inst.name||'未命名动作';
  const identity = row => `${current()?.session_uuid||sid()}:${row.set_uuid}`;
  function draft(row){const key=identity(row);let d=ui.drafts[key];if(!d||(!d.dirty&&d.base_revision!==row.revision)){d={base_revision:row.revision,values:{},dirty:false};ui.drafts[key]=d;}return d;}
  function val(row,field){const d=draft(row);return Object.hasOwn(d.values,field)?d.values[field]:(row[field]??'');}
  function saveLocal(row,field,value){const d=draft(row);d.values[field]=value;d.dirty=true;persist();}
  const thumbnail = item => {
    const url=item.thumbnail||item.thumbnail_url||item.exercise?.thumbnail;
    return url && /^(data:image\/|blob:|\.\/|\/)/.test(url)?`<img class="thumbnail" src="${esc(url)}" alt="" loading="lazy" onerror="this.outerHTML='<span class=&quot;failure-image&quot;>无图片</span>'">`:`<span class="thumbnail placeholder">${I('dumbbell')}</span>`;
  };
  function attribution(item){const media=(item.media||[]).find(m=>m.media_type==='image'&&m.available);if(!media)return '';const license=typeof media.license==='object'?(media.license?.short_name||media.license?.full_name||'许可详见来源'):(media.license||'许可详见来源');return `<span class="source-note">图：${esc(media.author||'来源未署名')} · ${esc(license)} · 已缩放</span>`;}
  const button = (action,text,cls='secondary',attrs='')=>`<button type="button" class="${cls}" data-action="${action}" ${attrs}>${text}</button>`;
  const back = (action='back')=>button(action,I('back'),'icon','aria-label="返回"');
  function activeSession(s){return s&&!s.deleted_at&&['draft','in_progress','paused'].includes(s.session_status);}
  function date(value,withTime=false){if(!value)return '时间未知';try{return new Intl.DateTimeFormat('zh-CN',{timeZone:snap.timezone_name||snap.timezone||'Asia/Shanghai',year:'numeric',month:'numeric',day:'numeric',...(withTime?{hour:'2-digit',minute:'2-digit'}:{})}).format(new Date(value));}catch(_){return '时间未知';}}
  function elapsed(start,end){if(!start)return '时长未知';const n=(end?new Date(end).getTime():Date.now()+clockOffset)-new Date(start).getTime();if(!Number.isFinite(n)||n<0)return '时长未知';const s=Math.floor(n/1000);return `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;}
  function begin(action,payload={},options={}){
    if(pending){notice={kind:'pending',text:'正在等待上一项操作的回执。'};render();return false;}
    notice=null;const command={id:uid(),action,payload};pending={command,started:Date.now(),options};persist();st('streamlit:setComponentValue',{value:{...command,delivery:Date.now()}});render();return true;
  }
  function retry(){if(pending){pending.started=Date.now();persist();st('streamlit:setComponentValue',{value:{...pending.command,delivery:Date.now()}});render();}}
  function activateSessionForms(session, reset=false){
    if(!session)return;const key=session.session_uuid||String(session.id);
    ui.sessionForms??={};
    if(ui.formSessionKey!==key||reset){
      if(ui.formSessionKey&&!reset)ui.sessionForms[ui.formSessionKey]={rename:ui.rename,notes:ui.notes,finish:ui.finish,restTarget:ui.restTarget,restExtension:ui.restExtension,formDirty:ui.formDirty,formRevisions:ui.formRevisions,finishEdited:ui.finishEdited,formErrors:ui.formErrors,formReview:ui.formReview};
      const saved=reset?{}:(ui.sessionForms[key]||{});ui.formDirty=saved.formDirty||{};ui.formRevisions=saved.formRevisions||{};ui.finishEdited=saved.finishEdited||{};ui.formErrors=saved.formErrors||{};ui.formReview=saved.formReview||{};ui.rename=saved.rename;ui.notes=saved.notes;ui.finish=saved.finish||{};ui.restTarget=saved.restTarget;ui.restExtension=saved.restExtension;ui.formSessionKey=key;
    }
  }
  function finishReceipt(r){
    if(!pending||r?.id!==pending.command.id)return;
    const p=pending,ok=['ok','success','applied','saved'].includes(r.status)||r.success===true;
    if(ok){
      if(p.command.action==='catalog')catalogLoadedAt=Date.now();
      if(p.command.action==='save_set'){
        const row=rowById(p.command.payload.set_id);if(row){
          const key=identity(row),local=ui.drafts[key],sent=p.command.payload.changes||{},norm=v=>v==null||v===''?null:String(v);
          if(local){for(const field of Object.keys(sent)){if(Object.hasOwn(local.values,field)&&norm(local.values[field])===norm(sent[field]))delete local.values[field];}
            if(Number.isInteger(r.data?.revision)){
              local.base_revision=r.data.revision;
              if(ui.endRequested && ui.discardReviewed && Object.hasOwn(ui.discardReviewed,row.set_uuid))
                ui.discardReviewed[row.set_uuid]=r.data.revision;
            }local.dirty=Object.keys(local.values).length>0;
            if(!local.dirty){delete ui.drafts[key];delete ui.editing[row.set_uuid];}else{p.options.keepNewInput=true;if(row.completion_state==='completed')ui.editing[row.set_uuid]=true;}
          }else delete ui.editing[row.set_uuid];
          delete ui.menus[row.set_uuid];
        }
      }
      if(p.command.action==='start_session'){
        ui.session_id=sid()||r.data?.id;activateSessionForms(current(),true);ui.expanded=null;ui.collapsed={};ui.view='workbench';
        ui.region=p.command.payload.region||'';
      }
      if(p.command.action==='session'){activateSessionForms(current());ui.session_id=sid();if(ui.view==='home'||p.options.openSession)ui.view=activeSession(current())?'workbench':'detail';}
      if(p.command.action==='add_exercises'){ui.view='workbench';const added=instance(r.data?.added_instance_ids?.at(-1));if(added){ui.expanded=added.id;delete ui.collapsed?.[added.id];const row=sets(added)[0];ui.scrollTo=row?`set-row-${row.set_uuid}`:`exercise-card-${added.id}`;ui.focusSet=row?.set_uuid;}}
      if(['add_set','copy_history'].includes(p.command.action)){ui.view='workbench';ui.expanded=p.command.payload.instance_id;const list=sets(instance(ui.expanded)||{});ui.scrollTo=list.length?`set-row-${list.at(-1).set_uuid}`:null;ui.focusSet=list.at(-1)?.set_uuid;delete ui.collapsed?.[ui.expanded];}
      if(p.command.action==='end_session'){
        ui.endRequested=false; delete ui.discardReviewed; ui.view='detail';
        notice={kind:'ok',text:r.data?.discarded_draft_count
          ? `训练已结束，已放弃 ${r.data.discarded_draft_count} 个未完成组。完成记录已保留。`
          : '训练已结束，实际记录已保留。未完成组仍保持原状态。'};
      }
      if(p.command.action==='delete_session'){ui.view='home';delete ui.deleteSession;ui.undo={event_id:r.event_id||r.data?.event_id||r.data?.last_event_id||p.command.id,entity:'session',id:p.command.payload.session_id,revision:r.data?.revision};}
      if(p.command.action==='delete_set'){ui.undo={event_id:r.event_id||r.data?.event_id||r.data?.last_event_id||p.command.id,entity:'set',id:p.command.payload.set_id,revision:r.data?.revision};}
      if(p.command.action==='undo'){ui.undo=null;}
      if(p.command.action==='update_session'){
        const changes=p.command.payload.changes||{},field=Object.hasOwn(changes,'notes')?'notes':'rename',sent=field==='notes'?changes.notes:changes.name;
        ui.formDirty??={};ui.formRevisions??={};
        if(String(ui[field]??'')===String(sent??'')){delete ui.formDirty[field];if(ui.formErrors)delete ui.formErrors[field];if(ui.formReview)delete ui.formReview[field];}else{ui.formDirty[field]=true;p.options.keepNewInput=true;}
        if(Number.isInteger(r.data?.revision))ui.formRevisions[field]=r.data.revision;
        notice={kind:'ok',text:p.options.keepNewInput?'提交的训练信息已保存；之后输入的内容仍待保存。':'训练信息已保存。'};
      }
      if(p.command.action==='save_set')notice={kind:'ok',text:p.options.keepNewInput?'提交的记录已保存；之后输入的内容仍待保存。':p.command.payload.complete?'本组实际记录已保存。':'草稿已保存，可稍后继续填写。'};
      if(p.command.action==='legacy')ui.legacyReturn=true;
      if(p.options.nextView&&!p.options.keepNewInput)ui.view=p.options.nextView;
      ui.lastError=null;ui.failedCommand=null;
      if(p.options.reviewForm){ui.formReview??={};ui.formReview[p.options.reviewForm]={revision:current()?.revision,name:current()?.name,notes:sessionNotes(current()),session_rpe:current()?.session_rpe,scale:current()?.session_rpe_scale,duration:current()?.duration_seconds};}
      if(p.options.reviewConflict){ui.conflictReview??={};const row=rowById(p.options.reviewConflict);if(row)ui.conflictReview[p.options.reviewConflict]={revision:row.revision,server:{...row}};}
      if(p.command.action==='save_set'&&ui.conflictReview)delete ui.conflictReview[p.command.payload.set_id];
    }else{
      const message=r.message||r.error||'保存失败，输入已保留。';
      ui.lastError={action:p.command.action,set_id:p.command.payload.set_id,message,conflicted:r.status==='conflicted'||r.status==='conflict'};
      notice={kind:'error',text:message};ui.failedCommand=p.command;ui.endRequested=false;delete ui.discardReviewed;
      const form=p.command.action==='end_session'?'finish':p.command.action==='update_session'?(Object.hasOwn(p.command.payload.changes||{},'notes')?'notes':'rename'):null;if(form){ui.formErrors??={};ui.formErrors[form]={message,conflicted:ui.lastError.conflicted};}
    }
    pending=null;persist();
    if(ui.catalogQueued&&ui.view==='catalog')queueMicrotask(()=>queryCatalog());
    if(ok&&ui.endRequested&&p.command.action==='save_set')queueMicrotask(flushBeforeEnd);
  }
  function banners(){
    let html='';
    if(pending){const stale=Date.now()-pending.started>10000;html+=`<div class="notice pending" role="status">${I('clock')}<span>${stale?'还未收到回执，输入保留在本机。可使用同一请求重试。':pending.command.action==='catalog'?'正在搜索动作…':pending.command.action==='add_exercises'?'正在添加动作，成功后返回训练…':'正在保存本次操作；其他组可继续填写…'}</span>${stale?button('retry','重试','quiet'):''}</div>`;}
    if(notice)html+=`<div class="notice ${notice.kind==='error'?'error':''}" role="${notice.kind==='error'?'alert':'status'}"><span>${esc(notice.text)}</span>${button('dismiss',I('close'),'icon','aria-label="关闭提示"')}</div>`;
    if(ui.failedCommand&&!ui.lastError?.conflicted)html+=`<div class="notice">${button('retry-failed','重试这项操作','secondary')}</div>`;
    if(ui.undo)html+=`<div class="notice"><span>记录已删除。</span>${button('undo',`${I('undo')}撤销删除`,'quiet')}</div>`;
    return html;
  }
  function home(){
    const active=snap.active_sessions||[], month=snap.month||snap.today?.slice(0,7)||new Date().toISOString().slice(0,7);
    const selected=snap.selected_date||snap.today||`${month}-01`,sessions=Array.isArray(snap.calendar)?snap.calendar:(snap.calendar?.sessions||[]);
    const parts=month.split('-').map(Number), total=new Date(parts[0],parts[1],0).getDate(),offset=(new Date(parts[0],parts[1]-1,1).getDay()+6)%7;
    const daily={};sessions.forEach(s=>{const d=s.date||s.local_date||s.session_date;if(d)(daily[d]??=[]).push(s);});
    const chosen=daily[selected]||[];
    const hero=active.length?`<div class="hero"><div class="eyebrow">当前训练</div><h2>继续本次训练</h2><p>${esc(active.length===1?active[0].name||'自由训练':`${active.length} 场训练尚未结束，选择要继续的一场。`)}</p>${active.length===1?button('open-session',`${I('play')}继续训练`,'primary',`data-id="${esc(active[0].id)}" data-testid="continue-training"`):active.map(s=>button('open-session',`${esc(s.name||'自由训练')} · ${date(s.started_at)}`,'secondary full tight',`data-id="${esc(s.id)}"`)).join('')}${button('open-start','另开一场','quiet tight')}</div>`:`<div class="hero" data-testid="training-empty-state"><h2>开始训练</h2><p>添加动作，逐组记录重量、次数与 RIR。</p>${button('open-start',`${I('plus')}开始训练`,'primary full','data-testid="start-training"')}</div>`;
    let days='';for(let n=0;n<offset;n++)days+='<div></div>';for(let d=1;d<=total;d++){const key=`${month}-${String(d).padStart(2,'0')}`,rows=daily[key]||[],completed=rows.reduce((n,s)=>n+(s.completed_sets||0),0);days+=`<button class="day ${key===snap.today?'today':''} ${key===selected?'selected':''}" data-action="select-date" data-date="${key}" aria-label="${key}${rows.length?`，${rows.length}场训练，${completed}组完成`: '，暂无记录'}" aria-pressed="${key===selected}"><span>${d}</span>${rows.length?`<span class="count">${rows.length>1?`${rows.length}场`:`${completed}组`}</span><i class="dot"></i>`:'<span class="count">&nbsp;</span>'}</button>`;}
    return {top:`<div class="title"><div class="eyebrow">训练工作区</div><h1>力量训练</h1></div>${button('health-overview','健康总览','quiet','aria-label="返回健康总览"')}${button('management',I('settings'),'icon','aria-label="训练管理"')}`,body:`${hero}<div class="calendar" data-testid="training-calendar"><div class="calendar-heading">${button('prev-month',I('back'),'icon','aria-label="上个月"')}<h2>${parts[0]} 年 ${parts[1]} 月</h2>${button('next-month',I('next'),'icon','aria-label="下个月"')}</div><div class="calendar-grid">${['一','二','三','四','五','六','日'].map(x=>`<div class="weekday">${x}</div>`).join('')}${days}</div><div class="calendar-note"><span><i class="outline-legend"></i>今天</span><span><i class="dot-legend"></i>有训练记录</span>${button('today','回到今天','quiet')}</div></div><div class="section-heading"><h3>${esc(selected)} 的训练</h3><small>${chosen.length?`${chosen.length} 场`:'暂无记录'}</small></div><div class="stack">${chosen.map(sessionCard).join('')||'<div class="empty"><p>这一天暂无训练记录。</p><small>未记录不代表没有训练。</small></div>'}</div>${button('open-plan','使用已有计划','quiet spaced')}`,testid:'strength-home'};
  }
  function sessionCard(s){return `<article class="session-card" data-testid="session-card-${esc(s.id)}"><button class="session-card-open" data-action="open-session" data-id="${esc(s.id)}" aria-label="查看训练：${esc(s.name||'自由训练')}"><div class="row between"><h3>${esc(s.name||'自由训练')}</h3><span class="badge ${activeSession(s)?'green':''}">${stateNames[s.session_status]||'状态未知'}</span></div><p>${esc((s.exercise_names||[]).slice(0,3).join(' · ')||'尚未添加动作')}</p><div class="session-meta"><span>${s.started_at?date(s.started_at,true):'发生时间未知'}</span><span>${s.completed_sets||0} 组完成 · ${s.exercise_count||0} 个动作</span></div></button><div class="session-card-actions">${button('home-delete-session',`${I('trash')}删除训练`,'danger',`data-id="${esc(s.id)}" aria-label="删除训练：${esc(s.name||'自由训练')}" ${pending?'disabled':''}`)}</div></article>`;}
  function start(){const t=ui.start;return {top:`${back('home')}<div class="title"><h1>开始今天的训练</h1><div class="caption">${esc(snap.today||'')} · 使用真实当前时间</div></div>`,body:`<div class="stack"><button class="choice-card ${!t.template_id?'selected':''}" data-action="choose-free"><div class="row between"><h3>自由训练</h3>${!t.template_id?I('check'):I('dumbbell')}</div><p>先选动作，直接记录。无需模板或参考组。</p></button><div class="form-panel stack"><div><div class="subtle-title">今天准备练（可选）</div><div class="chips">${(snap.regions||[]).map(r=>button('start-region',r.name,'chip '+(t.region===r.id?'active':''),`data-id="${esc(r.id)}" aria-pressed="${t.region===r.id}"`)).join('')}</div></div></div><details class="form-panel" ${t.template_id?'open':''}><summary>使用已有计划</summary><label class="spaced">选择已保存的计划<select data-local="start.template_id" aria-label="已有计划"><option value="">不使用计划</option>${(snap.templates||[]).map(tpl=>`<option value="${esc(tpl.id)}" ${t.template_id===tpl.id?'selected':''}>${esc(tpl.name)}</option>`).join('')}</select></label>${!(snap.templates||[]).length?'<p class="helper">还没有模板，可以直接自由训练。</p>':''}</details><p class="helper">浏览历史日期不会改变这场新训练的开始时间。</p></div>`,footer:button('start-session',`${I('play')}${t.template_id?'开始计划训练':'开始自由训练'}`,'primary full',`data-testid="start-free-training" ${pending?'disabled':''}`)};}
  function workout(detail=false){const s=current();if(!s)return {top:`${back('home')}<h1>读取训练</h1>`,body:'<div class="empty">请选择一场训练，或回到首页开始。</div>'};
    const list=instances(), all=list.flatMap(sets),done=all.filter(x=>x.completion_state==='completed').length;
    if(!list.some(x=>String(x.id)===String(ui.expanded))&&list.length)ui.expanded=list[0].id;
    return {top:`${back('home')}<div class="title">${detail?`<h1>${esc(s.name||'自由训练')}</h1>`:button('rename',esc(s.name||'自由训练')+' '+I('edit'),'session-name','aria-label="修改训练名称"')}<div class="caption"><span data-clock="session">${elapsed(s.started_at,s.ended_at)}</span> · ${done} 组完成 · ${list.length} 个动作</div></div>${detail?button('session-more',I('more'),'icon','aria-label="历史训练更多操作"'):button('open-finish','结束训练','end-button','data-testid="end-training"')}`,body:`${detail?`<div class="readonly-note">${stateNames[s.session_status]||'历史训练'} · ${date(s.started_at,true)}${s.deleted_at?' · 已删除':''}。实际记录保留原发生时间。</div>`:''}<div class="workout-summary"><span>${detail?'训练记录':'逐组记录本次实际'}</span><span>RIR 可留空，0 表示无剩余次数</span></div>${list.length?list.map(inst=>exerciseCard(inst,detail)).join(''):`<div class="empty">${I('dumbbell').replace('<svg','<svg class="empty-icon"')}<h3>准备好，开始第一组</h3><p>先添加今天想练的动作。新动作会准备一个空白草稿组。</p>${!detail?button('open-catalog',`${I('plus')}选择动作`,'primary'):''}</div>`}${sessionNotes(s)?`<div class="form-panel spaced"><h3>训练备注</h3><p class="helper">${esc(sessionNotes(s))}</p></div>`:''}`,footer:detail?`${button('home',`${I('calendar')}返回月历`,'secondary grow')}${button('session-more',I('more')+' 更多','quiet')}`:`${button('open-catalog',`${I('plus')}添加动作`,'primary','id="add-exercises-entry" data-testid="add-exercises"')}${button('notes',I('note')+'<span>训练备注</span>','icon-label')}${button('workout-more',I('more')+'<span>更多</span>','icon-label')}`,testid:detail?'training-detail':'training-workbench'};
  }
  function exerciseCard(inst,detail){const rows=sets(inst),done=countComplete(inst),open=!ui.collapsed?.[inst.id];const basis=inst.load_label||inst.condition?.load_label||({external_total_kg:'外部总重',plates_per_side_kg:'单边配重',per_dumbbell_kg:'每只哑铃',dumbbells_total_kg:'哑铃合计',single_implement_kg:'单件器械',machine_setting:'器械刻度',bodyweight_no_external:'自重',added_load_kg:'额外负重',assistance_setting:'助力大小',band_configuration:'弹力带设置'}[inst.condition?.load_basis]||'口径待确认');
    return `<article class="exercise-card ${open?'expanded':''}" data-testid="exercise-card-${esc(inst.id)}" id="exercise-card-${esc(inst.id)}"><div class="exercise-header"><button class="card-toggle" data-action="toggle-card" data-id="${esc(inst.id)}" aria-expanded="${open}" aria-label="${esc(displayName(inst))}，${done}组完成，共${rows.length}组">${thumbnail(inst)}<span class="grow"><span class="exercise-name">${esc(displayName(inst))}</span><span class="exercise-caption"><span>${esc(inst.equipment_label||'器械待确认')} · ${esc(basis)}</span><span>${done} / ${rows.length} 组完成</span>${rows.some(r=>r.completion_state==='skipped')?`<span>${rows.filter(r=>r.completion_state==='skipped').length} 组跳过</span>`:''}${rows.some(r=>r.set_type==='warmup')?`<span>${rows.filter(r=>r.set_type==='warmup').length} 组热身</span>`:''}</span>${attribution(inst)}<span class="progress-dots">${rows.map(r=>`<i class="progress-dot ${esc(r.completion_state)}" title="${stateNames[r.completion_state]||'未知'}"></i>`).join('')}</span></span></button>${button('instance-more',I('more'),'icon',`data-id="${esc(inst.id)}" aria-label="${esc(displayName(inst))}设置"`)}</div>${open?`<div class="card-body" data-testid="expanded-exercise"><div class="measurement-caption">本次实际 · ${esc(basis)}${!inst.catalog_active?' · 目录已停用，保留历史定义':''}</div><div class="sets-header"><span>组</span><span>${loadLabel(inst)}</span><span>${measureLabel(inst)}</span><span>RIR</span><span>完成</span></div>${rows.map((r,i)=>setRow(r,inst,i,detail)).join('')||'<p class="helper">还没有组记录。</p>'}${!detail?button('add-set',`${I('plus')}添加组`,'add-row',`data-id="${esc(inst.id)}"`):''}<div class="card-actions">${button('progress','动作进展','quiet',`data-id="${esc(inst.catalog_id)}"`)}${button('history',`${I('history')}动作历史`,'quiet',`data-id="${esc(inst.id)}"`)}${inst.media?.length?button('media-details','媒体与许可信息','quiet',`data-id="${esc(inst.catalog_id)}"`):''}${!detail?button('advice','查看可选建议','quiet',`data-id="${esc(inst.id)}"`):button('comparison','历史建议与实际','quiet',`data-id="${esc(inst.id)}"`)}${!detail&&rows.length?button('copy-last','沿用上一组为草稿','quiet',`data-id="${esc(inst.id)}"`):''}</div>${!detail?`<div class="exercise-order">${button('move-up','上移','quiet',`data-id="${esc(inst.id)}" ${instances()[0]?.id===inst.id?'disabled':''}`)}${button('move-down','下移','quiet',`data-id="${esc(inst.id)}" ${instances().at(-1)?.id===inst.id?'disabled':''}`)}</div>`:''}</div>`:''}</article>`;
  }
  const setTypes = {work:'工作组', warmup:'热身组', assessment:'测试组', other:'其他组'};
  const stopReasons = {unknown:'未记录', plan_target:'达到目标', target_rir:'达到目标余力',
    technical_limit:'技术终止', volitional_failure:'力竭', pain:'疼痛或不适', other:'其他'};
  function setContextOption(row, field, label, options, disabled) {
    const selected = val(row, field) || (field === 'set_type' ? 'work' : 'unknown');
    const choices = Object.entries(options).map(([key, text]) =>
      `<option value="${key}" ${key === selected ? 'selected' : ''}>${text}</option>`).join('');
    return `<label>${label}<select aria-label="${label}" data-set="${esc(row.set_uuid)}"
      data-field="${field}" ${disabled ? 'disabled' : ''}>${choices}</select></label>`;
  }
  function setRow(row,inst,index,detail){const d=draft(row),completed=row.completion_state==='completed',editing=ui.editing[row.set_uuid],readOnly=(completed||detail)&&!editing,field=measureField(inst),hasError=ui.lastError?.set_id===row.set_uuid;
    const input=(f,label,type='decimal')=>`<label><span class="field-label">${label}</span><input type="text" inputmode="${type}" autocomplete="off" data-set="${esc(row.set_uuid)}" data-field="${f}" value="${esc(val(row,f))}" aria-label="${label}第${index+1}组" placeholder="—" ${readOnly?'readonly':''}></label>`;
    const planned=row.planned||{},pqty=planned.reps_min!=null?`${planned.reps_min}${planned.reps_max!=null&&planned.reps_max!==planned.reps_min?'–'+planned.reps_max:''} 次`:planned.duration_s!=null?`${planned.duration_s} 秒`:planned.distance_m!=null?`${planned.distance_m} 米`:'';
    const unit=val(row,'load_unit');
    return `<div class="set-block ${completed?'completed':''}" id="set-row-${esc(row.set_uuid)}" data-testid="set-row-${esc(row.set_uuid)}" data-set-id="${esc(row.set_uuid)}"><div class="set-main"><span class="set-number ${row.set_type==='warmup'?'warmup':''}" title="${setTypes[row.set_type] || '组类型未知'}">${row.set_type==='warmup'?'热':index+1}</span>${input('load_value',loadLabel(inst))}${input(field,measureLabel(inst),field==='reps'?'numeric':'decimal')}${input('rir','RIR')}<button type="button" class="complete-button ${completed?'saved':''} ${editing?'correction':''}" data-action="${readOnly?'completed-noop':'complete-set'}" data-id="${esc(row.set_uuid)}" data-instance="${esc(inst.id)}" data-state-label="${readOnly?(completed?'已完成':'未完成草稿'):editing?'保存更正':'完成本组'}" aria-label="${readOnly?(completed?'已完成':'未完成草稿'):editing?'保存更正':'完成'}第${index+1}组" ${pending?.command.payload.set_id===row.set_uuid?'disabled':''}>${editing?'更正':I(completed||!detail?'check':'clock')}</button></div><div class="set-subline"><div class="row"><select data-set="${esc(row.set_uuid)}" data-field="load_unit" aria-label="重量单位第${index+1}组" ${readOnly?'disabled':''}><option value="">单位未知</option>${['kg','lb','level','stack_level'].map(u=>`<option value="${u}" ${unit===u?'selected':''}>${({level:'刻度',stack_level:'配重刻度'})[u]||u}</option>`).join('')}</select><span class="set-state ${d.dirty?'dirty':''}" data-draft-state="${esc(row.set_uuid)}">${d.dirty?'仅存于本机，待同步':completed?'✓ 已完成':row.completion_state==='draft'?'已存草稿':stateNames[row.completion_state]||'未知'}</span></div>${button('set-menu',I('more')+' 更多','set-menu-button',`data-id="${esc(row.set_uuid)}" aria-label="第${index+1}组更多"`)}</div>${(row.pain_flag===true||row.pain_flag===1)||row.quality_status==='technique_limited'?`<div class="warning-line">${(row.pain_flag===true||row.pain_flag===1)?'有不适记录 ':''}${row.quality_status==='technique_limited'?'动作技术受限':''}</div>`:''}${pqty||planned.load_value!=null?`<div class="plan-line">本组计划：${planned.load_value!=null?esc(planned.load_value)+' '+esc(planned.load_unit||'单位未知')+' · ':''}${esc(pqty)}${planned.rir!=null?' · 目标 RIR '+esc(planned.rir):''}</div>`:''}${ui.menus[row.set_uuid]?`<div class="row-menu"><div class="set-context">${setContextOption(row,'set_type','组类型',setTypes,readOnly)}${setContextOption(row,'stop_reason','停止原因（可选）',stopReasons,readOnly)}</div>${(completed||detail)&&!editing?button('edit-completed','更正本组','secondary',`data-id="${esc(row.set_uuid)}"`):!completed?button('save-draft','保存草稿','secondary',`data-id="${esc(row.set_uuid)}" data-instance="${esc(inst.id)}"`):button('cancel-correction','取消更正','quiet',`data-id="${esc(row.set_uuid)}"`)}${button('set-details','组的详细记录','quiet',`data-id="${esc(row.set_uuid)}"`)}${!detail?button('copy-row','复制为新草稿','quiet',`data-id="${esc(row.set_uuid)}" data-instance="${esc(inst.id)}"`):''}${button('delete-set',I('trash')+' 删除','danger',`data-id="${esc(row.set_uuid)}"`)}</div>`:''}${hasError?`<div class="row-error" role="alert">${esc(ui.lastError.message)}。输入已保留。${ui.lastError.conflicted?button('review-conflict','核对最新记录','secondary full tight',`data-id="${esc(row.set_uuid)}"`):''}</div>`:''}${ui.conflictReview?.[row.set_uuid]?`<div class="conflict-panel"><strong>保存前，请核对两个版本</strong><p>最新已保存：${observation(ui.conflictReview[row.set_uuid].server)}</p><p>本地待保存：${observation({...row,...d.values})}</p><p class="helper">高级记录保留后端最新内容。确认后仅更新本地的保存版本；仍需点击完成或更正。</p>${button('rebase-draft','保留本地输入，使用当前版本','secondary full tight',`data-id="${esc(row.set_uuid)}"`)}</div>`:''}</div>`;
  }
  function catalogResults(){
    const raw=snap.catalog||{};
    if(Array.isArray(raw.search_index)){
      const query=ui.query.toLowerCase().replaceAll('ß','ss').replaceAll('ς','σ');
      const names=item=>item.search_terms||[String(item.name||'').toLowerCase()];
      const compare=(a,b)=>a<b?-1:a>b?1:0;
      let items=raw.search_index.filter(item=>(!query||names(item).join(' ').includes(query))&&(!ui.region||(item.regions||[]).includes(ui.region))&&(!ui.equipment||item.equipment_type===ui.equipment)&&(ui.catalogView!=='favorites'||item.favorite)&&(ui.catalogView!=='recent'||item.last_used_at)&&(ui.catalogView!=='custom'||item.custom));
      if(query){const score=item=>names(item).some(n=>n===query)?0:names(item).some(n=>n.startsWith(query))?1:2;items.sort((a,b)=>score(a)-score(b)||compare(a.name,b.name));}
      else if(ui.catalogView==='recent')items.sort((a,b)=>compare(b.last_used_at||'',a.last_used_at||'')||compare(b.name,a.name));
      const total=items.length,offset=Number(ui.offset||0),media=new Map((raw.items||[]).map(item=>[item.exercise_id,item]));
      items=items.slice(offset,offset+30).map(item=>({...item,thumbnail:media.get(item.exercise_id)?.thumbnail,media:media.get(item.exercise_id)?.media||[]}));
      return {items,total,offset,limit:30,query:ui.query};
    }
    const filters=raw.filters||{},matches=(raw.query||'')===ui.query&&(filters.regions?.[0]||'')===ui.region&&(filters.equipment_type||'')===ui.equipment&&(filters.view||'all')===ui.catalogView;
    return matches?raw:{};
  }
  function catalog(){const cat=catalogResults(),items=cat.items||[];return {top:`${back('close-catalog')}<div class="title"><h1>添加动作</h1><div class="caption">选中后返回训练页，填写重量、次数和 RIR</div></div>${button('close-catalog',I('close'),'icon','aria-label="关闭动作选择"')}`,filters:`<div class="search-box">${I('search')}<input data-search="catalog" id="catalog-search" data-testid="catalog-search" aria-label="搜索动作" value="${esc(ui.query)}" placeholder="搜索名称、英文或别名" autocomplete="off"></div><div class="region-scroll">${button('catalog-region','全部部位','chip '+(!ui.region?'active':''),'data-id=""')}${(snap.regions||[]).map(r=>button('catalog-region',r.name,'chip '+(ui.region===r.id?'active':''),`data-id="${esc(r.id)}"`)).join('')}</div><div class="filter-line"><div class="chips">${[['recent','最近'],['favorites','收藏'],['all','全部']].map(([key,title])=>button('catalog-view',title,'chip '+(ui.catalogView===key?'active':''),`data-id="${key}"`)).join('')}</div><select data-catalog-equipment aria-label="器械筛选"><option value="">全部器械</option>${(snap.equipment_types||[]).map(e=>`<option value="${esc(e.id)}" ${e.id===ui.equipment?'selected':''}>${esc(e.name)}</option>`).join('')}</select></div>`,body:`<div class="result-count">${cat.total??items.length} 个匹配动作${cat.total>items.length?` · 当前 ${Number(cat.offset||0)+1}–${Number(cat.offset||0)+items.length}`:''}</div><div class="catalog-list" data-catalog-query="${esc(cat.query??'')}">${items.map(item=>catalogCard(item)).join('')}</div>${!items.length?(pending?.command.action==='catalog'?'<div class="skeleton" role="status" aria-label="正在搜索动作"></div>':`<div class="empty"><h3>没有找到匹配动作</h3><p>试试别名、英文名称，或清除筛选。</p>${button('catalog-clear','清除筛选','secondary')}</div>`):''}${cat.total>(cat.limit||30)?`<div class="row between spaced">${button('catalog-prev','上一页','secondary',`${Number(cat.offset||0)===0?'disabled':''}`)}<small>${Math.floor(Number(cat.offset||0)/(cat.limit||30))+1} / ${Math.ceil(cat.total/(cat.limit||30))}</small>${button('catalog-next','下一页','secondary',`${Number(cat.offset||0)+(cat.limit||30)>=cat.total?'disabled':''}`)}</div>`:''}`,testid:'exercise-catalog'};}
  function catalogCard(item){const id=item.exercise_id||item.id,existing=instances().find(x=>x.catalog_id===id);return `<article class="catalog-card" data-testid="catalog-item-${esc(id)}"><div class="row">${thumbnail(item)}<div class="grow"><h3 class="exercise-name">${esc(item.name||item.name_zh)}</h3><div class="exercise-caption">${esc(item.equipment_label||item.equipment_type||'器械未注明')}</div>${existing?'<small>本场已存在此动作</small>':''}</div></div>${attribution(item)}<div class="catalog-controls">${button('catalog-info',I('info'),'icon',`data-id="${esc(id)}" aria-label="${esc(item.name)}详情"`)}${existing?button('catalog-existing','回到已有动作','secondary',`data-id="${esc(existing.id)}"`):''}${button('catalog-select',existing?`${I('plus')}再次添加此动作`:`${I('plus')}添加`,'select-exercise',`data-id="${esc(id)}" ${pending?'disabled':''}`)}</div>${ui.catalogDetail===id?`<div class="catalog-detail"><p>${esc(item.description||item.description_zh||'动作条件将在添加后设置；目录默认口径不代表你已经确认。')}</p><p>${({duration:'记录时长（秒）',distance:'记录距离（米）',repetitions:'记录次数'})[item.recording_mode]||'记录方式未定义'} · ${esc(item.load_label||'口径待确认')}</p>${button('favorite',item.favorite?'取消收藏':'收藏动作','quiet',`data-id="${esc(id)}"`)}${button('catalog-detail-legacy','完整详情与媒体来源','quiet',`data-id="${esc(id)}"`)}</div>`:''}</article>`;}
  function history(){if(pending?.command.action==='history')return {top:`${back('history-back')}<h1>动作历史</h1>`,body:'<div class="loading">正在读取该动作的最近一次完整训练记录…</div>'};const inst=instance(ui.historyInstance),raw=snap.history||{},result=raw.result||raw.history||raw,rows=result.records||[],latest=result.latest_session;return {top:`${back('history-back')}<div class="title"><h1>动作历史</h1><div class="caption">${esc(inst?displayName(inst):'最近一次真实训练')}</div></div>`,body:`<div class="readonly-note">上次实际仅作事实参考，不自动填入本次，也不代表今天的能力。</div>${latest?`<div class="history-card"><div class="row between"><h3>${date(latest.occurred_at||latest.started_at)}</h3><span class="badge">${stateNames[latest.session_status||latest.status]||'状态未知'}</span></div><p class="helper">该次训练的全部已记录组；记录完整性以实际采集为准。</p>${rows.map((record,i)=>{const r=record.observation||record;return `<div class="history-row"><span>${i+1}</span><div><div class="quantity">${observation(r)}</div><small>${esc(({external_total_kg:'外部总重',plates_per_side_kg:'单边配重',per_dumbbell_kg:'每只哑铃',machine_setting:'器械刻度',bodyweight_no_external:'自重',assistance_setting:'助力大小'})[r.load_basis||r.condition?.load_basis]||'口径待确认')} · ${stateNames[r.completion_state]||'状态未知'}${r.set_type==='warmup'?' · 热身组':''}${r.deleted_at?' · 已删除':''}${(r.pain_flag===true||r.pain_flag===1)?' · 有不适':''}${r.quality_status==='technique_limited'?' · 技术受限':''}</small></div>${!r.deleted_at&&activeSession(current())?button('copy-history',I('copy'),'icon',`data-id="${esc(r.set_uuid)}" aria-label="填入历史第${i+1}组为草稿"`):''}</div>`;}).join('')}</div>`:`<div class="empty"><h3>${result.status==='no_history'?'首次记录':'暂无可排序的同动作历史'}</h3><p>${result.status==='no_history'?'暂无该动作的个人训练记录，可以自由记录第一组。':'可能有时间、可见性或条件未知的记录；请查看详细说明。'}</p></div>`}${rows.some(r=>r.daily_comparability?.comparable===false)?'<p class="helper spaced">部分条件与本次不完全可比。保留原值，不把不同口径换算成统一重量。</p>':''}${(result.unranked_records||[]).length?`<div class="form-panel spaced"><h3>时间未知的实际记录</h3>${result.unranked_records.map(r=>`<p class="helper">${observation(r)}</p>`).join('')}</div>`:''}<p class="helper spaced">复制仅生成新草稿，不复制实际 RIR、疼痛、质量、时间或完成身份。</p>${button('history-details','历史与比较详情','secondary full spaced')}`};}
  function observation(r){const quantity=r.reps!=null?`${esc(r.reps)} 次`:r.duration_s!=null?`${esc(r.duration_s)} 秒`:r.distance_m!=null?`${esc(r.distance_m)} 米`:'测量未记录';return `${r.load_value!=null?`${esc(r.load_value)} ${esc(r.load_unit||'单位未知')} × `:''}${quantity} · RIR ${r.rir==null?'未知':esc(r.rir)}`;}
  function advice(){if(snap.advice_job?.status==='error')return {top:`${back('history-back')}<h1>可选建议</h1>`,body:`<div class="empty"><p>${esc(snap.advice_job.message||'建议暂不可用，实际记录仍可继续。')}</p>${button('refresh-advice','重试建议','secondary')}${button('history-back','返回继续记录','primary spaced')}</div>`};if(pending?.command.action==='advice'||['running','slow'].includes(snap.advice_job?.status))return {top:`${back('history-back')}<h1>系统可选建议</h1>`,body:`<div class="notice pending">${I('clock')}<span>${snap.advice_job?.status==='slow'?'建议核对耗时较长。':'正在核对记录、身体背景与已有规则。'}可返回继续记录，保存不受影响。</span></div>${button('history-back','返回继续记录','secondary')}`};const raw=snap.advice?.instance_id===ui.historyInstance?snap.advice:{},r=raw.result||raw.advice||raw,groups=r.groups||[];const options=(r.stale?[]:groups).flatMap((g,i)=>(g.options||[]).filter(o=>o.load!=null).map(o=>({...o,number:i+1})));return {top:`${back('history-back')}<div class="title"><h1>系统可选建议</h1><div class="caption">建议与本次实际输入分别保留</div></div>`,body:`<div class="readonly-note">这些是有依据时提供的可选安排，你可以自由记录实际训练。</div>${r.stale?`<div class="notice pending"><span>${esc(r.stale_message||'记录或依据已更新，请重新核对；原冻结结果保留。')}</span></div>${button('refresh-advice','重新核对建议','primary full spaced')}`:''}${options.map(o=>`<div class="form-panel spaced"><h3>待开始目标组 ${o.number}</h3><p class="tight">${esc(o.load)} ${esc(o.load_unit||'单位未知')} × ${esc(o.reps??'次数未指定')} 次 · 目标 RIR ${esc(o.rir??'未指定')}</p><p class="helper">${esc(o.basis?.weight_origin||'')} ${esc(o.basis?.repetitions_origin||'')} ${esc(o.basis?.rir_origin||'')}</p><p class="helper">仅适用于所列组，不自动扩展为整场处方。</p></div>`).join('')||'<div class="empty"><h3>当前没有获许可的数值选项</h3><p>仍可查看动作历史，继续原计划或自由记录。</p></div>'}${(r.unknown||[]).filter(x=>typeof x==='string'&&!/[a-z]+_[a-z]/i.test(x)).map(x=>`<p class="helper spaced">${esc(x)}</p>`).join('')}${r.created_at?`<p class="source-note">数据截止：${date(r.created_at,true)}</p>`:''}${button('advice-details','完整理由、来源与适用缺项','secondary full spaced')}`};}
  function finish(){const s=current(),list=instances(),rows=list.flatMap(sets),completed=rows.filter(x=>x.completion_state==='completed').length,unfinished=rows.filter(x=>['draft','in_progress'].includes(x.completion_state)).length,f=ui.finish;return {top:`${back('workbench')}<div class="title"><h1>结束这次训练</h1><div class="caption">${esc(s?.name||'自由训练')}</div></div>`,body:`${sessionConflict('finish')}<div class="summary-grid" data-testid="finish-summary"><div class="summary-number"><strong>${completed}</strong><span>已完成组</span></div><div class="summary-number"><strong>${list.filter(x=>countComplete(x)>0).length}</strong><span>个已完成动作</span></div><div class="summary-number"><strong>${unfinished}</strong><span>未完成组</span></div></div><p class="helper">${unfinished?`${unfinished} 个未完成组未计入完成量。`:'已保存的实际记录会保留。'}</p><p class="helper">实际经过时间：${elapsed(s?.started_at,s?.ended_at)}${!completed?' · 没有完成组，本场不会计入完成训练次数。':''}</p><label class="spaced">未完成内容<select data-local="finish.draft_policy" aria-label="未完成草稿处理"><option value="save" ${(!f.draft_policy||f.draft_policy==='save')?'selected':''}>保存未完成草稿后结束</option><option value="local" ${f.draft_policy==='local'?'selected':''}>只计已完成；待同步输入保留本机</option><option value="discard" ${f.draft_policy==='discard'?'selected':''}>结束并放弃未完成组</option></select></label>${f.draft_policy==='discard'?`<p class="helper">确认后将移除 ${unfinished} 个未完成组。更改先保存到修订历史，保存失败会保留本机输入。</p>`:''}<div class="form-panel stack spaced"><label>训练备注（可选）<textarea data-local="finish.notes" ${pending?.command.action==='end_session'?'disabled':''} aria-label="结束训练备注" placeholder="今天的感受、未完成原因…">${esc(f.notes??sessionNotes(s))}</textarea></label><div class="form-grid"><label>整场 sRPE（可选）<input inputmode="decimal" type="text" data-local="finish.session_rpe" ${pending?.command.action==='end_session'?'disabled':''} value="${esc(f.session_rpe??'')}" placeholder="${f.rpe_scale==='borg6_20'?'6–20':f.rpe_scale==='rir_rpe10'?'1–10':'0–10'}" aria-label="整场sRPE"></label><label>实际时长（分钟，可选）<input inputmode="decimal" type="text" data-local="finish.duration_minutes" ${pending?.command.action==='end_session'?'disabled':''} value="${esc(f.duration_minutes??'')}" placeholder="留空保留未知" aria-label="整场实际时长"></label></div><label>评分量表<select data-local="finish.rpe_scale" ${pending?.command.action==='end_session'?'disabled':''} aria-label="整场评分量表">${Object.entries(sessionScales).map(([key,label])=>`<option value="${key}" ${(f.rpe_scale||'cr10')===key?'selected':''}>${label}</option>`).join('')}</select></label><p class="helper">整场主观用力与组 RIR 分开记录，均为可选。</p></div>`,footer:button('confirm-end',f.draft_policy==='discard'?`放弃 ${unfinished} 个未完成组并结束`:'确认结束训练','primary full',`data-testid="confirm-end-training" ${pending?'disabled':''}`)};}
  function sessionConflict(kind){const error=ui.formErrors?.[kind],reviewed=ui.formReview?.[kind];return `${error?.conflicted?`<div class="notice error"><span>${esc(error.message)}</span></div>${button('review-form-conflict','核对最新训练信息','secondary full',`data-id="${kind}"`)}`:''}${reviewed?`<div class="conflict-panel"><strong>已读取最新保存内容</strong><p>${kind==='rename'?'训练名称：'+esc(reviewed.name):kind==='notes'?'训练备注：'+esc(reviewed.notes||'空'):esc(reviewed.name)+' · 整场评分 '+esc(reviewed.session_rpe??'未知')+' · '+esc(sessionScales[reviewed.scale]||'量表未知')+' · 时长 '+esc(reviewed.duration!=null?reviewed.duration/60+' 分钟':'未知')}</p><p class="helper">本地输入保留在下方。请对照后决定是否用它更新最新记录。</p>${button('rebase-form','保留本地输入，使用当前训练版本','secondary full tight',`data-id="${kind}"`)}</div>`:''}`;}
  function formView(kind){const s=current(),name=kind==='rename'?'修改训练名称':kind==='notes'?'训练备注':kind==='rest'?'休息计时':'训练更多操作';let body='';
    if(kind==='rename')body=`<label>训练名称<input data-local="rename" value="${esc(ui.rename??s?.name??'')}" aria-label="新的训练名称"></label>${button('save-name','保存名称','primary full spaced')}`;
    if(kind==='notes')body=`<label>训练备注<textarea data-local="notes" aria-label="训练备注">${esc(ui.notes??sessionNotes(s))}</textarea></label><p class="helper">先保存备注再结束；未提交的输入会保留在本浏览器。</p>${button('save-notes','保存备注','primary full spaced')}`;
    if(kind==='rest'){const timer=s?.rest_timer;body=`<div class="form-panel"><h3>组间休息</h3><div class="rest-clock" data-clock="rest">${restTime(timer)}</div><label>目标秒数（留空为正计时）<input inputmode="decimal" data-local="restTarget" value="${esc(ui.restTarget??'')}" placeholder="未设置" aria-label="休息目标秒数"></label>${button('timer-start','开始新的休息计时','primary full spaced')}${timer?`<div class="row wrap spaced">${button('timer-pause','暂停计时')}${button('timer-resume','继续计时')}${button('timer-skip','结束本次休息')}</div><label class="spaced">延长秒数<input inputmode="decimal" data-local="restExtension" value="${esc(ui.restExtension??'')}" placeholder="填写秒数" aria-label="延长休息秒数"></label>${button('timer-extend','延长计时','secondary full spaced')}`:''}<p class="helper spaced">这里是计时提示，不会自动记录为实际组前休息，也不会补造组开始时间。</p></div>`;}
    if(kind==='workout-more')body=`<div class="menu-list">${menu('rest','休息计时','按实际操作开始、暂停、延长或结束')}${menu('pre-state','训练前状态','可选的疲劳、酸痛与不适记录')}${menu('session-details','会话详情与历史建议','实际时间、另存模板、冻结结果')}${menu('management','训练管理','模板、动作维护、导入导出、历史冲突、离线记录器')}${menu('health-overview','返回健康总览','本次训练会保留，可稍后继续')}${activeSession(s)?menu('abort-training','中断并保留记录','明确结束本场，保留已保存事实'):''}${menu('delete-session','删除本场训练','通过真实修订删除，可撤销')}</div>`;
    if(kind==='instance-more'){const inst=instance(ui.moreInstance);body=`<h2>${esc(inst?displayName(inst):'动作设置')}</h2><div class="menu-list spaced">${menu('instance-settings','动作条件与器械档位','负荷口径、器械、侧别、ROM、定义与顺序')}${menu('history-from-more','动作历史','最近一次该动作的全部已记录组')}${menu('advice-from-more','可选建议与依据','显式更新，输入不会被覆盖')}${menu('recommendations','建议、来源与原反馈','完整依据与原有可选反馈')}${menu('comparison-from-more','建议与实际对照','保留真实身份与原冻结结果')}</div>`;}
    if(kind==='session-more')body=`<div class="menu-list">${menu('session-details','会话详情与更正','时间、可选字段、另存模板与冻结结果')}${menu('delete-session','删除本场训练','真实删除，保留撤销入口')}${menu('management','历史与冲突管理','查看删除记录、撤销及历史修订')}</div>`;
    if(kind==='confirm-delete-set')body=`<div class="empty"><h3>删除这一组？</h3><p>删除会同步到实际训练记录与统计，可通过撤销恢复。</p>${button('confirm-delete-set','确认删除本组','danger full')}</div>`;
    if(kind==='confirm-delete-session'){const target=ui.deleteSession||{name:s?.name,completed_sets:s?.completed_sets,exercise_count:instances().length};body=`<div class="empty" data-testid="session-delete-confirmation"><h3>删除“${esc(target.name||'自由训练')}”？</h3><p>${target.completed_sets||0} 组完成 · ${target.exercise_count||0} 个动作。本场记录将从日常列表和统计中排除，历史修订仍保留，可撤销。</p>${button('confirm-delete-session','确认删除本场训练','danger full',pending?'disabled':'')}${button('cancel-delete-session','取消，保留训练','secondary full tight',pending?'disabled':'')}</div>`;}
    return {top:`${back(kind==='confirm-delete-session'?'cancel-delete-session':activeSession(s)?'workbench':'detail')}<div class="title"><h1>${kind==='confirm-delete-session'?'删除训练':name}</h1></div>`,body:sessionConflict(kind)+body};
  }
  function menu(action,title,description){return button(action,`<span><strong>${title}</strong><p>${description}</p></span>${I('next')}`,'');}
  function restTime(timer){if(!timer)return '尚未开始';if(timer.clock_anomaly||timer.elapsed_seconds==null)return '时间异常，请重新确认计时起点';let elapsedSec=Number(timer.elapsed_seconds||0);if(timer.state==='running'&&snap.now)elapsedSec+=Math.max(0,(Date.now()+clockOffset-new Date(snap.now).getTime())/1000);const target=timer.target_seconds;if(target!=null)elapsedSec=Math.max(0,Number(target)-elapsedSec);const sec=Math.floor(elapsedSec);return `${target!=null?'剩余 ':''}${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}${timer.state==='paused'?' · 已暂停':timer.state==='skipped'?' · 已结束':''}`;}
  function nodeKey(node){if(node.nodeType!==1)return null;return node.id||node.getAttribute('data-testid')||(node.dataset.set?`field:${node.dataset.set}:${node.dataset.field}`:node.dataset.action?`action:${node.dataset.action}:${node.dataset.id||''}`:null);}
  function patchNode(old,next){
    if(old.nodeType!==next.nodeType||old.nodeName!==next.nodeName){old.replaceWith(next);return next;}
    if(old.nodeType===3){if(old.nodeValue!==next.nodeValue)old.nodeValue=next.nodeValue;return old;}
    for(const attr of [...old.attributes])if(!next.hasAttribute(attr.name))old.removeAttribute(attr.name);
    for(const attr of [...next.attributes])if(old.getAttribute(attr.name)!==attr.value)old.setAttribute(attr.name,attr.value);
    const previous=[...old.childNodes],keyed=new Map(previous.map(n=>[nodeKey(n),n]).filter(([key])=>key));let cursor=old.firstChild;
    for(const child of [...next.childNodes]){const key=nodeKey(child);let match=key?keyed.get(key):cursor&&!nodeKey(cursor)&&cursor.nodeName===child.nodeName?cursor:null;
      if(match){if(match!==cursor)old.insertBefore(match,cursor);patchNode(match,child);cursor=match.nextSibling;}else{old.insertBefore(child,cursor);}
    }
    while(cursor){const after=cursor.nextSibling;cursor.remove();cursor=after;}
    if(['INPUT','TEXTAREA','SELECT'].includes(old.nodeName)&&document.activeElement!==old&&old.value!==next.value)old.value=next.value;
    return old;
  }
  function render(){
    if(!loaded)return;
    const focused=document.activeElement,focusKey=focused?.dataset?.set?{set:focused.dataset.set,field:focused.dataset.field}:null;
    const sameView=ui.renderedView===ui.view;ui.renderedView=ui.view;
    let page;switch(ui.view){case'home':page=home();break;case'start':page=start();break;case'workbench':page=workout();break;case'detail':page=workout(true);break;case'catalog':page=catalog();break;case'history':page=history();break;case'advice':page=advice();break;case'finish':page=finish();break;default:page=formView(ui.view);}
    app.dataset.lastReceiptId=receipt?.id||'';app.dataset.lastReceiptStatus=receipt?.status||'';app.dataset.pendingId=pending?.command.id||'';
    const markup=`<main class="shell" data-testid="${page.testid||ui.view}"><header class="topbar">${page.top||''}</header>${page.filters?`<div class="filters">${page.filters}</div>`:''}<section class="scroll ${!page.footer?'no-footer':''}" aria-label="${ui.view==='catalog'?'动作选择内容':'训练内容'}"><div data-testid="operation-status">${banners()}</div>${page.body||''}</section>${page.footer?`<footer class="footer">${page.footer}</footer>`:''}</main>`;
    if(sameView&&app.firstElementChild&&document.createElement){const template=document.createElement('template');template.innerHTML=markup;patchNode(app.firstElementChild,template.content.firstElementChild);}else app.innerHTML=markup;
    if(ui.view==='catalog'&&pending?.command.action==='add_exercises')app.querySelectorAll('.catalog-list button').forEach(control=>{control.disabled=true;});
    resize();
    if(ui.scrollTo||ui.focusSet){const id=ui.scrollTo,set=ui.focusSet,view=ui.view;ui.scrollTo=null;ui.focusSet=null;
      // The parent applies setFrameHeight asynchronously. Scrolling before that
      // acknowledgement clamps to the previous, shorter picker viewport.
      const locate=(attempt=0)=>{if(ui.view!==view)return;if(globalThis.innerHeight<lastHeight-2&&attempt<120){requestAnimationFrame(()=>locate(attempt+1));return;}const target=set?app.querySelector(`[data-set="${CSS.escape(set)}"][data-field="load_value"]`):document.getElementById(id);target?.scrollIntoView({block:'nearest'});if(set)target?.focus({preventScroll:true});};requestAnimationFrame(()=>locate());}
    else if(focusKey&&sameView&&document.activeElement!==focused){app.querySelector(`[data-set="${CSS.escape(focusKey.set)}"][data-field="${focusKey.field}"]`)?.focus({preventScroll:true});}
    persist();
  }
  function navigate(view){ui.formDirty??={};ui.formRevisions??={};if(['rename','notes','finish'].includes(view)&&!ui.formDirty[view]){ui.formRevisions[view]=current()?.revision;if(view==='rename')ui.rename=current()?.name??'';if(view==='notes')ui.notes=sessionNotes(current());}
    if(view==='home')ui.session_id=sid()||ui.session_id;ui.view=view;ui.lastError=null;notice=null;persist();render();}
  function queryCatalog(refresh=false){if(ui.view!=='catalog'){ui.catalogQueued=false;return false;}if(!refresh&&Array.isArray(snap.catalog?.search_index)){ui.catalogQueued=false;render();return true;}if(pending){ui.catalogQueued=true;persist();return false;}ui.catalogQueued=false;return begin('catalog',{query:ui.query,regions:ui.region?[ui.region]:[],equipment_type:ui.equipment||null,view:ui.catalogView,offset:ui.offset||0,limit:30});}
  function legacy(view,id){const payload={view};if(['set_details'].includes(view)){payload.set_id=id;payload.id=id;}else if(['instance_settings','recommendations','comparison'].includes(view)){payload.instance_id=id;payload.id=id;}else if(view==='catalog_detail'){payload.exercise_id=id;payload.id=id;}else{payload.session_id=sid();payload.id=sid();}begin('legacy',payload);}
  function flushBeforeEnd(){
    if(pending||!ui.endRequested)return;
    if(ui.finish.draft_policy!=='local'){const unsaved=instances().flatMap(sets).find(row=>draft(row).dirty);if(unsaved){saveSet(unsaved.set_uuid,false);return;}}
    const f=ui.finish,changed=ui.finishEdited||{},payload={session_id:sid(),base_revision:ui.formRevisions?.finish||current().revision};
    if(changed.notes)payload.notes=f.notes??'';if(changed.session_rpe)payload.session_rpe=f.session_rpe===''?null:f.session_rpe??null;
    if(changed.session_rpe||changed.rpe_scale)payload.rpe_scale=f.rpe_scale||'cr10';
    if(changed.duration_minutes)payload.duration_minutes=f.duration_minutes===''?null:f.duration_minutes??null;
    if(f.draft_policy==='discard')payload.discard_drafts=ui.discardReviewed;
    begin('end_session',payload);
  }
  function saveSet(id,complete){const row=rowById(id),inst=instances().find(x=>sets(x).some(r=>r.set_uuid===id));if(!row||!inst)return;const d=draft(row),changes={...d.values};['load_value','reps','duration_s','distance_m','rir','load_unit'].forEach(f=>{if(Object.hasOwn(changes,f)&&changes[f]==='')changes[f]=null;});begin('save_set',{set_id:id,base_revision:d.base_revision,changes,complete,correction:Boolean(ui.editing[id])});}
  app.addEventListener('input',event=>{const el=event.target;if(el.dataset.set&&el.dataset.field){const row=rowById(el.dataset.set);if(row){saveLocal(row,el.dataset.field,el.value);const status=app.querySelector(`[data-draft-state="${CSS.escape(row.set_uuid)}"]`);if(status){status.textContent='仅存于本机，待同步';status.classList.add('dirty');}}return;}if(el.dataset.local){const path=el.dataset.local.split('.');ui.formDirty??={};ui.formRevisions??={};if(['rename','notes','finish'].includes(path[0])){ui.formDirty[path[0]]=true;ui.formRevisions[path[0]]??=current()?.revision;if(path[0]==='finish'){ui.finishEdited??={};ui.finishEdited[path[1]]=true;}}if(path.length===2){ui[path[0]]??={};ui[path[0]][path[1]]=el.value;}else ui[path[0]]=el.value;persist();if(['start.template_id','finish.rpe_scale','finish.draft_policy'].includes(el.dataset.local))render();return;}if(el.dataset.search==='catalog'){ui.query=el.value;ui.offset=0;persist();clearTimeout(searchTimer);searchTimer=setTimeout(()=>queryCatalog(),180);}});
  app.addEventListener('change',event=>{const el=event.target;if(el.matches('[data-catalog-equipment]')){ui.equipment=el.value;ui.offset=0;queryCatalog();}if(el.dataset.field||el.dataset.local)el.dispatchEvent(new Event('input',{bubbles:true}));});
  app.addEventListener('focusin',event=>{if(event.target.matches('input,textarea,select'))setTimeout(()=>event.target.scrollIntoView({block:'nearest'}),150);});
  app.addEventListener('click',event=>{const el=event.target.closest('[data-action]');if(!el||el.disabled)return;const a=el.dataset.action,id=el.dataset.id,s=current();
    if(pending?.command.action==='add_exercises'&&(a.startsWith('catalog-')||a==='close-catalog'||a==='favorite')){notice={kind:'pending',text:'正在添加动作，保存后会返回训练页。'};render();return;}
    if(a==='retry-failed'){if(!pending&&ui.failedCommand){pending={command:ui.failedCommand,started:Date.now(),options:{}};ui.failedCommand=null;retry();}return;}if(a==='dismiss'){notice=null;render();return;}if(a==='retry'){retry();return;}if(a==='completed-noop')return;
    if(a==='review-form-conflict'){begin('session',{session_id:sid()},{reviewForm:id});return;}
    if(a==='rebase-form'){const reviewed=ui.formReview?.[id];if(reviewed){ui.formRevisions??={};ui.formRevisions[id]=reviewed.revision;delete ui.formReview[id];if(ui.formErrors)delete ui.formErrors[id];notice={kind:'ok',text:'已保留本地输入。请核对后再次保存或确认结束。'};render();}return;}
    if(a==='review-conflict'){begin('session',{session_id:sid()},{reviewConflict:id});return;}
    if(a==='rebase-draft'){const row=rowById(id),reviewed=ui.conflictReview?.[id];if(row&&reviewed){const d=draft(row);d.base_revision=reviewed.revision;d.dirty=true;if(row.completion_state==='completed')ui.editing[id]=true;delete ui.conflictReview[id];ui.lastError=null;notice={kind:'ok',text:'已保留本地输入。请核对数值后，点击完成或更正保存。'};render();}return;}
    if(a==='home'){navigate('home');return;}if(a==='workbench'){navigate('workbench');return;}if(a==='detail'){navigate('detail');return;}if(a==='open-start'){begin('start_session',{});return;}if(a==='open-plan'){navigate('start');return;}
    if(a==='open-session'){begin('session',{session_id:id},{openSession:true});return;}
    if(a==='prev-month'||a==='next-month'){const [y,m]=(snap.month||snap.today.slice(0,7)).split('-').map(Number),d=new Date(y,m-1+(a==='next-month'?1:-1),1);const month=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;begin('calendar',{month,selected_date:`${month}-01`});return;}
    if(a==='select-date'){begin('calendar',{month:snap.month,selected_date:el.dataset.date});return;}
    if(a==='today'){begin('calendar',{month:snap.today.slice(0,7),selected_date:snap.today});return;}
    if(a==='start-region'){ui.start.region=ui.start.region===id?'':id;render();return;}if(a==='choose-free'){ui.start.template_id='';render();return;}
    if(a==='start-session'){begin('start_session',{region:ui.start.region||null,template_id:ui.start.template_id||null});return;}
    if(a==='open-catalog'){clearTimeout(searchTimer);ui.catalogReturnAnchor=instances().length?'add-exercises-entry':null;ui.view='catalog';ui.query='';ui.offset=0;render();queryCatalog(true);return;}
    if(a==='close-catalog'){clearTimeout(searchTimer);ui.catalogQueued=false;ui.scrollTo=ui.catalogReturnAnchor;navigate('workbench');return;}
    if(a==='catalog-clear'){ui.query='';ui.region='';ui.equipment='';ui.catalogView='all';ui.offset=0;queryCatalog();return;}
    if(a==='catalog-existing'){ui.expanded=id;delete ui.collapsed?.[id];ui.scrollTo=`exercise-card-${id}`;navigate('workbench');return;}
    if(a==='catalog-region'){ui.region=id;ui.offset=0;queryCatalog();return;}if(a==='catalog-view'){ui.catalogView=id;ui.offset=0;queryCatalog();return;}
    if(a==='catalog-prev'||a==='catalog-next'){ui.offset=Math.max(0,Number(ui.offset||0)+(a==='catalog-next'?1:-1)*30);queryCatalog();return;}
    if(a==='catalog-select'){clearTimeout(searchTimer);ui.catalogQueued=false;const item=(catalogResults().items||[]).find(x=>(x.exercise_id||x.id)===id);if(item&&s)begin('add_exercises',{session_id:sid(),base_revision:s.revision,exercises:[{exercise_id:id,allow_repeat:instances().some(x=>x.catalog_id===id)}]});return;}
    if(a==='catalog-info'){ui.catalogDetail=ui.catalogDetail===id?null:id;render();return;}
    if(a==='catalog-detail-legacy'||a==='media-details'){legacy('catalog_detail',id);return;}
    if(a==='favorite'){const item=(catalogResults().items||[]).find(x=>(x.exercise_id||x.id)===id);begin('favorite',{exercise_id:id,enabled:!item?.favorite});return;}
    if(a==='toggle-card'){ui.collapsed??={};ui.collapsed[id]=!ui.collapsed[id];render();return;}
    if(a==='move-up'||a==='move-down'){const ids=instances().map(x=>x.id),index=ids.indexOf(id),next=index+(a==='move-up'?-1:1);if(next>=0&&next<ids.length){[ids[index],ids[next]]=[ids[next],ids[index]];begin('reorder_exercises',{session_id:sid(),base_revision:s.revision,instance_ids:ids});}return;}
    if(a==='add-set'){const inst=instance(id);begin('add_set',{instance_id:id,base_revision:inst.revision});return;}
    if(a==='copy-last'){const inst=instance(id),rows=sets(inst);begin('add_set',{instance_id:id,base_revision:inst.revision,copy_from_set_id:rows.at(-1).set_uuid});return;}
    if(a==='set-menu'){ui.menus[id]=!ui.menus[id];render();return;}
    if(a==='complete-set'){saveSet(id,true);return;}if(a==='save-draft'){saveSet(id,false);return;}
    if(a==='edit-completed'){ui.editing[id]=true;draft(rowById(id));render();return;}if(a==='cancel-correction'){delete ui.editing[id];delete ui.drafts[identity(rowById(id))];render();return;}
    if(a==='copy-row'){const inst=instance(el.dataset.instance);begin('add_set',{instance_id:inst.id,base_revision:inst.revision,copy_from_set_id:id});return;}
    if(a==='set-details'){legacy('set_details',id);return;}
    if(a==='delete-set'){ui.deleteSet=id;navigate('confirm-delete-set');return;}
    if(a==='confirm-delete-set'){const row=rowById(ui.deleteSet);begin('delete_set',{set_id:row.set_uuid,base_revision:row.revision},{nextView:activeSession(s)?'workbench':'detail'});return;}
    if(a==='home-delete-session'){const sessions=Array.isArray(snap.calendar)?snap.calendar:(snap.calendar?.sessions||[]),target=sessions.find(item=>String(item.id)===String(id));if(target){ui.deleteSession={session_id:target.id,base_revision:target.revision,name:target.name,completed_sets:target.completed_sets,exercise_count:target.exercise_count,return_view:'home'};navigate('confirm-delete-session');}return;}
    if(a==='delete-session'){if(s){ui.deleteSession={session_id:s.id,base_revision:s.revision,name:s.name,completed_sets:s.completed_sets,exercise_count:instances().length,return_view:activeSession(s)?'workbench':'detail'};navigate('confirm-delete-session');}return;}
    if(a==='cancel-delete-session'){if(pending?.command.action==='delete_session')return;const next=ui.deleteSession?.return_view||'home';delete ui.deleteSession;navigate(next);return;}
    if(a==='confirm-delete-session'){const target=ui.deleteSession;if(target)begin('delete_session',{session_id:target.session_id,base_revision:target.base_revision});return;}
    if(a==='undo'){if(ui.undo)begin('undo',{event_id:ui.undo.event_id,base_revision:ui.undo.revision||1});return;}
    if(a==='history'||a==='history-from-more'){ui.historyInstance=id||ui.moreInstance;returnView=activeSession(s)?'workbench':'detail';ui.view='history';render();begin('history',{instance_id:ui.historyInstance});return;}
    if(a==='advice'||a==='advice-from-more'){ui.historyInstance=id||ui.moreInstance;returnView='workbench';ui.view='advice';render();begin('advice',{instance_id:ui.historyInstance});return;}
    if(a==='history-back'){navigate(returnView);return;}
    if(a==='copy-history'){const inst=instance(ui.historyInstance);begin('copy_history',{instance_id:inst.id,base_revision:inst.revision,source_set_id:id});return;}
    if(a==='refresh-advice'){begin('advice',{instance_id:ui.historyInstance});return;}
    if(a==='history-details'||a==='advice-details'){legacy('recommendations',ui.historyInstance);return;}
    if(a==='open-finish'){if(!ui.formDirty?.finish){ui.finish={notes:sessionNotes(s),session_rpe:s?.session_rpe??'',rpe_scale:s?.session_rpe_scale||'cr10',duration_minutes:s?.duration_seconds!=null?s.duration_seconds/60:''};ui.finishEdited={};}navigate('finish');return;}
    if(a==='confirm-end'){
      if(pending)return;
      if(ui.finish.draft_policy==='discard'){
        const unfinished=instances().flatMap(sets).filter(row=>['draft','in_progress'].includes(row.completion_state));
        ui.discardReviewed=Object.fromEntries(unfinished.map(row=>[row.set_uuid,row.revision]));
      }
      ui.endRequested=true;flushBeforeEnd();return;
    }
    if(a==='rename'||a==='notes'||a==='rest'||a==='workout-more'||a==='session-more'){navigate(a);return;}
    if(a==='save-name'){begin('update_session',{session_id:sid(),base_revision:ui.formRevisions?.rename||s.revision,changes:{name:ui.rename??s.name}},{nextView:'workbench'});return;}
    if(a==='save-notes'){begin('update_session',{session_id:sid(),base_revision:ui.formRevisions?.notes||s.revision,changes:{notes:ui.notes??''}},{nextView:'workbench'});return;}
    if(a==='instance-more'){ui.moreInstance=id;navigate('instance-more');return;}
    if(a==='instance-settings'){legacy('instance_settings',ui.moreInstance);return;}
    if(a==='recommendations'){legacy('recommendations',ui.moreInstance);return;}
    if(a==='comparison'||a==='comparison-from-more'){legacy('comparison',id||ui.moreInstance);return;}
    if(a==='pre-state'){legacy('pre_state');return;}
    if(a==='session-details'){legacy('session_details');return;}
    if(a==='progress'){begin('legacy',{view:'progress',catalog_id:id||null});return;}
    if(a==='management'){legacy('management');return;}
    if(a==='health-overview'){begin('workspace',{workspace:'导入与总览'});return;}
    if(a==='abort-training'){begin('abort_session',{session_id:sid(),base_revision:s.revision},{nextView:'detail'});return;}
    if(a.startsWith('timer-')){const action=a.slice(6);begin('timer',{session_id:sid(),base_revision:s.revision,action,target_seconds:action==='start'?(ui.restTarget||null):action==='extend'?(ui.restExtension||null):null});return;}
  });
  window.addEventListener('message',event=>{
    if(event.source!==window.parent||event.data?.type!=='streamlit:render')return;
    const args=event.data.args||{},next=args.snapshot||{};if(!next.db_scope)return;
    const first=!loaded||scope!==next.db_scope;snap=next;receipt=args.receipt||snap.receipt||null;clockOffset=snap.now?new Date(snap.now).getTime()-Date.now():0;
    if(first){scope=next.db_scope;loaded=true;ui=initialUI();pending=null;notice=null;catalogLoadedAt=0;load();if(!ui.session_id&&sid())ui.session_id=sid();}
    if(current()){activateSessionForms(current());for(const item of current().exercises||[])for(const row of item.sets||[])if(row.deleted_at)delete ui.drafts[identity(row)];if(current().deleted_at&&ui.view!=='home'){ui.view='detail';notice={kind:'error',text:'本场训练已删除。可在历史管理中撤销，本地输入不会覆盖删除状态。'};}}
    if(receipt)finishReceipt(receipt);
    if(!current()&&['workbench','detail','catalog','finish','history','advice','notes','rename','instance-more','workout-more','rest'].includes(ui.view)&&ui.session_id&&!pending){begin('session',{session_id:ui.session_id});return;}
    if(args.open_record && args.open_record!==ui.lastOpenedRecord && current()){
      ui.lastOpenedRecord=args.open_record;ui.session_id=sid();ui.legacyReturn=false;
      ui.view=activeSession(current())?'workbench':'detail';ui.scrollTo=null;
    }
    if(ui.legacyReturn){ui.legacyReturn=false;if(!['home','start'].includes(ui.view))ui.view=activeSession(current())?'workbench':'detail';}
    render();
  });
  window.addEventListener('resize',resize);
  window.addEventListener('beforeunload',persist);
  setInterval(()=>{
    const s=current();const sessionClock=app.querySelector('[data-clock="session"]');if(sessionClock&&s)sessionClock.textContent=elapsed(s.started_at,s.ended_at);
    const restClock=app.querySelector('[data-clock="rest"]');if(restClock)restClock.textContent=restTime(s?.rest_timer);
    if(ui.view==='catalog'&&!pending&&Date.now()-catalogLoadedAt>60000)queryCatalog(true);
    if(ui.view==='advice'&&['running','slow'].includes(snap.advice_job?.status)&&!pending)begin('advice_status');
    if(pending&&Date.now()-pending.started>10000&&!app.querySelector('[data-action="retry"]'))render();
  },1000);
  st('streamlit:componentReady',{apiVersion:1});
  if(globalThis.ResizeObserver)new ResizeObserver(resize).observe(app);
  resize();
})();
