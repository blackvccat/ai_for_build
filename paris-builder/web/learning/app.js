'use strict';
const $ = (s, root=document) => root.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = n => Number(n || 0).toLocaleString('en-US');
const labels = {overview:'学习总览',library:'分层知识库',sources:'源素材档案',studio:'设计研究台',audit:'验证与边界'};
const layerNames = {structure:'建筑结构',facade:'立面风格',technique:'建造技法',component:'实体构件'};
const layerNotes = {structure:'学习体量、院落与街道的空间关系',facade:'理解开间、楼层与立面构图的秩序',technique:'解释方块状态如何表达建筑细节',component:'检索可追溯的裁件与派生配方'};
const originNames = {source_crop:'源素材裁件',source_decomposition:'参考建筑实拆',derived_recipe:'派生配方',existing_rule:'既有设计归纳',style_research:'风格研究'};
const reviewNames = {unreviewed:'待复核',reference:'已选为参考',excluded:'已排除'};
const viewNames = {front:'正面',back:'背面',left:'左侧',right:'右侧',top:'顶部',axonometric_front:'前轴测',axonometric_back:'后轴测'};
const examples = ['克制的巴黎公寓，有精致的薄窗套','带前院和两侧翼楼的府邸','沿斜坡逐段下降的街屋','屋顶上排烟的烟囱'];
let state = {page:'overview', data:null, query:'', layer:'', source:'', quality:'', width:'', vanilla:false, offset:0};
let selectedId=null, requestVersion=0, toastTimer, lastFocus=null, lastBrief=null, activeRun=null;
let agentSession=localStorage.getItem('atelier-agent-session'), agentPlan=null, studioTab='chat';
let lastAutoOpenedRun=null, agentRefreshTimer=null, agentSending=false;
let designRequestVersion=0;
let pendingReferences=[];
const composerDrafts=new Map();
const taskStatusNames={idle:'待命',queued:'已排队',running:'执行中',stopping:'正在中断',interrupted:'已中断',done:'已完成',failed:'执行失败'};

function clearAgentReferences(){
  pendingReferences.forEach(item=>URL.revokeObjectURL(item.url));pendingReferences=[];
  if($('#agent-reference-files'))$('#agent-reference-files').value='';
  renderAgentReferences();
}
function renderAgentReferences(){
  const list=$('#agent-reference-list');if(!list)return;
  list.innerHTML=pendingReferences.map((item,i)=>`<span class="attachment-preview"><img src="${esc(item.url)}" alt="${esc(item.file.name)}"><span>${esc(item.file.name)}</span><button type="button" data-remove-reference="${i}" aria-label="移除图片：${esc(item.file.name)}" title="移除图片">×</button></span>`).join('');
  $('#agent-reference-note').hidden=!pendingReferences.length;
}
function addAgentReferences(files){
  if(agentSending){toast('本轮正在发送，请完成或中断后添加图片');return;}
  if(pendingReferences.length+files.length>2||files.some(file=>file.size>2000000||!['image/png','image/jpeg'].includes(file.type))){toast('最多添加 2 张 PNG/JPEG 参考图，每张不超过 2 MB');return;}
  pendingReferences.push(...files.map(file=>({file,url:URL.createObjectURL(file)})));renderAgentReferences();
}
async function changeAgentExecution(action){
  if(!agentSession)return;
  const session=agentSession;
  try{
    const result=await api('/api/agent/session/'+action,{id:session});
    await restoreAgentSession();
    if(action==='resume'&&result.job_id){
      await poll(result.job_id,()=>{});
      if(agentSession===session)await restoreAgentSession();
    }
  }catch(error){if(agentSession===session){await restoreAgentSession();toast(error.message);}}
}
let renderedAgentSignature='', typingFrame=null;
const typedReplies=new Map();
const initializedReplySessions=new Set();
const operationReceipts=new Map();
const operationNames={'agent.turn':'处理消息','dsh.intent':'理解需求','dsh.research':'来源研究','dsh.design':'设计规划','dsh.repair':'根据视觉缺陷修订','workflow.build':'生成建筑','workflow.review':'阶段评审','build.frameworks':'生成框架','build.facades':'生成立面','build.tier2':'二级细化','build.tier3':'三级细化','vision.frameworks':'框架视觉评审','vision.facades':'立面视觉评审','vision.tier2':'细化视觉评审','vision.tier3':'最终视觉评审'};
operationNames['generator.repair']='修复生成器源码';
operationNames['dsh.generator_repair']='源码诊断与补丁设计';
const operationStatuses={RUNNING:'执行中',SUCCEEDED:'已完成',FAILED:'失败',INTERRUPTED:'已中断'};
function facadeDecisionText(decision){
  if(typeof decision==='string')return decision;
  const techniques={rustication:'基座分缝',shopfront:'店面',window_surround:'窗套',guard_rail:'护栏',cornice:'檐口',pediment:'山花',chimney_cap:'烟囱压顶'};
  return [decision.placement,techniques[decision.technique]||decision.technique,decision.reason].filter(Boolean).join(' · ');
}
function animateAgentReplies(){
  cancelAnimationFrame(typingFrame);
  const tick=now=>{
    let pending=false;
    document.querySelectorAll('[data-typing-reply]').forEach(node=>{
      const entry=typedReplies.get(node.dataset.typingReply);if(!entry)return;
      const characters=Array.from(entry.text);
      if(entry.position<characters.length){if(!entry.lastTick||now-entry.lastTick>=40){entry.position=Math.min(characters.length,entry.position+2);entry.lastTick=now;}pending=true;}
      node.textContent=characters.slice(0,entry.position).join('');
      node.classList.toggle('typing-active',entry.position<characters.length);
    });
    if(pending)typingFrame=requestAnimationFrame(tick);
  };
  typingFrame=requestAnimationFrame(tick);
}
const formLabels={street_house:'单栋街屋',street_row:'连续街排',apartment_block:'公寓楼',court_palace:'庭院府邸',civic_hall:'公共建筑',slope_terrace:'坡地退台'};
const schemeLabels={haussmann_apartment:'奥斯曼公寓',palace_front:'府邸立面',civic_colonnade:'公共柱廊',plain_terrace:'简洁街屋',shop_terrace:'连续店面'};

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入');
  return data;
}
function fail(error, el=$('#global-error')) {el.textContent=error.message || String(error);el.hidden=false;}
function toast(message) {clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,4000);}
function asset(id,kind='image',view='') {return '/api/asset?'+new URLSearchParams({id,kind,...(view?{view}:{})});}
function art(layer) {
  const shapes={structure:'M8 43V18l18-10 18 10v25M26 8v35M8 18l18 10 18-10M49 43V26l14-8 14 8v17M63 18v25M49 26l14 8 14-8',facade:'M12 45V9h58v36M12 18h58M12 36h58M20 24h8v9h-8zM37 24h8v9h-8zM54 24h8v9h-8zM20 10v7M41 10v7M60 10v7M10 45h62',technique:'M8 40h67M14 37h55v-5H14zM18 31h47v-6H18zM23 24h37V13H23zM20 12h44V7H20zM32 13v11M50 13v11',component:'M22 43V14h38v29M18 44h46M18 10h46v4H18zM28 20h26v18H28zM41 20v18M28 29h26M25 39h32v4H25z'};
  return `<div class="line-art"><svg viewBox="0 0 84 52" aria-hidden="true"><path d="${shapes[layer] || shapes.component}"/></svg></div>`;
}
function heading(kicker,title,description,action='') {
  return `<div class="page-heading"><div><span class="eyebrow">${kicker}</span><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
}
function sourceThumb(r) {
  const source = state.data.sources.find(s=>r.sources.includes(s.id)&&s.image);
  return source ? `<img loading="lazy" src="${asset(source.id,'source')}" alt="来源建筑截图"><span class="card-tag">来源建筑 · 非裁件预览</span>` : `${art(r.layer)}${r.dimensions?`<span class="dimension-label">${r.dimensions.join(' × ')} 格 · 裁件待渲染</span>`:''}`;
}
function card(r) {
  return `<button class="knowledge-card" data-record="${esc(r.id)}"><div class="card-visual">${r.image?`<img loading="lazy" src="${asset(r.id)}" alt="${esc(r.title)}"><span class="card-tag">${esc(layerNames[r.layer])}</span>`:sourceThumb(r)}</div><div class="card-body"><h3>${esc(r.title)}</h3><p>${esc(r.summary)}</p><div class="card-footer"><span>${esc(originNames[r.origin])}</span><span class="status-tag ${esc(r.review.status)}">${reviewNames[r.review.status]}</span></div></div></button>`;
}
function overview() {
  const m=state.data.manifest, a=m.audit;
  const hero=state.data.sources.find(s=>s.name==='巴黎建筑素材2' && s.image)||state.data.sources.find(s=>s.image);
  $('#content').innerHTML=heading('THE ARCHITECTURAL LEARNING ATELIER','从优秀建筑中学习，让创新有据可循。','从源素材到建筑知识，再到有依据的原创设计。每一层都能查看、检索与追溯。',`<div class="date-note">巴黎 · 十九世纪末至二十世纪初<span>KNOWLEDGE BEFORE GENERATION</span></div>`)+
    `<section class="hero"><div class="hero-photo"><img src="${asset(hero.id,'source')}" alt="${esc(hero.name)} 原始参考截图"><span class="photo-top">SOURCE ARCHIVE / 源建筑参考</span><div class="photo-bottom"><span>LEARNING FROM THE ORIGINAL</span><h3>${esc(hero.name)} <small>用户提供的源作品</small></h3></div></div><div class="hero-copy"><span class="eyebrow">从一个模糊的想法开始</span><h2>理解它为什么成立，<br>再探索它还能怎样。</h2><p>把结构、立面与建造技法分层组织。用自然语言寻找建筑依据，保留每一次推断的来源与边界。</p><button class="primary" data-go="studio">进入设计研究台 <span>↗</span></button></div></section>
    <section class="stats"><div class="stat"><span class="stat-label">建筑参考样本</span><strong>14<small>组</small></strong><span class="hint">图片与 .schem 对应</span></div><div class="stat"><span class="stat-label">已索引知识</span><strong>${number(m.count)}<small>条</small></strong><span class="hint">四层知识 · 本地语义向量</span></div><div class="stat"><span class="stat-label">新增源裁件</span><strong>${number(a.detail_count)}<small>件</small></strong><span class="hint">逐件回读与来源核对</span></div><div class="stat"><span class="stat-label">你选定的参考</span><strong>${number(state.data.reviewed)}<small>条</small></strong><span class="hint">数量不等于已理解的技法</span></div></section>
    <div class="section-heading"><h2>四层知识，相互关联<small>THE KNOWLEDGE LAYERS</small></h2><button class="subtle" data-go="library">浏览全部 →</button></div><div class="layer-grid">${Object.keys(layerNames).map((k,i)=>`<button class="layer-card" data-layer-go="${k}" style="text-align:left;color:inherit">${art(k)}<div class="layer-title"><span>0${i+1} / ${layerNames[k]}</span><b>${m.layers[k]} 条 ↗</b></div><p>${layerNotes[k]}</p></button>`).join('')}</div>
    <div class="learning-strip"><span>◎</span><p><strong>当前学习阶段：证据入库与检索验证。</strong> ${number(a.detail_count)} 件裁件已接入检索；建筑角色、优秀程度与适用场景仍需复核。这里会清楚标注源事实、既有归纳和 AI 推断，游戏验收保持待完成。</p></div>`;
}
function library() {
  $('#content').innerHTML=heading('LAYERED KNOWLEDGE','分层知识库','描述你想要的效果，找到相关构件与规则，再打开来源检查它是否适用。')+
    `<form class="search-bar" id="search-form"><span class="search-icon">⌕</span><input id="search-input" aria-label="描述建筑意图" placeholder="例如：侧街使用的克制薄窗套，保留巴黎建筑的层次感" value="${esc(state.query)}"><button class="primary">检索知识 →</button></form><div class="chips">${examples.map(x=>`<button class="chip" data-query="${esc(x)}">${esc(x)}</button>`).join('')}</div>
    <div class="tabs"><button class="tab ${!state.layer?'active':''}" data-layer="">全部知识</button>${Object.keys(layerNames).map(k=>`<button class="tab ${state.layer===k?'active':''}" data-layer="${k}">${layerNames[k]} <span class="muted">${state.data.manifest.layers[k]}</span></button>`).join('')}</div>
    <div class="filters"><select id="source-filter" aria-label="来源过滤"><option value="">全部素材来源</option>${state.data.sources.filter(s=>s.count).map(s=>`<option value="${s.id}" ${state.source===s.id?'selected':''}>${esc(s.name)} · ${s.group.startsWith('补充')?'补充':'原始'}</option>`).join('')}</select><select id="quality-filter" aria-label="参考状态"><option value="">全部可检索候选</option>${Object.keys(reviewNames).map(k=>`<option value="${k}" ${state.quality===k?'selected':''}>${reviewNames[k]}</option>`).join('')}</select><label>最大面宽 <input id="width-filter" type="number" min="1" max="500" value="${esc(state.width)}" placeholder="不限"></label><label><input id="vanilla-filter" type="checkbox" ${state.vanilla?'checked':''}>仅原版方块构件</label><span class="result-count" id="result-count">载入中…</span></div>
    <div id="search-results" class="result-grid"></div><div id="pager" class="pager"></div>`;
  $('#search-form').onsubmit=e=>{e.preventDefault();state.query=$('#search-input').value.trim();state.offset=0;loadResults();};
  ['source','quality','width','vanilla'].forEach(k=>$('#'+k+'-filter').onchange=e=>{state[k]=k==='vanilla'?e.target.checked:e.target.value;state.offset=0;loadResults();});
  loadResults();
}
async function loadResults() {
  const version=++requestVersion;
  const params=new URLSearchParams({q:state.query,layer:state.layer,source:state.source,quality:state.quality,vanilla:state.vanilla,offset:state.offset});
  if(state.width) params.set('max_width',state.width);
  $('#search-results').innerHTML='<div class="loading">正在检索本地知识…</div>';
  try {
    const r=await api('/api/search?'+params);
    if(version!==requestVersion||state.page!=='library')return;
    $('#result-count').textContent=`${number(r.total)} 条候选${state.query?' · 语义排序':''}`;
    $('#search-results').innerHTML=r.items.map(card).join('')||'<div class="empty">没有符合条件的知识。<br>尝试缩短描述、放宽宽度，或切换知识层。</div>';
    $('#pager').innerHTML=`<button class="secondary" data-page-step="-1" ${state.offset===0?'disabled':''}>← 上一页</button><span>${r.total?Math.floor(state.offset/24)+1:0} / ${Math.ceil(r.total/24)}</span><button class="secondary" data-page-step="1" ${state.offset+24>=r.total?'disabled':''}>下一页 →</button>`;
  } catch(e) {if(version===requestVersion){$('#search-results').innerHTML=`<div class="error inline-error">${esc(e.message)}</div>`;$('#result-count').textContent='检索失败';}}
}
function sources() {
  const originals=state.data.sources.filter(s=>s.group==='14 组建筑参考'&&s.image);
  $('#content').innerHTML=heading('SOURCE ARCHIVE','源素材档案','从完整建筑回到局部构件。原始文件保留，知识解释始终与来源关联。')+
    `<div class="source-grid">${originals.map(s=>`<article class="source-card"><img loading="lazy" src="${asset(s.id,'source')}" alt="${esc(s.name)} 源截图"><div class="source-body"><h3>${esc(s.name)}</h3><div class="source-meta"><span>${s.measurements?`${s.measurements.dimensions.width} × ${s.measurements.dimensions.height} × ${s.measurements.dimensions.length} 格`:''}</span><span>${s.count} 条关联知识</span></div><button class="subtle" data-source-go="${s.id}">查看来源关联 →</button><details><summary>文件与来源哈希</summary><div class="evidence-block">${esc(s.path)}<code>SHA-256 ${s.sha256}</code></div></details></div></article>`).join('')}</div>
    <div class="learning-strip"><span>◎</span><p>部分补充文件与原作品同名，但内容不同。知识库按路径与哈希区分；“补充素材”裁件不会仅因同名而被归到这 14 组原始作品中。全部来源可在知识库筛选栏查看。</p></div>`;
}
function studio() {
  renderedAgentSignature='';
  $('#content').innerHTML=`<div class="studio-shell"><aside class="studio-rail"><div class="studio-brand">ATELIER <small>PARIS / 建筑 Agent</small></div><button class="studio-mobile-link" data-go="library" type="button">知识库</button><button class="studio-mobile-link" data-open-provider="1" type="button">模型</button><button class="studio-new" id="agent-new" type="button">＋ 新对话</button><div class="studio-rail-label">会话</div><div id="agent-sessions" class="studio-sessions"></div><div id="session-notice" role="status"></div><div class="studio-rail-bottom"><button data-go="overview">学习总览</button><button data-go="library">知识库</button><button data-go="sources">源素材</button><button data-open-provider="1">模型连接</button></div></aside><section class="studio-main"><header class="studio-header"><div><strong>建筑设计 Agent</strong><span id="studio-session-label">新对话</span></div><select id="agent-session-select" aria-label="切换会话"></select><button type="button" data-delete-current="1" title="删除当前会话，建筑文件保留">删除会话</button><nav class="studio-tabs" aria-label="工作视图"><button type="button" data-studio-tab="chat">对话</button><button type="button" data-studio-tab="trace">轨迹</button><button type="button" data-studio-tab="preview">预览</button></nav></header><div id="studio-view-chat" class="studio-view"><div id="agent-timeline" class="agent-timeline" role="log" aria-live="polite"></div><form id="agent-form" class="agent-composer"><textarea id="agent-input" aria-label="发给建筑 Agent 的消息" placeholder="描述你的建筑需求，或继续提出修改…" required minlength="2"></textarea><section class="agent-attachments"><label for="agent-reference-files">添加参考图</label><input id="agent-reference-files" type="file" accept="image/png,image/jpeg" multiple aria-label="添加现实建筑参考图"><span id="agent-reference-list"></span><input id="agent-reference-note" type="text" maxlength="500" placeholder="说明参考图中希望借鉴的部分" aria-label="参考图说明" hidden></section><div><span id="agent-status" role="status"></span><button class="primary" type="submit" title="发送消息">↑</button></div></form></div><div id="studio-view-trace" class="studio-view" hidden><div class="studio-view-inner"><h2>执行轨迹</h2><div id="agent-trace"></div></div></div><div id="studio-view-preview" class="studio-view" hidden><div class="studio-view-inner"><div id="design-workspace"></div><div id="design-history"></div><details class="manual-research"><summary>手动检索与研究</summary><section class="panel"><h2>研究需求</h2><textarea id="brief-input" aria-label="设计需求" placeholder="描述建筑想法">${esc(lastBrief?.request||'想做一栋巴黎公寓，底层有咖啡店，屋顶有烟囱。')}</textarea><div class="actions"><button class="secondary" id="brief-local">检索依据</button><button class="secondary" id="brief-model">DeepSeek 研究方案</button></div><div id="brief-status" role="status"></div></section><div id="brief-results"></div></details></div></div></section></div>`;
  $('#brief-local').onclick=()=>runBrief(false);$('#brief-model').onclick=()=>runBrief(true);
  $('#agent-form').onsubmit=sendAgentTurn;
  $('#agent-reference-files').onchange=e=>{addAgentReferences([...e.target.files]);e.target.value='';};
  const composer=$('#agent-form');
  composer.insertAdjacentHTML('beforeend','<div class="agent-execution"><span id="agent-task-state" role="status"></span><button type="button" id="agent-interrupt" aria-label="中断任务" title="中断任务" hidden>■</button><button type="button" id="agent-resume" aria-label="继续任务" title="继续任务" hidden>▶</button></div>');
  $('#agent-interrupt').onclick=()=>changeAgentExecution('interrupt');
  $('#agent-resume').onclick=()=>changeAgentExecution('resume');
  $('#agent-input').removeAttribute('required');$('#agent-input').removeAttribute('minlength');
  $('#agent-input').oninput=()=>resizeComposer();
  $('#agent-input').value=composerDrafts.get(agentSession||'new')||'';resizeComposer();
  $('#agent-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault();if(!$('#agent-form button[type=submit]').disabled)composer.requestSubmit();}};
  composer.ondragover=e=>{if([...e.dataTransfer.types].includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';composer.classList.add('drag-over');}};
  composer.ondragleave=e=>{if(!composer.contains(e.relatedTarget))composer.classList.remove('drag-over');};
  composer.ondrop=e=>{e.preventDefault();composer.classList.remove('drag-over');addAgentReferences([...e.dataTransfer.files]);};
  $('#agent-input').onpaste=e=>{const files=[...e.clipboardData.files];if(files.length){e.preventDefault();addAgentReferences(files);}};
  renderAgentReferences();
  $('#agent-session-select').onchange=e=>{if(e.target.value)selectAgentSession(e.target.value);};
  $('#agent-new').onclick=()=>selectAgentSession(null);
  if(lastBrief) showBrief(lastBrief);
  renderAgentEvents([]);
  setStudioTab(studioTab);
  loadDesignHistory();
  loadAgentSessions();
  restoreAgentSession();
  clearInterval(agentRefreshTimer);
  agentRefreshTimer=setInterval(()=>{if(state.page==='studio'&&agentSession)restoreAgentSession();},4000);
}
function setStudioTab(tab,{refresh=true}={}){
  const changed=studioTab!==tab;
  studioTab=tab;
  for(const name of ['chat','trace','preview'])$('#studio-view-'+name).hidden=name!==tab;
  document.querySelectorAll('[data-studio-tab]').forEach(button=>button.classList.toggle('active',button.dataset.studioTab===tab));
  if(refresh&&changed&&tab==='preview'&&(activeRun||lastAutoOpenedRun))openDesignRun(activeRun||lastAutoOpenedRun);
}
function selectAgentSession(session){
  composerDrafts.set(agentSession||'new',$('#agent-input').value);
  agentEventSource?.close();
  designRequestVersion++;
  clearTimeout(workflowRefreshTimer);
  agentSession=session;agentPlan=null;activeRun=null;lastAutoOpenedRun=null;lastBrief=null;
  if(session)localStorage.setItem('atelier-agent-session',session);else localStorage.removeItem('atelier-agent-session');
  clearAgentReferences();$('#agent-input').value=composerDrafts.get(session||'new')||'';$('#agent-reference-note').value='';resizeComposer();
  $('#design-workspace').innerHTML='';$('#brief-results').innerHTML='';
  renderAgentEvents([]);$('#agent-status').textContent='';
  $('#agent-task-state').textContent=taskStatusNames.idle;
  $('#agent-form button[type=submit]').disabled=agentSending;
  $('#agent-interrupt').hidden=true;$('#agent-resume').hidden=true;
  setStudioTab('chat');loadAgentSessions();if(session)restoreAgentSession();
}
function resizeComposer(){
  const input=$('#agent-input');if(!input)return;
  input.style.height='auto';input.style.height=Math.min(180,Math.max(64,input.scrollHeight))+'px';
}
async function loadAgentSessions(){
  try{const rows=(await api('/api/agent/sessions')).items;if(state.page!=='studio')return;
    $('#agent-sessions').innerHTML=rows.map(row=>`<div class="studio-session-row"><button type="button" class="studio-session ${row.id===agentSession?'active':''}" data-agent-session="${esc(row.id)}"><span>${esc(row.title)}</span><small>${row.event_count} 条记录</small></button><button type="button" class="session-delete" data-delete-session="${esc(row.id)}" aria-label="删除会话：${esc(row.title)}" title="删除会话">×</button></div>`).join('')||'<p>暂无会话</p>';
    $('#agent-session-select').innerHTML='<option value="">切换会话</option>'+rows.map(row=>`<option value="${esc(row.id)}" ${row.id===agentSession?'selected':''}>${esc(row.title)}</option>`).join('');
  }catch(error){if(state.page==='studio')$('#agent-sessions').textContent=error.message;}
}
async function deleteAgentSession(id) {
  if(!id){toast('当前没有可删除的会话');return;}
  try {
    await api('/api/agent/session/delete',{id});
    if(agentSession===id)selectAgentSession(null);
    $('#session-notice').innerHTML=`会话已删除，建筑文件保留。<button type="button" data-undo-session="${esc(id)}">撤销删除</button>`;
    await loadAgentSessions();
  }catch(error){toast(error.message);}
}
async function undoAgentSession(id) {
  try{await api('/api/agent/session/restore',{id});selectAgentSession(id);$('#session-notice').textContent='会话已恢复';}
  catch(error){toast(error.message);}
}
async function restoreAgentSession() {
  if(!agentSession)return;
  const session=agentSession;
  connectAgentEvents(session);
  try {const data=await api('/api/agent/session?'+new URLSearchParams({id:session}));if(state.page==='studio'&&agentSession===session){
    renderAgentEvents(data.events);
    $('#agent-form button[type=submit]').disabled=data.active||agentSending;
    const task=data.task||{status:data.active?'running':'idle'};
    $('#agent-task-state').textContent=taskStatusNames[task.status]||task.status;
    $('#agent-interrupt').hidden=!['queued','running','stopping'].includes(task.status);
    $('#agent-interrupt').disabled=task.status==='stopping';
    $('#agent-resume').hidden=!(task.status==='interrupted'||task.status==='failed'&&task.kind==='workflow.build'&&task.run);
    $('#agent-resume').title=task.status==='failed'?'重试当前建筑任务':'继续任务';
    $('#agent-resume').disabled=data.active;
    const latest=[...data.events].reverse().find(e=>['tool_result','tool_started','workflow_stage','workflow_created'].includes(e.kind));
    $('#agent-status').textContent=data.active?'Agent 正在处理…':data.events.at(-1)?.kind==='agent_error'?data.events.at(-1).message:latest?.kind==='tool_started'?'正在构建并渲染七视角…':latest?.status==='FAIL'?'构建失败，查看轨迹或继续提出修改。':'';
    if((latest?.kind==='workflow_stage'||latest?.kind==='workflow_created'||latest?.kind==='tool_result'&&['PASS','NEEDS_REVISION'].includes(latest.status))&&latest.run&&lastAutoOpenedRun!==latest.run){
      lastAutoOpenedRun=latest.run;
      await loadDesignHistory();
      if(agentSession===session&&studioTab==='preview')openDesignRun(latest.run,{activate:false});
    }
    loadAgentSessions();
  }}
  catch(error){if(state.page==='studio'&&agentSession===session)$('#agent-status').textContent=error.message;}
}
function renderAgentEvents(events) {
  const signature=JSON.stringify([agentSession,events]);
  if(signature===renderedAgentSignature)return;
  renderedAgentSignature=signature;
  const timeline=$('#agent-timeline'), oldScroll=timeline.scrollTop, nearBottom=timeline.scrollHeight-timeline.clientHeight-oldScroll<80;
  const expanded=new Set([...timeline.querySelectorAll('[data-atomic][open]')].map(node=>node.dataset.atomic));
  agentPlan=[...events].reverse().find(e=>e.kind==='plan')||null;
  const first=events.find(e=>e.kind==='user');
  $('#studio-session-label').textContent=first?first.text.slice(0,48):'新对话';
  const latestWorkflow=[...events].reverse().find(e=>['workflow_stage','workflow_created','tool_started'].includes(e.kind));
  const operations=new Map();events.filter(e=>e.kind==='operation').forEach(e=>operations.set(e.id,e));
  const latestProgress=[...events].reverse().find(e=>e.kind==='agent_progress');
  const latestFailure=[...events].reverse().find(e=>e.kind==='tool_result'&&e.status==='FAIL');
  const firstRender=!initializedReplySessions.has(agentSession);
  if(events.length)initializedReplySessions.add(agentSession);
  timeline.dataset.session=agentSession||'';
  $('#agent-timeline').innerHTML=events.filter(e=>(e.kind!=='operation'||e===operations.get(e.id))
    &&(e.kind!=='agent_progress'||e===latestProgress&&events.indexOf(e)>events.indexOf(latestFailure))
    &&(e.kind!=='tool_result'||e.status!=='FAIL'||e===latestFailure)
    &&(!['workflow_stage','workflow_created','tool_started'].includes(e.kind)||e===latestWorkflow&&events.indexOf(e)>events.indexOf(latestFailure))).map(e=>{
    if(e.kind==='operation')return `<details class="atomic-step" data-atomic="${esc(e.id)}" data-operation-status="${esc(e.status)}"><summary><span>${esc(operationNames[e.operation_type]||e.operation_type||'执行步骤')} ${esc(e.inputs?.candidate||'')}${e.inputs?.revision!=null?' · 修订 '+esc(e.inputs.revision):''}</span><small class="atomic-${esc(e.status)}">${esc(operationStatuses[e.status]||e.status)}</small></summary><div class="atomic-content"><p>${esc(e.error||'正在读取步骤记录…')}</p></div></details>`;
    if(e.kind==='user')return `<div class="agent-event user"><span>你</span>${e.text.length>400?`<details><summary>${esc(e.text.slice(0,110))}… 展开任务书</summary><p>${esc(e.text)}</p></details>`:`<p>${esc(e.text)}</p>`}</div>`;
    if(e.kind==='reference')return `<div class="agent-event tool"><span>操作者参考图</span><a class="agent-reference" href="${esc(e.url)}" target="_blank" rel="noopener"><img src="${esc(e.url)}" alt="${esc(e.name)}"><span>${esc(e.name)}${e.note?' · '+esc(e.note):''}</span></a></div>`;
    if(e.kind==='reference_analysis')return `<div class="agent-event tool"><span>参考图观察</span>${e.observations.map(text=>`<p>${esc(text)}</p>`).join('')}</div>`;
    if(e.kind==='assistant'){
      const key=agentSession+':'+e.at+':'+events.indexOf(e);
      if(!typedReplies.has(key))typedReplies.set(key,{text:e.text,position:firstRender||window.matchMedia('(prefers-reduced-motion: reduce)').matches?Array.from(e.text).length:0});
      const entry=typedReplies.get(key);
      return `<div class="agent-event"><span>建筑设计 Agent</span><p data-typing-reply="${esc(key)}">${esc(Array.from(entry.text).slice(0,entry.position).join(''))}</p></div>`;
    }
    if(e.kind==='agent_started')return `<div class="agent-event tool"><span>意图判断</span><p>${esc(e.summary)}</p></div>`;
    if(e.kind==='agent_error')return `<div class="agent-event tool"><span>该次尝试未完成</span><p>${esc(e.message)}</p>${e===events[events.length-1]?'<button type="button" class="secondary" data-retry-agent="1">重试此任务</button>':''}</div>`;
    if(e.kind==='agent_progress')return `<div class="agent-event tool"><span>Agent 进度</span><p>${esc(e.summary)}</p></div>`;
    if(e.kind==='task_state')return `<div class="agent-event tool"><span>${esc(taskStatusNames[e.status]||e.status)}</span><p>${esc(e.summary||'')}</p></div>`;
    if(e.kind==='workflow_created'||e.kind==='workflow_stage')return `<div class="agent-event tool"><span>${esc(stageLabels[e.stage]||e.stage)}</span><p>${esc(e.stage==='game'?'建筑已打包，可查看预览与下载。游戏验收待完成。':e.summary)}</p><button class="secondary" data-design-run="${esc(e.run)}">查看结果</button></div>`;
    if(e.kind==='research_result')return `<div class="agent-event"><span>DSH 研究 · 已保存的现实资料</span><p>${esc(e.summary||'已检索建筑资料')}</p><div class="agent-sources">${(e.sources||[]).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.publisher||s.title)}</a>`).join('')}</div>${e.images?.length?`<div class="agent-images">${e.images.map(item=>`<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer"><img loading="lazy" src="${esc(item.thumbnail||item.url)}" alt="${esc(item.title||item.name)}"><span>${esc(item.title||item.name)}</span></a>`).join('')}</div><p class="hint">参考图片尚未由视觉模型判读。</p>`:''}</div>`;
    if(e.kind==='plan')return `<div class="agent-event"><span>Agent 设计方案 · DeepSeek Harness</span><p>${esc(e.summary)}</p>${e.tools?.length?`<p class="hint">已调用：${e.tools.map(esc).join('、')}</p>`:''}<ol>${e.steps.map(step=>`<li>${esc(step)}</li>`).join('')}</ol><h3>立面决策</h3><ul>${(e.facade_decisions||[]).map(d=>`<li>${esc(facadeDecisionText(d))}</li>`).join('')}</ul><div class="agent-evidence">${e.evidence_ids.slice(0,6).map(id=>`<button data-record="${esc(id)}">${esc(id)}</button>`).join('')}</div></div>`;
    if(e.kind==='tool_started')return `<div class="agent-event tool"><span>工具执行 · ${esc(e.tool)}</span><p>${esc(e.run)} 已开始构建。</p></div>`;
    if(e.kind==='tool_result')return `<div class="agent-event tool"><span>验证结果 · ${esc(e.status)}</span><p>${esc(e.run)} ${e.status==='PASS'?'文件和几何已验证，七视角可查看；游戏验收待完成。':esc(e.message)}</p>${e.run?`<button class="secondary" data-design-run="${esc(e.run)}">打开版本</button>`:''}</div>`;
    if(e.kind==='visual_review')return `<div class="agent-event tool"><span>视觉评审 · ${e.verdict==='revise'?'需要修改':'仅预览认可'}</span><p>${esc(e.note)}</p><button class="secondary" data-design-run="${esc(e.run)}">查看版本</button></div>`;
    return '';
  }).join('')||'<div class="studio-welcome"><span>ATELIER / PARIS</span><h2>你想建造什么？</h2><p>描述地块、用途和想要的街景，Agent 会先查证据并给出可执行的建筑方案。</p></div>';
  timeline.scrollTop=nearBottom?timeline.scrollHeight:oldScroll;
  timeline.querySelectorAll('[data-atomic]').forEach(panel=>{
    if(expanded.has(panel.dataset.atomic))panel.open=true;
    const receipt=operationReceipts.get(panel.dataset.atomic);
    if(receipt&&typeof renderOperationContent==='function')renderOperationContent(panel,receipt);
  });
  animateAgentReplies();
  $('#agent-trace').innerHTML=events.filter(e=>e.kind!=='user').map(e=>`<div class="trace-row"><time>${esc(e.at||'')}</time><strong>${esc({agent_started:'意图判断',assistant:'Agent 回复',agent_error:'执行停止',research_result:'来源研究',plan:'设计规划',tool_started:'构建开始',tool_result:'工具结果',visual_review:'视觉评审'}[e.kind]||e.kind)}</strong><p>${esc(e.summary||e.text||e.note||e.message||e.run||e.operation_type||'')} ${esc(e.status||'')}</p>${e.kind==='operation'?`<button class="secondary" data-operation="${esc(e.id)}">查看输入、工具与收据</button>`:''}</div>`).join('')||'<p class="hint">尚无执行事件。</p>';
}
async function sendAgentTurn(e) {
  e.preventDefault();const files=pendingReferences.map(item=>item.file);
  const text=$('#agent-input').value.trim()||(files.length?'请分析这张建筑参考图。':'');if(text.length<2||agentSending)return;
  agentSending=true;
  const sentSession=agentSession;
  let resultSession=sentSession;
  const button=$('button[type=submit]',e.currentTarget),status=$('#agent-status');button.disabled=true;status.textContent='正在检索与规划…';
  try {
    if(files.length>2||files.some(file=>file.size>2000000||!['image/png','image/jpeg'].includes(file.type)))throw Error('最多添加 2 张 PNG/JPEG 参考图，每张不超过 2 MB');
    const references=await Promise.all(files.map(file=>new Promise((resolve,reject)=>{
      const reader=new FileReader();reader.onload=()=>resolve({name:file.name,note:$('#agent-reference-note').value.trim(),data:String(reader.result).split(',')[1]});reader.onerror=()=>reject(Error('参考图读取失败'));reader.readAsDataURL(file);
    })));
    let result=await api('/api/agent/turn',{session:sentSession,text,references});
    if(state.page!=='studio'||agentSession!==sentSession)return;
    agentSession=result.session;resultSession=result.session;localStorage.setItem('atelier-agent-session',agentSession);
    connectAgentEvents(agentSession);
    await restoreAgentSession();
    if(result.job_id)result=await poll(result.job_id,message=>{status.textContent=message;});
    if(state.page!=='studio'||agentSession!==result.session)return;
    if(!result.error&&$('#agent-input').value.trim()===text){$('#agent-input').value='';composerDrafts.delete(agentSession||'new');resizeComposer();}status.textContent=result.build?'方案已提交，正在自动构建…':result.error||'';
    if(!result.error){clearAgentReferences();$('#agent-reference-note').value='';}
    lastAutoOpenedRun=null;
    await restoreAgentSession();
    await loadAgentSessions();
    if(result.plan&&!result.build){lastBrief={request:text,design:result.plan.design,selections:{}};showDesignEditor(lastBrief);}
  }catch(error){if(state.page==='studio'&&(agentSession===sentSession||agentSession===resultSession))status.textContent=error.message;}finally{agentSending=false;if(state.page==='studio'){if(agentSession)await restoreAgentSession();else $('#agent-form button[type=submit]').disabled=false;}}
}
async function poll(id,onStatus) {
  for(let i=0;i<1500;i++) {
    const job=await api('/api/job/'+id);
    if(job.status==='done')return job.result;
    if(job.status==='failed'||job.status==='interrupted')throw Error(job.error);
    if(onStatus)onStatus(job.status==='stopping'?'正在中断…':job.status==='queued'?'任务已排队…':'正在处理，结果会保留来源与调用记录…');
    await new Promise(resolve=>setTimeout(resolve,1200));
  }
  throw Error('等待超时；任务可能仍在执行，请稍后查看');
}
async function runBrief(useModel) {
  agentPlan=null;
  $('.manual-research').open=true;
  const text=$('#brief-input').value.trim();if(text.length<2){toast('请先描述你的建筑想法');return;}
  const status=$('#brief-status');status.className='hint';status.textContent='正在分层检索…';
  $('#brief-local').disabled=$('#brief-model').disabled=true;
  try {
    let result=await api('/api/brief',{text,use_model:useModel});
    if(result.job_id)result=await poll(result.job_id,message=>status.textContent=message);
    lastBrief=result;
    if(state.page==='studio'){showBrief(result);status.textContent=result.model_error||'已完成。点击候选可检查来源与约束。';status.className=result.model_error?'error inline-error':'hint';}
    await refreshOverview();
  } catch(e) {status.textContent=e.message;status.className='error inline-error';}
  finally {if(state.page==='studio'){$('#brief-local').disabled=$('#brief-model').disabled=false;}}
}
function proposalHtml(data) {
  const p=data.proposal||{};
  return `<div class="flex"><span class="status-tag">AI 推断 · 待复核</span><span class="hint">文本证据输入，未看图</span></div><p>${esc(p.summary||'')}</p>${[['directions','可探索的原创方向'],['possible_uses','可能的用途'],['constraints','使用约束'],['unknowns','尚不确定的条件'],['next_steps','建议验证步骤']].map(([key,label])=>Array.isArray(p[key])?`<h3>${label}</h3><ul class="audit-list">${p[key].map(x=>`<li>${esc(typeof x==='object'?JSON.stringify(x):x)}</li>`).join('')}</ul>`:'').join('')}<h3>引用的知识</h3><div class="evidence-list">${(p.evidence_ids||[]).map(id=>`<button class="evidence-item" data-record="${esc(id)}"><span>${esc(id)}</span><span>查看 →</span></button>`).join('')}</div>${data.receipt?`<p class="hint">真实调用：${esc(data.receipt.model)} · ${number(data.receipt.usage?.total_tokens)} tokens · ${data.receipt.elapsed_seconds}s</p>`:''}`;
}
function showBrief(data) {
  $('#brief-results').innerHTML=(data.proposal?`<section class="panel"><h2>设计研究建议</h2>${proposalHtml(data)}</section>`:'')+
    `<div class="section-heading"><h2>四层检索依据<small>RETRIEVED EVIDENCE</small></h2></div><div class="audit-grid">${Object.entries(data.selections).map(([layer,rows])=>`<section class="panel"><h2>${layerNames[layer]}</h2><div class="evidence-list">${rows.map(r=>`<button class="evidence-item" data-record="${esc(r.id)}"><span>${esc(r.title)}</span><span>相关度 ${r.scores.semantic.toFixed(2)} →</span></button>`).join('')}</div></section>`).join('')}</div><p class="hint">相关度表示向量接近程度，不是美学分数，也不证明这个构件适合直接安装。</p>`;
  showDesignEditor(data);
}
function showDesignEditor(data) {
  const d=data.design||{};
  const select=(id,options,value)=>`<select id="${id}">${Object.entries(options).map(([key,label])=>`<option value="${key}" ${key===value?'selected':''}>${label}</option>`).join('')}</select>`;
  $('#design-workspace').innerHTML=`<section class="design-section"><div class="section-heading"><h2>建筑方案<small>BUILDABLE PLAN</small></h2></div><p class="hint">${esc(d.source||'待检查的建筑方案')}。修改后生成新版本；每个版本保留输入、来源和校验报告。</p><form id="design-form" class="design-form"><label>建筑结构${select('design-form-type',formLabels,d.form)}</label><label>立面方案${select('design-scheme',schemeLabels,d.facade)}</label><label>面宽（格）<input id="design-width" type="number" min="8" max="64" required value="${esc(d.width||22)}"></label><label>进深（格）<input id="design-depth" type="number" min="12" max="48" required value="${esc(d.depth||26)}"></label><label>层数<input id="design-storeys" type="number" min="3" max="8" required value="${esc(d.storeys||6)}"></label><label>种子<input id="design-seed" type="number" min="1" max="999999999" required value="${esc(d.seed||1900)}"></label><div class="design-submit"><button class="primary" type="submit">生成建筑与七视角预览</button><span id="design-status" role="status" class="hint"></span></div></form><div id="design-result"></div></section>`;
  $('#design-form').onsubmit=buildFromStudio;
}
async function buildFromStudio(e) {
  e.preventDefault();
  const form=e.currentTarget, button=$('button[type=submit]',form), status=$('#design-status');
  const evidence_ids=agentPlan?.evidence_ids||[...new Set(Object.values(lastBrief.selections).flat().map(r=>r.id))];
  const body={request:lastBrief.request,form:$('#design-form-type').value,scheme:$('#design-scheme').value,
    width:Number($('#design-width').value),depth:Number($('#design-depth').value),storeys:Number($('#design-storeys').value),
    seed:Number($('#design-seed').value),evidence_ids,session:agentPlan?agentSession:null};
  button.disabled=true;status.textContent='正在提交构建任务…';
  try {
    const queued=await api('/api/design/build',body);activeRun=queued.run;
    status.textContent=`${queued.run} 正在构建。可切换页面，返回后从历史版本打开。`;
    await loadDesignHistory();
    const result=await poll(queued.job_id,()=>{if(state.page==='studio'&&activeRun===queued.run)status.textContent=`${queued.run} 正在构建并渲染…`;});
    if(state.page==='studio'&&activeRun===queued.run){status.textContent='构建完成；请逐视角检查。';await openDesignRun(result.run,{activate:false});}
    if(agentPlan)await restoreAgentSession();
    await loadDesignHistory();
  } catch(error) {if(state.page==='studio')status.textContent=error.message;}
  finally {if(state.page==='studio')button.disabled=false;}
}
async function loadDesignHistory() {
  try {
    const rows=(await api('/api/design/runs')).items;
    if(state.page!=='studio')return;
    $('#design-history').innerHTML=`<div class="section-heading"><h2>设计版本<small>RECENT BUILDS</small></h2></div>${rows.length?`<div class="design-runs">${rows.map(r=>`<button class="design-run" data-design-run="${esc(r.run)}"><strong>${esc(r.run)}</strong><span>${esc(formLabels[r.intent.form]||r.intent.form)} · ${esc(r.intent.width)} × ${esc(r.intent.depth)} · ${esc(r.status)}</span></button>`).join('')}</div>`:'<p class="hint">尚无生成版本。</p>'}`;
  } catch(error) {if(state.page==='studio')$('#design-history').textContent=error.message;}
}
async function openDesignRun(name,{activate=false}={}) {
  if(!activate&&(state.page!=='studio'||studioTab!=='preview'))return;
  const session=agentSession, request=++designRequestVersion;
  activeRun=name;
  if(activate)setStudioTab('preview',{refresh:false});
  try {
    const data=await api('/api/design/run?'+new URLSearchParams({name}));
    if(state.page!=='studio'||studioTab!=='preview'||activeRun!==name||agentSession!==session||request!==designRequestVersion)return;
    if(!$('#design-workspace').querySelector('#design-result')){
      $('#design-workspace').innerHTML='<section class="design-section"><div id="design-result"></div></section>';
    }
    if(data.workflow){renderFormalWorkflow(name,data.workflow);return;}
    const report=data.report;
    const views=data.views||[];
    $('#design-result').innerHTML=`<div class="design-result-head"><div><span class="eyebrow">${esc(name)}</span><h2>${report?'快速草稿预览':'草稿构建进行中'}</h2><p class="hint">${esc(data.intent.request)}</p></div>${report&&report.status==='PASS'?`<a class="secondary" href="/api/design/file?${new URLSearchParams({name,kind:'schematic'})}">下载 .schem</a>`:''}</div>${report?`<div class="design-facts"><span>文件与几何：${esc(report.status)}</span><span>手法落实：${esc(data.quality_review?.status||'未检查')}</span><span>尺寸：${esc(report.dimensions_whl.join(' × '))} 格</span><span>开口：${esc(report.openings)}</span><span>游戏验收：${esc(report.game_acceptance)}</span></div>`:''}${data.quality_review?.missing_techniques?.length?`<p class="error inline-error">未落实规划手法：${esc(data.quality_review.missing_techniques.join('、'))}</p>`:''}${views.length?`<div class="design-preview"><img id="design-image" src="/api/design/file?${new URLSearchParams({name,kind:'view',view:views.includes('axonometric_front')?'axonometric_front':views[0]})}" alt="建筑生成预览"><div class="view-tabs">${views.map(view=>`<button type="button" data-design-view="${view}" class="${view==='axonometric_front'?'active':''}">${viewNames[view]}</button>`).join('')}</div></div>`:'<p class="hint">预览尚未就绪。构建结束后重新打开此版本。</p>'}<details><summary>查看构建记录与设计参数</summary><pre>${esc(JSON.stringify(data.intent,null,2))}</pre><pre>${esc(data.quality_review?JSON.stringify(data.quality_review,null,2):'暂无手法落实记录')}</pre><pre>${esc(data.log||'暂无日志')}</pre></details>`;
    if(report&&views.length){
      $('#design-result').insertAdjacentHTML('beforeend',`<form id="visual-review" class="visual-review"><h3>视觉评审</h3><p class="hint">逐张检查七视角。文件通过不等于外观合格，游戏验收仍独立进行。</p><div class="review-modes"><label><input type="radio" name="verdict" value="revise" ${!data.visual_review||data.visual_review.verdict==='revise'?'checked':''}> 需要修改</label><label><input type="radio" name="verdict" value="visually_approved" ${data.visual_review?.verdict==='visually_approved'?'checked':''}> 仅预览认可</label></div><textarea id="visual-note" aria-label="视觉评审意见" required minlength="3" placeholder="例如：正视图右侧屋顶断开，窗洞偏小；下一版先修屋顶连续性。">${esc(data.visual_review?.note||'')}</textarea><div class="actions"><button class="secondary" type="submit">保存视觉意见</button><span id="visual-status" class="hint" role="status">${data.visual_review?'已记录 '+esc(data.visual_review.verdict):'尚未评审'}</span></div></form>`);
      $('#visual-review').onsubmit=async event=>{
        event.preventDefault();const note=$('#visual-note').value.trim();const verdict=$('input[name=verdict]:checked').value;
        try{await api('/api/design/review',{run:name,verdict,note});$('#visual-status').textContent='视觉意见已保存；可在对话中继续提出修改。';if(agentSession)await restoreAgentSession();}
        catch(error){$('#visual-status').textContent=error.message;}
      };
    }
    if(activate)$('#design-result').scrollIntoView({block:'start',behavior:'smooth'});
  } catch(error) {toast(error.message);}
}
async function audit() {
  const m=state.data.manifest,a=m.audit,b=state.data.benchmark;
  $('#content').innerHTML=heading('EVIDENCE & VALIDATION','知道已验证什么，也知道还缺什么。','每一条技术结论都有范围。文件可读、语义正确、设计优秀与游戏成立分别记录。')+
    `<div class="audit-grid"><section class="panel"><h2>本次知识入库审计</h2>${[['实际入库',number(m.count)+' 条'],['新增源裁件',number(a.detail_count)+' 件'],['唯一裁件几何',number(a.unique_v2_geometry)+' 种'],['重复几何记录',number(a.duplicate_v2_records)+' 条（保留来源）'],['被拒裁切',number(a.excluded_cuts)+' 条'],['元数据 / 来源不一致',a.issues.length+' 项'],['向量维度',m.vector_dimension],['索引建立时间',new Date(m.created_at).toLocaleString('zh-CN')]].map(([k,v])=>`<div class="audit-row"><span>${k}</span><b>${esc(v)}</b></div>`).join('')}<p class="hint">来源哈希、清洗后裁件尺寸与状态清单逐件核对。以本次数据库记录为准。</p></section><section class="panel"><h2>验证边界</h2><ul class="audit-list">${a.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}<li>渲染使用原版方块模型；模组方块会被替代，不能据此验证模组细节。</li><li>DeepSeek 的文本解释不能代替看图与游戏测试。</li><li>用户选择“参考”只用于知识筛选，不等于游戏验收。</li></ul><h2 style="margin-top:24px">检索可行性试验</h2>${b?`<p>${number(b.passed)} / ${number(b.total)} 个预设检索案例命中目标范围。</p><p class="hint">${esc(b.scope)}</p><details><summary>查看试验记录</summary><pre>${esc(JSON.stringify(b,null,2))}</pre></details>`:'<p class="hint">试验报告尚未生成，不能提前宣称检索质量达标。</p>'}</section></div>
    <section class="panel" style="margin-top:23px"><div class="section-heading"><h2>被拒裁切及原因</h2><span class="hint">显示前 50 条 / 共 ${a.excluded_cuts} 条</span></div><div id="exclusions"><p class="hint">载入中…</p></div></section>`;
  try {const rows=await api('/api/exclusions');if(state.page==='audit')$('#exclusions').innerHTML=rows.items.map(r=>`<div class="exclusion"><b>${esc(r.detail_id||r.source)} <span>· ${esc(r.source)}</span></b><span>${esc(r.reason)}</span></div>`).join('');}catch(e){toast(e.message);}
}
async function openRecord(id) {
  if(!selectedId)lastFocus=document.activeElement;
  selectedId=id;$('#drawer').hidden=false;$('#drawer-backdrop').hidden=false;document.body.style.overflow='hidden';
  $('#drawer-content').innerHTML='<div class="loading">正在读取证据…</div>';
  try {
    const r=await api('/api/record?'+new URLSearchParams({id}));if(selectedId!==id)return;
    const defaultView=r.raw?.outside==='south/+z'?'axonometric_back':'axonometric_front';
    const image=r.render?asset(id,'view',defaultView):r.image?asset(id):'';
    $('#drawer-content').innerHTML=`<div class="drawer-head"><span>${layerNames[r.layer]} / ${esc(originNames[r.origin])}</span><button class="icon-button" id="drawer-close" aria-label="关闭知识详情">×</button></div><div class="drawer-main"><span class="eyebrow">KNOWLEDGE RECORD</span><h2>${esc(r.title)}</h2><div class="flex mb"><span class="status-tag ${r.review.status}">${reviewNames[r.review.status]}</span><span class="pill">语义待复核</span><span class="pill">游戏未验收</span></div>${image?`<img id="detail-image" class="detail-image" src="${image}" alt="构件预览">`:`<div class="card-visual">${art(r.layer)}<span class="dimension-label">${r.schematic?'可生成真实方块模型预览':'知识规则 · 无实体裁件'}</span></div>`}
    ${r.render?`<div class="view-tabs">${r.render.views.map(v=>`<button data-view="${v}" class="${v===defaultView?'active':''}">${viewNames[v]}</button>`).join('')}</div><p class="hint">七视图来自当前裁件。${r.render.warnings.length?'存在 '+r.render.warnings.length+' 条渲染警告；模组 / 实体效果需复核。':'简化光照与玻璃效果，不能代替游戏验收。'}</p>`:''}
    <div class="detail-actions">${r.schematic?`<button class="secondary" id="render-record">${r.render?'重新渲染七视图':'生成构件七视图'}</button><a class="secondary" href="${asset(id,'schematic')}">下载 .schem ↓</a>`:''}<button class="primary" id="annotate-record">DeepSeek 辅助解释 ↗</button></div><div id="record-job" class="hint" role="status"></div>
    <div class="detail-facts"><div>实际尺寸<strong>${r.dimensions?r.dimensions.join(' × ')+' 格':'规则层'}</strong></div><div>来源关联<strong>${r.sources.length} 份素材</strong></div><div>记录类型<strong>${esc(originNames[r.origin])}</strong></div></div><p>${esc(r.summary)}</p>
    ${r.observations.length?`<h3>文件可确认的事实</h3><ul>${r.observations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}${r.inferences.length?`<h3>解释与推断</h3><ul>${r.inferences.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}<h3>适用边界与待验证条件</h3><ul>${r.constraints.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
    ${r.annotation?`<section class="panel"><h3 style="margin-top:0">AI 辅助解释</h3>${proposalHtml(r.annotation)}</section>`:''}
    ${r.links.length?`<h3>关联知识</h3><div class="evidence-list">${r.links.map(x=>`<button class="evidence-item" data-record="${esc(x)}"><span>${esc(x)}</span><span>→</span></button>`).join('')}</div>`:''}
    <h3>来源证据</h3>${r.evidence.map(e=>`<div class="evidence-block">${esc(e.path)}<br>定位：${esc(e.locator)}<code>SHA-256 ${esc(e.sha256)}</code></div>`).join('')}
    ${r.sources.length?`<h3>关联源素材</h3>${r.sources.map(sid=>{const s=state.data.sources.find(x=>x.id===sid);return s?`<div class="evidence-block">${esc(s.name)} · ${esc(s.group)}${s.image?`<img loading="lazy" class="detail-image" src="${asset(s.id,'source')}" alt="${esc(s.name)} 原始截图">`:''}<code>${esc(s.path)}</code></div>`:'';}).join('')}`:''}
    <h3>你的参考筛选</h3><input class="review-note" id="review-note" aria-label="参考筛选备注" placeholder="记录为什么值得学习，或为什么需要排除" value="${esc(r.review.note)}"><div class="detail-actions"><button class="primary" data-review="reference">收录为参考</button><button class="secondary" data-review="unreviewed">保持待复核</button><button class="secondary" data-review="excluded">排除</button></div><p class="hint">这是知识参考筛选，游戏验收状态不会随之改变。</p>
    <details><summary>查看完整原始记录、方块状态与清洗记录</summary><pre>${esc(JSON.stringify(r.raw,null,2))}</pre></details>${r.duplicate_ids?.length?`<p class="hint">另有 ${r.duplicate_ids.length} 条相同几何记录；保留了各自来源。</p>`:''}</div>`;
    $('#drawer-close').onclick=closeDrawer;$('#drawer-close').focus();
    if($('#render-record'))$('#render-record').onclick=()=>recordJob('render',id);
    $('#annotate-record').onclick=()=>recordJob('annotate',id);
  }catch(e){$('#drawer-content').innerHTML=`<div class="drawer-head">知识详情<button class="icon-button" id="drawer-close" aria-label="关闭知识详情">×</button></div><div class="error">${esc(e.message)}</div>`;$('#drawer-close').onclick=closeDrawer;}
}
async function recordJob(kind,id) {
  const el=$('#record-job');el.textContent=kind==='render'?'正在启动真实方块模型渲染…':'正在连接 DeepSeek…';
  const btn=kind==='render'?$('#render-record'):$('#annotate-record');btn.disabled=true;
  try {const r=await api('/api/'+kind,{id});await poll(r.job_id,message=>el.textContent=message);if(selectedId===id)await openRecord(id);await refreshOverview();toast(kind==='render'?'七视图已生成':'AI 解释已保存为待复核推断');}
  catch(e){el.textContent=e.message;btn.disabled=false;}
}
function closeDrawer(){selectedId=null;$('#drawer').hidden=true;$('#drawer-backdrop').hidden=true;document.body.style.overflow='';lastFocus?.focus();}
$('#drawer-backdrop').onclick=closeDrawer;
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&selectedId)closeDrawer();if(e.key==='Tab'&&selectedId){const els=[...$('#drawer').querySelectorAll('button:not([disabled]),a[href],input,summary')];if(!els.length)return;const first=els[0],last=els[els.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
document.addEventListener('click',async e=>{
  const el=e.target.closest('button,[data-record]');if(!el)return;
  if(el.hasAttribute('data-remove-reference')){if(agentSending)return;const index=Number(el.dataset.removeReference);URL.revokeObjectURL(pendingReferences[index].url);pendingReferences.splice(index,1);renderAgentReferences();return;}
  if(el.dataset.go)location.hash=el.dataset.go;
  if(el.dataset.layerGo){state.layer=el.dataset.layerGo;state.offset=0;location.hash='library';if(state.page==='library')library();}
  if(el.dataset.sourceGo){state.source=el.dataset.sourceGo;state.layer='';state.query='';state.offset=0;location.hash='library';}
  if(el.hasAttribute('data-layer')){state.layer=el.dataset.layer;state.offset=0;library();}
  if(el.dataset.query){state.query=el.dataset.query;state.offset=0;library();}
  if(el.dataset.pageStep){state.offset=Math.max(0,state.offset+Number(el.dataset.pageStep)*24);loadResults();}
  if(el.dataset.record)openRecord(el.dataset.record);
  if(el.dataset.deleteSession||el.dataset.deleteCurrent){deleteAgentSession(el.dataset.deleteSession||agentSession);return;}
  if(el.dataset.undoSession){undoAgentSession(el.dataset.undoSession);return;}
  if(el.dataset.retryAgent){const data=await api('/api/agent/session?'+new URLSearchParams({id:agentSession}));const prior=[...data.events].reverse().find(e=>e.kind==='user');if(prior){$('#agent-input').value=prior.text;$('#agent-form').requestSubmit();}return;}
  if(el.dataset.agentSession)selectAgentSession(el.dataset.agentSession);
  if(el.dataset.studioTab)setStudioTab(el.dataset.studioTab);
  if(el.dataset.openProvider)$('#provider-dialog').showModal();
  if(el.dataset.designRun)openDesignRun(el.dataset.designRun,{activate:true});
  if(el.dataset.designView&&activeRun){
    $('#design-image').src='/api/design/file?'+new URLSearchParams({name:activeRun,kind:'view',view:el.dataset.designView});
    document.querySelectorAll('[data-design-view]').forEach(x=>x.classList.toggle('active',x===el));
  }
  if(el.dataset.view&&selectedId){$('#detail-image').src=asset(selectedId,'view',el.dataset.view);$('.view-tabs').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===el));}
  if(el.dataset.review&&selectedId){try{const id=selectedId;await api('/api/review',{id,status:el.dataset.review,note:$('#review-note').value});await refreshOverview();toast('参考筛选已保存');await openRecord(id);if(state.page==='library')loadResults();}catch(err){toast(err.message);}}
});
$('#provider-open').onclick=()=>$('#provider-dialog').showModal();$('#provider-close').onclick=()=>$('#provider-dialog').close();
$('#provider-form').onsubmit=async e=>{e.preventDefault();const button=$('button[type=submit]',e.target);button.disabled=true;$('#provider-result').textContent='正在验证账户与模型…';try{const key=$('#api-key').value.trim();const r=await api('/api/provider',{key});$('#api-key').value='';$('#provider-result').textContent='已连接 '+r.model+'，密钥由 Windows 用户凭据保护';await refreshOverview();}catch(err){$('#provider-result').textContent=err.message;}finally{button.disabled=false;}};
async function refreshOverview(){state.data=await api('/api/overview');$('#nav-count').textContent=number(state.data.manifest.count);$('#provider-label').textContent=state.data.provider.configured?'DeepSeek 已连接':'本地知识引擎';$('#provider-dot').style.background=state.data.provider.configured?'#bedc7a':'#879884';}
function route(){const key=location.hash.slice(1)||'overview';state.page=labels[key]?key:'overview';document.body.classList.toggle('studio-mode',state.page==='studio');requestVersion++;$('#global-error').hidden=true;$('#page-name').textContent=labels[state.page];document.querySelectorAll('nav a').forEach(x=>x.classList.toggle('active',x.dataset.page===state.page));({overview,library,sources,studio,audit})[state.page]();window.scrollTo(0,0);}
window.addEventListener('hashchange',()=>{if(state.data)route();});
window.addEventListener('unhandledrejection',e=>fail(e.reason));
refreshOverview().then(route).catch(e=>{fail(e);$('#content').innerHTML='<div class="empty">知识库服务暂不可用，请检查启动窗口或稍后刷新。</div>';});
