const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync('web/learning/workflow.js','utf8');
const esc=value=>String(value??'').replaceAll('<','&lt;').replaceAll('>','&gt;');
const context=vm.createContext({esc,number:n=>Number(n||0).toLocaleString('en-US')});
vm.runInContext(source.slice(source.indexOf('function sourceStateEvidenceContent('),source.indexOf('let workflowRefreshTimer=')),context);

test('source summary uses audited methods and window coverage with pending game scope',()=>{
  const html=context.sourceStateEvidenceContent({status:'PASS',matched:16,declared:16,
    source_special_categories:{thin_door_window:12,single_arm_wall:2,shaped_stair:2},
    matched_ordinary_header_cells:2,stateful_inventory:{door:900,stair_shape:800},
    opening_coverage:[{opening_id:0,face:'street_north',storey:1,status:'PASS'},
                      {opening_id:1,face:'street_east',storey:1,status:'PASS'}],game_acceptance:'PENDING'});
  assert.match(html,/来源构法核对 · PASS/);
  assert.match(html,/2 \/ 2 扇窗通过/);
  assert.match(html,/门叶薄窗片 12 格 · 单臂墙肢 2 格 · 异形楼梯 2 格/);
  assert.match(html,/普通窗楣填充：2 格/);
  assert.match(html,/核对范围：北街与东街住宅窗/);
  assert.match(html,/游戏验收：PENDING/);
  assert.doesNotMatch(html,/900|800/);
});

test('missing report produces no badge and failed coverage stays visible and escaped',()=>{
  assert.equal(context.sourceStateEvidenceContent(null),'');
  const html=context.sourceStateEvidenceContent({status:'FAIL',matched:0,declared:1,
    source_special_categories:{},opening_coverage:[{opening_id:0,face:'street_east',storey:1,status:'FAIL',
      missing_categories:['single_arm_wall','<script>'],missing_thin_window_cells:1}]});
  assert.match(html,/0 \/ 1 扇窗通过/);
  assert.match(html,/待补齐：单臂墙肢、&lt;script&gt;/);
  assert.match(html,/薄窗片尚缺 1 格/);
  assert.match(html,/游戏验收：PENDING/);
  assert.doesNotMatch(html,/<script>/);
});
