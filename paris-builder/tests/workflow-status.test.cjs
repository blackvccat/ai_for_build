const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync('web/learning/workflow.js','utf8');
const context=vm.createContext({stageLabels:{game:'游戏验收',tier3:'三级细化',tier2:'二级细化'}});
vm.runInContext(source.slice(source.indexOf('function workflowProgressMessage('),source.indexOf('let workflowRefreshTimer=')),context);

test('rollback explains the unresolved request and cannot reuse a previous revision pass',()=>{
  const data={status:{stage:'tier3',revision:73},job:{status:'done'},ready_for_review:false,
    latest_review:{stage:'tier3',revision:72,decision:'pass'},
    history:[{rollback_from:'game',to:'tier3',reason:'立面细节没运用调试棒手法'}]};
  assert.equal(context.workflowProgressMessage(data),'已从游戏验收退回三级细化。修改依据：立面细节没运用调试棒手法');
  data.history=[];
  assert.equal(context.workflowProgressMessage(data),'');
});

test('active and blocked jobs override old review status while a current pass remains usable',()=>{
  const data={status:{stage:'tier3',revision:73},job:{status:'running'},latest_review:{revision:72,decision:'pass'},history:[]};
  assert.match(context.workflowProgressMessage(data),/正在生成/);
  data.job={status:'failed',error:'视觉评审未通过'};data.status.awaiting='AGENT_BLOCKED_tier3';
  assert.equal(context.workflowProgressMessage(data),'视觉评审未通过');
  data.status.awaiting=null;data.latest_review.revision=73;
  assert.equal(context.workflowProgressMessage(data),'上一阶段评审已通过，可继续三级细化。');
});
