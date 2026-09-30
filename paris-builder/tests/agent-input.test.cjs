const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function composerFixture(){
  const source=fs.readFileSync('web/learning/app.js','utf8');
  const elements=new Map();let submits=0;const messages=[];
  function element(selector){
    if(!elements.has(selector))elements.set(selector,{
      value:'',hidden:false,disabled:false,innerHTML:'',textContent:'',style:{},scrollHeight:64,
      removeAttribute(){},insertAdjacentHTML(){},contains(){return false;},
      classList:{add(){},remove(){}},requestSubmit(){submits++;}
    });
    return elements.get(selector);
  }
  const noop=()=>{};
  const context=vm.createContext({
    document:{querySelector:element},localStorage:{getItem:()=>null,removeItem:noop},
    URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL:noop},
    setInterval:noop,clearInterval:noop,toast:text=>messages.push(text),
    loadDesignHistory:noop,loadAgentSessions:noop,restoreAgentSession:noop,
    renderAgentEvents:noop,setStudioTab:noop,showBrief:noop,sendAgentTurn:noop,
    runBrief:noop,agentEventSource:null
  });
  const setup=source.slice(0,source.indexOf('const operationNames='));
  const studio=source.slice(source.indexOf('function studio()'),source.indexOf('function setStudioTab('));
  const resize=source.slice(source.indexOf('function resizeComposer('),source.indexOf('async function loadAgentSessions('));
  vm.runInContext(setup+'\n'+resize+'\n'+studio+'\nstudio();',context);
  return {context,element,messages,count:()=>submits};
}

test('Enter sends, Shift+Enter and IME confirmation do not send',()=>{
  const fixture=composerFixture();let prevented=0;
  const input=fixture.element('#agent-input');
  const event={key:'Enter',preventDefault(){prevented++;}};
  input.onkeydown({...event,shiftKey:true});
  input.onkeydown({...event,isComposing:true});
  input.onkeydown({...event,keyCode:229});
  assert.equal(fixture.count(),0);assert.equal(prevented,0);
  input.onkeydown(event);assert.equal(fixture.count(),1);assert.equal(prevented,1);
  fixture.element('#agent-form button[type=submit]').disabled=true;
  input.onkeydown(event);assert.equal(fixture.count(),1);
});

test('Dropped and pasted images share previews and attachment limits',()=>{
  const fixture=composerFixture();const image={name:'reference.png',size:100,type:'image/png'};
  let prevented=0;
  fixture.element('#agent-form').ondrop({preventDefault(){prevented++;},dataTransfer:{files:[image]}});
  assert.equal(prevented,1);
  assert.equal(vm.runInContext('pendingReferences.length',fixture.context),1);
  assert.match(fixture.element('#agent-reference-list').innerHTML,/reference.png/);
  assert.equal(fixture.element('#agent-reference-note').hidden,false);
  fixture.element('#agent-input').onpaste({preventDefault(){},clipboardData:{files:[image]}});
  assert.equal(vm.runInContext('pendingReferences.length',fixture.context),2);
  fixture.element('#agent-form').ondrop({preventDefault(){},dataTransfer:{files:[image]}});
  assert.equal(vm.runInContext('pendingReferences.length',fixture.context),2);
  assert.match(fixture.messages.at(-1),/2/);
  vm.runInContext('clearAgentReferences()',fixture.context);
  assert.equal(vm.runInContext('pendingReferences.length',fixture.context),0);
  assert.equal(fixture.element('#agent-reference-note').hidden,true);
});

test('Non-images and oversized files are rejected without altering attachments',()=>{
  const fixture=composerFixture();
  for(const file of [{name:'text.txt',size:10,type:'text/plain'},{name:'large.jpg',size:2000001,type:'image/jpeg'}]){
    fixture.element('#agent-form').ondrop({preventDefault(){},dataTransfer:{files:[file]}});
  }
  assert.equal(vm.runInContext('pendingReferences.length',fixture.context),0);
  assert.equal(fixture.messages.length,2);
});
