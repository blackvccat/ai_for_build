const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

test('background refresh and delayed build completion preserve the selected view',async()=>{
  const source=fs.readFileSync('web/learning/app.js','utf8');
  const open=source.slice(source.indexOf('async function openDesignRun('),source.indexOf('async function audit('));
  let resolve;const switched=[];
  let rendered=0;
  const context=vm.createContext({URLSearchParams,activeRun:null,state:{page:'studio'},studioTab:'preview',agentSession:'one',designRequestVersion:0,
    setStudioTab:tab=>{switched.push(tab);context.studioTab=tab;},api:()=>new Promise(done=>{resolve=done;}),
    $:()=>({querySelector:()=>true}),renderFormalWorkflow:()=>{rendered++;},toast:()=>{}});
  vm.runInContext(open,context);
  const refresh=vm.runInContext("openDesignRun('ATELIER-test',{activate:false})",context);
  context.studioTab='trace';resolve({workflow:{}});await refresh;
  assert.deepEqual(switched,[]);
  assert.equal(rendered,0);
  await vm.runInContext("openDesignRun('ATELIER-test')",context);
  assert.deepEqual(switched,[]);
  const explicit=vm.runInContext("openDesignRun('ATELIER-test',{activate:true})",context);
  assert.deepEqual(switched,['preview']);resolve({workflow:{}});await explicit;
});

test('late preview responses cannot overwrite another session or a newer response',async()=>{
  const source=fs.readFileSync('web/learning/app.js','utf8');
  const open=source.slice(source.indexOf('async function openDesignRun('),source.indexOf('async function audit('));
  const pending=[],rendered=[];
  const context=vm.createContext({URLSearchParams,activeRun:null,state:{page:'studio'},studioTab:'preview',agentSession:'one',designRequestVersion:0,
    api:()=>new Promise(done=>pending.push(done)),$:()=>({querySelector:()=>true}),
    renderFormalWorkflow:(name,data)=>rendered.push(data.version),toast:()=>{}});
  vm.runInContext(open,context);
  const old=vm.runInContext("openDesignRun('same-run')",context);
  context.agentSession='two';pending.shift()({workflow:{version:'old-session'}});await old;
  assert.deepEqual(rendered,[]);
  const first=vm.runInContext("openDesignRun('same-run')",context);
  const second=vm.runInContext("openDesignRun('same-run')",context);
  pending[1]({workflow:{version:'newer'}});await second;
  pending[0]({workflow:{version:'older'}});await first;
  assert.deepEqual(rendered,['newer']);
});

test('workflow refresh timer stops refreshing when the user leaves preview',()=>{
  const source=fs.readFileSync('web/learning/workflow.js','utf8');
  const timer=source.split('\n').find(line=>line.includes('if(busy)workflowRefreshTimer='));
  let callback;const opens=[];
  const context=vm.createContext({busy:true,state:{page:'studio'},activeRun:'test',run:'test',studioTab:'preview',
    setTimeout:fn=>{callback=fn;return 1;},openDesignRun:(...args)=>opens.push(args)});
  vm.runInContext(timer,context);context.studioTab='trace';callback();assert.equal(opens.length,0);
  context.studioTab='preview';callback();assert.equal(opens.length,1);
  assert.equal(opens[0][1].activate,false);
});

test('switching sessions invalidates pending previews and clears old task controls',()=>{
  const source=fs.readFileSync('web/learning/app.js','utf8');
  const select=source.slice(source.indexOf('function selectAgentSession('),source.indexOf('async function loadAgentSessions('));
  const elements=new Map(),tabs=[],restored=[];
  const context=vm.createContext({agentEventSource:{close(){}},designRequestVersion:2,workflowRefreshTimer:1,
    composerDrafts:new Map(),agentSession:'old',agentPlan:{},activeRun:'old-run',lastAutoOpenedRun:'old-run',lastBrief:{},agentSending:false,
    localStorage:{setItem(){},removeItem(){}},clearTimeout(){},clearAgentReferences(){},renderAgentEvents(){},
    setStudioTab:tab=>tabs.push(tab),loadAgentSessions(){},restoreAgentSession:()=>restored.push(context.agentSession),
    taskStatusNames:{idle:'idle'},$:selector=>{if(!elements.has(selector))elements.set(selector,{style:{},scrollHeight:64,value:''});return elements.get(selector);}});
  vm.runInContext(select,context);vm.runInContext("selectAgentSession('new')",context);
  assert.equal(context.designRequestVersion,3);assert.equal(context.activeRun,null);assert.equal(context.lastBrief,null);
  assert.equal(elements.get('#agent-interrupt').hidden,true);assert.equal(elements.get('#agent-resume').hidden,true);
  assert.equal(elements.get('#design-workspace').innerHTML,'');assert.deepEqual(tabs,['chat']);assert.deepEqual(restored,['new']);
});
