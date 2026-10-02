/* Formal stages, explicit visual observations and durable operation receipts. */
let agentEventSource = null;
let agentEventSession = null;
const qualityLabels={style_character:'风格表达',composition:'构图',storey_expression:'楼层层级',material_coherence:'材料协调',detail_craft:'当前阶段细节品质',all_direction_readability:'各向可读性'};
function connectAgentEvents(session) {
  if(agentEventSession===session&&agentEventSource?.readyState!==EventSource.CLOSED)return;
  agentEventSource?.close();
  agentEventSession=session;
  agentEventSource = new EventSource('/api/agent/events?' + new URLSearchParams({id:session}));
  let scheduled = false;
  agentEventSource.onmessage = () => {
    if (scheduled || state.page !== 'studio' || agentSession !== session) return;
    scheduled = true;
    setTimeout(async () => { scheduled=false; await restoreAgentSession(); }, 250);
  };
}
const stageLabels = {research:'来源研究',retrieval:'四层检索',frameworks:'造型设计',facades:'立面设计',tier2:'二级细化',tier3:'三级细化',delivery:'交付验证',game:'游戏验收',accepted:'用户已验收'};
const layerLabels = {shop_base:'底层店面',noble_floor:'贵族层',upper_floors:'标准层',attic:'顶层',roof:'屋顶',party_walls:'共墙',corner:'转角'};
function workflowProgressMessage(data) {
  const stage=data.status.stage;
  if(['queued','running','stopping'].includes(data.job?.status))return 'Agent 正在生成、看图评审并自动推进…';
  if(String(data.status.awaiting||'').startsWith('AGENT_'))return data.job?.error||'当前阶段已暂停，可恢复继续';
  const last=data.history?.at(-1);
  if(last?.rollback_from&&last.to===stage)return '已从'+(stageLabels[last.rollback_from]||last.rollback_from)+'退回'+(stageLabels[stage]||stage)+'。修改依据：'+(last.reason||'需重新生成并评审当前阶段。');
  if(data.ready_for_review)return '候选已就绪，Agent 将完成阶段评审。';
  if(data.latest_review?.decision==='pass'&&data.latest_review.revision===data.status.revision)return '上一阶段评审已通过，可继续'+(stageLabels[stage]||stage)+'。';
  return '';
}
function sourceStateEvidenceContent(report) {
  if(!report)return '';
  const categories=report.source_special_categories||{};
  const labels={thin_door_window:'门叶薄窗片',single_arm_wall:'单臂墙肢',shaped_stair:'异形楼梯'};
  const faces={street_north:'北街',street_east:'东街'};
  const windows=report.opening_coverage||[],passed=windows.filter(row=>row.status==='PASS').length;
  return `<details open data-source-state><summary>来源构法核对 · ${esc(report.status)}</summary>
    <p>两街住宅窗覆盖：${passed} / ${windows.length} 扇窗通过。来源状态匹配：${number(report.matched)} / ${number(report.declared)} 格。</p>
    <p>${Object.entries(labels).map(([key,label])=>`${label} ${number(categories[key])} 格`).join(' · ')}</p>
    ${report.matched_ordinary_header_cells?`<p>普通窗楣填充：${number(report.matched_ordinary_header_cells)} 格。</p>`:''}
    <p class="hint">核对范围：北街与东街住宅窗的来源状态和声明放置位置。游戏验收：${esc(report.game_acceptance||'PENDING')}。</p>
    ${windows.length?`<details><summary>逐窗覆盖记录</summary>${windows.map(row=>`<p>${esc(faces[row.face]||row.face)} · ${esc(row.storey)} 层 · 窗 ${Number(row.opening_id)+1} · ${esc(row.status)}${row.missing_categories?.length?`<br>待补齐：${row.missing_categories.map(key=>esc(labels[key]||key)).join('、')}`:''}${row.missing_thin_window_cells?`<br>薄窗片尚缺 ${number(row.missing_thin_window_cells)} 格`:''}</p>`).join('')}</details>`:''}
  </details>`;
}
let workflowRefreshTimer=null;
const operationLoads=new Map();
const operationViews=new Map();
Object.assign(operationNames,{'generator.repair':'生成器修复','dsh.generator_repair':'源码诊断与补丁设计',
  'dsh.framework_planning':'提示词核对与造型设计'});
function renderOperationContent(panel,receipt){
  const host=panel.querySelector('.atomic-content');if(!host)return;
  const result=receipt.result||{},proposal=result.proposal||{},review=result.review||{};
  const text=(label,value)=>value?`<section class="operation-section"><h4>${esc(label)}</h4><p>${esc(typeof value==='string'?value:JSON.stringify(value,null,2))}</p></section>`:'';
  const checks=group=>Object.entries(group||{}).map(([key,value])=>`<div class="operation-check"><strong>${esc(key)}</strong><span class="atomic-${value.status==='pass'?'SUCCEEDED':'FAILED'}">${esc(value.status||'')}</span><p>${esc(value.observation||'')}</p></div>`).join('');
  const images=receipt.preview_images||[];
  const prior=operationViews.get(panel.dataset.atomic)||host.querySelector('[data-operation-view].active')?.dataset.operationView;
  const active=images.some(image=>image.url===prior)?prior:(images.find(image=>image.name==='axonometric_front')||images[0])?.url;
  host.innerHTML=text('当前状态',receipt.error)+text('设计依据',result.design_rationale||proposal.reason||proposal.summary)+
    text('问题诊断',proposal.diagnosis)+
    ([].concat(proposal.framework_candidates||proposal.framework_candidate||[]).map((row,i)=>text('造型方案 '+(i+1)+' · 设计选择',row.rationale)).join(''))+
    (images.length?`<div class="operation-images"><img src="${esc(active)}" alt="步骤对应建筑视图"><div class="view-tabs">${images.map(image=>`<button type="button" data-operation-view="${esc(image.url)}" class="${image.url===active?'active':''}">${esc(viewNames[image.name]||image.name)}</button>`).join('')}</div></div>`:'')+
    (proposal.confirmed_brief||result.confirmed_brief?`<details><summary>已确认任务书</summary>${text('完整规格',proposal.confirmed_brief||result.confirmed_brief)}</details>`:'')+
    (proposal.architectural_contract?`<details><summary>建筑规制</summary>${text('设计约束',proposal.architectural_contract)}</details>`:'')+
    (proposal.unsupported_decisions?.length?`<details><summary>待补齐的生成器能力 · ${proposal.unsupported_decisions.length} 项</summary>${text('源码能力诊断',proposal.unsupported_decisions)}</details>`:'')+
    text('审核结论',review.decision)+text('发现的问题',review.failure_modes)+
    (review.view_observations?`<details><summary>逐视图观察</summary>${Object.entries(review.view_observations).map(([view,value])=>text(viewNames[view]||view,value)).join('')}</details>`:'')+
    (review.geometry_checks?`<details open><summary>框架形制检查</summary>${checks(review.geometry_checks)}</details>`:'')+
    (review.detail_checks?`<details><summary>逐层构件检查</summary>${Object.entries(review.detail_checks).map(([layer,group])=>`<h4>${esc(layerLabels[layer]||layer)}</h4>${checks(group)}`).join('')}</details>`:'')+
    (review.storey_checks?`<details><summary>逐楼层检查</summary>${Object.entries(review.storey_checks).map(([floor,group])=>`<h4>${Number(floor)===0?'地面层':esc(floor)+' 层'}</h4>${checks(group)}`).join('')}</details>`:'')+
    (review.reference_comparison?`<details><summary>参考图对照</summary>${text('逐图比较',review.reference_comparison)}</details>`:'')+
    (proposal.edits?`<details><summary>源码修改 · ${proposal.edits.length} 处</summary>${proposal.edits.map(edit=>`<h4>${esc(edit.file)}</h4><pre>${esc(edit.before)}\n\n→\n\n${esc(edit.after)}</pre>`).join('')}</details>`:'')+
    (receipt.validation||result.validation?`<details><summary>验证结果 · ${esc((receipt.validation||result.validation).status||receipt.status)}</summary>${text('完整验证',receipt.validation||result.validation)}</details>`:'')+
    (receipt.tools?.length?`<details><summary>实际工具调用 · ${receipt.tools.length} 次</summary>${receipt.tools.map(tool=>text(tool.tool,tool.inputs)).join('')}</details>`:'')+
    `<details><summary>输入、输出与收据</summary><pre>${esc(JSON.stringify(receipt,null,2))}</pre></details>`;
  host.querySelectorAll('[data-operation-view]').forEach(button=>button.onclick=()=>{
    operationViews.set(panel.dataset.atomic,button.dataset.operationView);
    host.querySelector('.operation-images img').src=button.dataset.operationView;
    host.querySelectorAll('[data-operation-view]').forEach(other=>other.classList.toggle('active',other===button));
  });
}
async function loadOperationContent(panel){
  const id=panel.dataset.atomic;
  let receipt=operationReceipts.get(id);
  if(!receipt||receipt.status!==panel.dataset.operationStatus||receipt.status==='RUNNING'){
    if(!operationLoads.has(id))operationLoads.set(id,api('/api/operation/'+id).finally(()=>operationLoads.delete(id)));
    try{receipt=await operationLoads.get(id);operationReceipts.set(id,receipt);}
    catch(error){if(panel.isConnected)panel.querySelector('.atomic-content').textContent=error.message;return;}
  }
  if(panel.isConnected&&panel.open)renderOperationContent(panel,receipt);
}
document.addEventListener('toggle',event=>{
  const panel=event.target;if(panel.matches?.('[data-atomic]')&&panel.open)loadOperationContent(panel);
},true);
function workflowAsset(run,path) {
  const normalized=path.replaceAll('\\','/');
  const marker='/runs/'+run+'/';
  const relative=normalized.includes(marker)?normalized.split(marker)[1]:path;
  return '/api/workflow/file?'+new URLSearchParams({run,path:relative});
}
function renderFormalWorkflow(run,data) {
  clearTimeout(workflowRefreshTimer);
  const stage=data.status.stage, draftKey='atelier-review:'+run+':'+data.status.revision+':'+stage;
  let review=structuredClone(data.review_template);
  try {const saved=JSON.parse(localStorage.getItem(draftKey));if(saved&&JSON.stringify(saved.artifact_hashes)===JSON.stringify(review.artifact_hashes))review=saved;}catch(error){}
  const saveDraft=()=>localStorage.setItem(draftKey,JSON.stringify(review));
  const busy=['queued','running','stopping'].includes(data.job?.status);
  const autonomous=data.execution_mode==='autonomous';
  const retainedForStage=Object.keys(data.candidate_search?.best||{}).some(key=>key.startsWith(stage+':'));
  const preview=data.preview||{};
  const container=$('#design-result');
  const inspection=new Map([...(container.dataset.run===run?container.querySelectorAll('[data-candidate]'):[])].map(panel=>[
    panel.dataset.candidate,{open:panel.open,view:panel.dataset.activeView}]));
  const expanded=new Set([...container.querySelectorAll('details[open]')].map(panel=>panel.querySelector('summary')?.textContent));
  container.dataset.run=run;
  container.innerHTML=`<div class="design-result-head"><div><span class="eyebrow">${esc(run)} · 正式流程</span><h2>${esc(stageLabels[stage]||stage)}</h2><p>当前阶段：${esc(stageLabels[stage])} · 修订 ${data.status.revision} · 游戏验收 ${esc(data.status.game_acceptance)}</p></div><button class="secondary" id="workflow-refresh">刷新进度</button></div>
    <div class="workflow-stages">${Object.entries(stageLabels).map(([key,label])=>`<span class="${key===stage?'current':''}">${esc(label)}</span>`).join('')}</div>
    <div id="workflow-message" role="status">${esc(workflowProgressMessage(data))}</div>
    ${!busy&&['frameworks','facades','tier2','tier3','delivery'].includes(stage)?'<button class="primary" id="workflow-auto">由 Agent 继续完成</button>':''}
    ${Object.keys(data.candidate_search?.best||{}).length?`<details><summary>保留的最佳候选</summary><p>恢复产物后会重新测量并评审。</p>${Object.values(data.candidate_search.best).map(entry=>`<p>${esc(stageLabels[entry.stage]||entry.stage)} · 修订 ${esc(entry.original_revision)} · ${entry.metric.feasible===true?'已测符合性通过':'历史候选，待测量复核'} · ${entry.metric.failed} 项失败 / ${entry.metric.unsupported} 项待核实</p>`).join('')}${!busy&&retainedForStage?'<button class="secondary" id="workflow-restore-best">恢复最佳候选并重新评审</button>':''}</details>`:''}
    ${data.latest_review?`<details ${data.latest_review.revision===data.status.revision?'open':''} data-latest-review><summary>${data.latest_review.revision===data.status.revision?'最近阶段评审':'此前阶段评审'} · 修订 ${esc(data.latest_review.revision)} · ${esc(stageLabels[data.latest_review.stage]||data.latest_review.stage)} · ${esc(data.latest_review.decision)}</summary>${data.latest_review.candidates.map(item=>`<p>${esc(item.id||'当前方案')} · ${esc(item.conformance_status||'')}</p>${item.quality_checks?Object.entries(item.quality_checks).map(([key,check])=>`<p><strong>${esc(qualityLabels[key]||key)} · ${esc(check.status)}</strong><br>${esc(check.observation.replace(new RegExp('^'+key+'[:：]\\s*'),''))}</p>`).join(''):''}${(item.failure_modes||[]).map(note=>`<p>${esc(note)}</p>`).join('')}`).join('')}</details>`:''}
    <details><summary>Agent 阶段记录</summary><pre>${esc(JSON.stringify(data.history,null,2))}</pre></details>
    ${['frameworks','facades','tier2','tier3','delivery'].includes(stage)&&!data.ready_for_review?`<button class="primary" id="workflow-build" ${busy?'disabled':''}>${busy?'正在生成…':'生成当前阶段'}</button>`:''}
    ${data.delivery?`<a class="primary" href="${workflowAsset(run,'delivery.zip')}">下载建筑与状态实验包</a>`:''}
    ${data.delivery?`<div class="actions"><a class="secondary" href="${workflowAsset(run,data.delivery_files.building)}">建筑 .schem</a><a class="secondary" href="${workflowAsset(run,data.delivery_files.state_lab)}">状态实验 .schem</a></div>`:''}
    ${!data.candidates.length&&Object.keys(preview).length?`${data.delivery?'':'<p class="hint">当前阶段候选尚未生成，显示此前阶段建筑预览。</p>'}<div class="design-preview"><img id="workflow-final-image" src="${workflowAsset(run,(preview.axonometric_front||Object.values(preview)[0]).path)}" alt="${data.delivery?'交付建筑预览':'此前阶段建筑预览'}"><div class="view-tabs">${Object.keys(preview).filter(view=>viewNames[view]).map(view=>`<button type="button" data-final-view="${view}">${esc(viewNames[view])}</button>`).join('')}</div></div>`:''}
    <details><summary>任务书与此前选择</summary><pre>${esc(JSON.stringify({brief:data.brief,selected:data.selected},null,2))}</pre></details>
    ${data.candidates.length?'<h3>手法样本参考 · 优秀立面代表（学习手法用，非验收标准）</h3><div class="workflow-references">'+data.references.map(path=>`<a href="/api/workflow/reference?${new URLSearchParams({name:path.replaceAll('\\','/').split('/').pop()})}" target="_blank" rel="noopener"><img loading="lazy" src="/api/workflow/reference?${new URLSearchParams({name:path.replaceAll('\\','/').split('/').pop()})}" alt="${esc(path)}"><span>${esc(path.split(/[\\/]/).pop())}</span></a>`).join('')+'</div>':''}
    <div id="workflow-candidates"></div>
    ${data.candidates.length?`<form id="workflow-review"><h3>阶段结论</h3><label>选定候选<select id="workflow-selected">${data.candidates.map(c=>`<option value="${esc(c.id||'')}">${esc(c.id||'当前方案')}</option>`).join('')}</select></label><label>结论<select id="workflow-decision"><option value="reject">退回修改</option><option value="pass">通过并进入下一阶段</option></select></label><label>回退阶段<select id="workflow-rollback">${Object.keys(stageLabels).filter(s=>['frameworks','facades','tier2','tier3'].includes(s)&&Object.keys(stageLabels).indexOf(s)<=Object.keys(stageLabels).indexOf(stage)).map(s=>`<option value="${s}" ${s===stage?'selected':''}>${stageLabels[s]}</option>`).join('')}</select></label><label>具体依据<textarea id="workflow-rationale" required minlength="5" placeholder="说明选择或退回的视图证据与原因"></textarea></label><button class="primary">保存评审并应用门槛</button></form>`:''}
    ${stage==='game'?`<form id="workflow-game"><h3>记录你的游戏验收</h3><p>仅填写你实际在 Minecraft 1.21.11 中观察到的结果。</p>${[['normal_update_comparison','已对比正常更新'],['suppressed_update','禁止更新粘贴符合预期'],['neighbor_change','相邻变化后符合预期'],['chunk_reload','区块重载后符合预期']].map(([key,label])=>`<label><input type="checkbox" data-game="${key}"> ${label}</label>`).join('')}<label>结论<select id="game-decision"><option value="rejected">需要修改</option><option value="accepted">我已验收通过</option></select></label><textarea id="game-statement" aria-label="游戏实际观察" placeholder="记录客户端、粘贴工具、更新设置与实际观察" required minlength="5"></textarea><button class="primary">保存实际验收记录</button></form>`:''}`;
  $('#workflow-refresh').onclick=()=>openDesignRun(run);
  if($('#workflow-restore-best'))$('#workflow-restore-best').onclick=async()=>{
    const button=$('#workflow-restore-best');button.disabled=true;
    try{await api('/api/workflow/restore-best',{run});await openDesignRun(run);}
    catch(error){toast(error.message);button.disabled=false;}
  };
  if($('#workflow-auto'))$('#workflow-auto').onclick=async()=>{const button=$('#workflow-auto');button.disabled=true;try{const result=await api('/api/workflow/autonomous',{run});if(activeRun===run)await openDesignRun(run);await followBuild(result);}catch(error){toast(error.message);button.disabled=false;}};
  document.querySelectorAll('[data-final-view]').forEach(button=>button.onclick=()=>{
    $('#workflow-final-image').src=workflowAsset(run,preview[button.dataset.finalView].path);
    document.querySelectorAll('[data-final-view]').forEach(item=>item.classList.toggle('active',item===button));
  });
  const followBuild=async queued=>{
    try {await poll(queued.job_id,message=>{if(state.page==='studio'&&activeRun===run&&$('#workflow-message'))$('#workflow-message').textContent=message;});}
    catch(error){toast(error.message);}
    if(state.page==='studio'&&activeRun===run)await openDesignRun(run,{activate:false});
  };
  if(busy)workflowRefreshTimer=setTimeout(()=>{if(state.page==='studio'&&activeRun===run&&studioTab==='preview')openDesignRun(run,{activate:false});},4000);
  if($('#workflow-build'))$('#workflow-build').onclick=async()=>{
    const button=$('#workflow-build');button.disabled=true;
    try {const result=await api('/api/workflow/build',{run});if(activeRun===run)await openDesignRun(run);await followBuild(result);}
    catch(error){$('#workflow-message').textContent=error.message;button.disabled=false;}
  };
  data.candidates.forEach((candidate,index)=>{
    const item=review.candidates.find(item=>item.id===candidate.id);
    const panel=document.createElement('details');panel.className='workflow-candidate';panel.dataset.candidate=candidate.id;
    const previous=inspection.get(candidate.id);panel.open=previous?previous.open:index===0;
    panel.innerHTML=`<summary>${esc(candidate.id||'当前方案')} · ${candidate.plan.width} × ${candidate.plan.depth} · ${candidate.plan.storeys} 层</summary><p class="hint">${esc(candidate.plan.form)} / ${esc(candidate.plan.scheme)} · 种子 ${candidate.plan.seed}</p><label>候选结论<select data-verdict><option value="reject">待修改 / 未通过</option><option value="pass">视觉通过</option></select></label><div class="workflow-scores">${['地块关系','多面闭合','轮廓比例','立面层级','全向可读'].map((label,i)=>`<label>${label}<input type="number" min="0" max="20" step="1" value="0" data-score="${i}"></label>`).join('')}</div><div class="view-tabs">${Object.keys(candidate.views).map(view=>`<button type="button" data-stage-view="${esc(view)}">${esc(viewNames[view]||view)}</button>`).join('')}</div><img class="workflow-preview" alt="候选当前视图"><label data-observation-label></label><textarea data-observation placeholder="记录当前视图可见的结构、层级、开口、交接与缺陷"></textarea><small data-observation-count></small><details><summary>逐张标准图对照</summary>${Object.keys(item.reference_comparison).map((key,i)=>`<label>${esc(key)}<textarea data-reference="${i}" placeholder="写出与该标准的具体相同点、差距和适用边界"></textarea></label>`).join('')}</details><label>失败模式（确无缺陷时明确写“无”）<textarea data-failures></textarea></label>`;
    let activeView=candidate.views[previous?.view]?previous.view:Object.keys(candidate.views)[0];
    const selectView=view=>{activeView=view;panel.dataset.activeView=view;panel.querySelector('img').src=workflowAsset(run,candidate.views[view].path);panel.querySelector('[data-observation-label]').textContent=(viewNames[view]||view)+'：具体观察';panel.querySelector('[data-observation]').value=item.view_observations[view];panel.querySelectorAll('[data-stage-view]').forEach(b=>b.classList.toggle('active',b.dataset.stageView===view));};
    panel.querySelector('[data-verdict]').value=item.decision;
    panel.querySelector('[data-verdict]').onchange=e=>{item.decision=e.target.value;saveDraft();};
    panel.querySelectorAll('[data-score]').forEach(input=>{input.value=item.scores[Number(input.dataset.score)];input.oninput=()=>{item.scores[Number(input.dataset.score)]=Number(input.value);saveDraft();};});
    panel.querySelectorAll('[data-stage-view]').forEach(button=>button.onclick=()=>selectView(button.dataset.stageView));
    panel.querySelector('[data-observation]').oninput=e=>{item.view_observations[activeView]=e.target.value;panel.querySelector('[data-observation-count]').textContent=Object.values(item.view_observations).filter(x=>x.trim()).length+' / '+Object.keys(item.view_observations).length+' 个视图已记录';};
    panel.querySelector('[data-observation]').addEventListener('input',saveDraft);
    panel.querySelectorAll('[data-reference]').forEach(input=>{const key=Object.keys(item.reference_comparison)[Number(input.dataset.reference)];input.value=item.reference_comparison[key];input.oninput=()=>{item.reference_comparison[key]=input.value;saveDraft();};});
    panel.querySelector('[data-failures]').value=item.failure_modes.join('\n');
    panel.querySelector('[data-failures]').oninput=e=>{item.failure_modes=e.target.value.split('\n').filter(x=>x.trim());saveDraft();};
    if(['layered-v1','layered-v2'].includes(data.review_policy)){
      panel.insertAdjacentHTML('beforeend',`<details><summary>逐层建筑检查</summary>${Object.entries(layerLabels).map(([key,label])=>`<label>${label}<select data-layer="${key}"><option value="">待检查</option><option value="pass">通过</option><option value="fail">需修改</option><option value="not_applicable">不适用</option></select><textarea data-layer-note="${key}" aria-label="${label}观察" placeholder="具体观察与依据"></textarea></label>`).join('')}</details>`);
      panel.querySelectorAll('[data-layer]').forEach(input=>{const check=item.layer_checks[input.dataset.layer];input.value=check.status;input.onchange=()=>{check.status=input.value;saveDraft();};});
      panel.querySelectorAll('[data-layer-note]').forEach(input=>{const check=item.layer_checks[input.dataset.layerNote];input.value=check.observation;input.oninput=()=>{check.observation=input.value;saveDraft();};});
    }
    $('#workflow-candidates').append(panel);selectView(activeView);
    if(candidate.conformance){
      const report=candidate.conformance;
      const findings=report.checks.filter(check=>check.required);
      panel.insertAdjacentHTML('beforeend',`<details open data-conformance><summary>几何符合性 · ${esc(report.status)}</summary><p>从当前导出建筑测量；各项独立判定。</p>${findings.map(check=>`<p><strong>${esc(check.id)} · ${esc(check.status)}</strong><br>${esc(check.observation)}</p>`).join('')}<details><summary>完整测量与适用范围</summary><pre>${esc(JSON.stringify(report,null,2))}</pre></details></details>`);
    }
    if(candidate.source_state_evidence)panel.insertAdjacentHTML('beforeend',sourceStateEvidenceContent(candidate.source_state_evidence));
    if(item.quality_checks)panel.insertAdjacentHTML('beforeend',`<details data-quality><summary>六项视觉品质</summary><p>风格、构图、楼层表达、材料协调、当前阶段细节品质、全向可读性由模型评审。</p></details>`);
  });
  container.querySelectorAll('details:not([data-candidate])').forEach(panel=>{
    if(expanded.has(panel.querySelector('summary')?.textContent))panel.open=true;
  });
  if($('#workflow-review'))$('#workflow-review').hidden=true;
  document.querySelectorAll('.workflow-candidate').forEach(panel=>{
    panel.querySelectorAll('label,textarea,.workflow-scores,small,details').forEach(element=>{
      if(!element.closest('[data-conformance],[data-quality],[data-source-state]'))element.hidden=true;
    });
  });
  if($('#workflow-review')){
    $('#workflow-selected').value=review.selected||'';$('#workflow-decision').value=review.decision;$('#workflow-rollback').value=review.rollback_stage;$('#workflow-rationale').value=review.rationale;
    $('#workflow-review').addEventListener('input',()=>{review.selected=$('#workflow-selected').value||null;review.decision=$('#workflow-decision').value;review.rollback_stage=$('#workflow-rollback').value;review.rationale=$('#workflow-rationale').value;saveDraft();});
    $('#workflow-review').onsubmit=async event=>{
    event.preventDefault();review.selected=$('#workflow-selected').value||null;review.decision=$('#workflow-decision').value;review.rollback_stage=$('#workflow-rollback').value;review.rationale=$('#workflow-rationale').value;
    const button=event.submitter;button.disabled=true;saveDraft();
    try {const result=await api('/api/workflow/review',{run,review});localStorage.removeItem(draftKey);if(activeRun===run)await openDesignRun(run);if(result.build)await followBuild(result.build);if(result.build_error)toast(result.build_error);}catch(error){if(activeRun===run&&$('#workflow-message'))$('#workflow-message').textContent=error.message;}finally{button.disabled=false;}
  };}
  if($('#workflow-game'))$('#workflow-game').onsubmit=async event=>{
    event.preventDefault();const experiments=Object.fromEntries([...document.querySelectorAll('[data-game]')].map(input=>[input.dataset.game,input.checked?'PASS':'NOT_RUN']));
    try{await api('/api/workflow/game',{run,user_statement:$('#game-statement').value,decision:$('#game-decision').value,experiments});if(activeRun===run)await openDesignRun(run);}catch(error){if(activeRun===run&&$('#workflow-message'))$('#workflow-message').textContent=error.message;}
  };
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-operation]');if(!button)return;
  try{const receipt=await api('/api/operation/'+button.dataset.operation);operationReceipts.set(button.dataset.operation,receipt);const target=document.createElement('pre');target.textContent=JSON.stringify(receipt,null,2);button.after(target);button.disabled=true;}catch(error){toast(error.message);}
});
