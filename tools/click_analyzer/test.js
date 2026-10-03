'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),A=require('./core.js');
const ev=(x,y,extra={})=>({x,y,source:'test',line:1,task:'task',account:'a',profile:'p',device:'d',session:1,timeMs:null,timeKind:'missing',...extra});
test('OAS coordinates, decimal precision, task boundary, source and filename profile',()=>{
  const p=A.parse('2026-10-02 09:00:00.001 | INFO | Scheduler: Start task `Courtyard`\n2026-10-02 09:00:01.010 | control.py:0204 | INFO | Click ( 12, 34.5) @ FIRE\n2026-10-02 09:00:02.000 | INFO | Scheduler: End task `Courtyard`\n09:00:03 click (1,2)','2026-10-02_小号1.txt');
  assert.equal(p.events.length,2);assert.equal(p.events[0].profile,'小号1');assert.equal(p.events[0].account,A.UNKNOWN);assert.equal(p.events[0].y,34.5);assert.equal(p.events[0].task,'Courtyard');assert.equal(p.events[0].line,2);assert.equal(p.events[1].task,A.UNKNOWN);
});
test('actual OAS STAT context attributes role and subtask without leaking account identifier',()=>{
  const p=A.parse('09:00:00 Start scheduler loop: 小号2\n09:00:01 Scheduler: Start task `MultiDailyAltAcc`\n09:00:02 [Screen_size] 1280x720\n09:00:03 [STAT] {"ev":"switch_start","acc":"private@example.test","char":"角色","svr":"区"}\n09:00:04 Click (100,200) @ LOGIN\n09:00:05 [STAT] {"ev":"acc_start","acc":"private@example.test","char":"角色","svr":"区"}\n09:00:06 [STAT] {"ev":"task_start","acc":"private@example.test","char":"角色","svr":"区","task":"courtyard"}\n09:00:07 Click (110,210) @ FIRE\n09:00:08 [STAT] {"ev":"task_end"}\n09:00:09 Click (120,220) @ BACK\n09:00:10 [STAT] {"ev":"acc_end"}\n09:00:11 Click (130,230) @ NEXT');
  assert.equal(p.events.length,4);assert.equal(p.events[0].account,A.UNKNOWN);assert.equal(p.events[1].task,'courtyard');assert.match(p.events[1].account,/角色 · 区/);assert(!p.events[1].account.includes('private'));assert.equal(p.events[2].task,'MultiDailyAltAcc');assert.equal(p.events[3].account,A.UNKNOWN);assert.equal(p.events[1].width,1280);
});
test('traceback, OCR, swipe and source code are not clicks',()=>{
  const p=A.parse('OCR (100,200)\nSwipe (100,200) -> (200,300)\n│ 48 │ Click (1,2)\nlogger.info("Click (1,2)")\nself.device.click(1,2)\n09:00:00 click (9,8)');assert.equal(p.events.length,1);
});
test('JSONL requires click event, reports failure and malformed coordinates',()=>{
  const p=A.parse('{"event":"click","x":1,"y":2,"time":"2026-10-02T09:00:00+08:00","account":"a"}\n{"event":"swipe","x":3,"y":4}\n{"event":"click","x":1,"y":2,"status":"failed"}\n{"event":"click","x":null,"y":2}\nCLICK_EVENT {oops}');
  assert.equal(p.events.length,1);assert.equal(p.rejected.length,3);assert.equal(p.events[0].timeMs,Date.parse('2026-10-02T01:00:00Z'));
});
test('CSV handles quoted commas and physical multiline record positions',()=>{
  const p=A.parse('x,y,task,account,time,button\r\n10,20,"庭院,任务",a,09:00:00,"two\nlines"\r\n11,21,t,b,09:00:01,FIRE');assert.equal(p.events.length,2);assert.equal(p.events[0].task,'庭院,任务');assert.equal(p.events[1].line,4);assert.throws(()=>A.parse('x,y\n"1,2'),/引号/);
});
test('exact/near repetition and HHI have hand-verifiable denominators',()=>{
  const s=A.analyze([ev(1,1),ev(1,1),ev(2,2),ev(90,90)],{width:100,height:100,cell:50,tolerance:2});
  assert.equal(s.repeatRatio,.25);assert.equal(s.nearRatio,.5);assert.equal(s.top1,.75);assert.equal(s.hhi,.625);assert.equal(s.longest,3);
});
test('account and profile are distinct repetition spaces',()=>{
  const s=A.analyze([ev(1,1),ev(1,1,{account:'b'}),ev(1,1,{profile:'q'})]);assert.equal(s.repeatRatio,0);assert.equal(s.nearRatio,0);
});
test('unknown account comparisons stay within source and session',()=>{
  const s=A.analyze([ev(1,1,{account:A.UNKNOWN}),ev(1,1,{account:A.UNKNOWN,session:2}),ev(1,1,{account:A.UNKNOWN,source:'second'})]);assert.equal(s.repeatRatio,0);assert.equal(s.nearRatio,0);
});
test('screen bounds and metadata mismatches are excluded, including width boundary',()=>{
  const s=A.analyze([ev(-1,1),ev(1280,1),ev(1,720),ev(2,2,{width:1920,height:1080}),ev(1279,719)]);assert.equal(s.total,1);assert.equal(s.outside.length,3);assert.equal(s.mismatch.length,1);assert.equal(s.regions[0].height,40);
});
test('empty data and short edge cells are valid',()=>{
  const s=A.analyze([ev(100,90)],{width:101,height:95,cell:40});assert.equal(s.regions[0].width,21);assert.equal(s.regions[0].height,15);assert.equal(A.analyze([]).hhi,0);
});
test('midnight is tracked across task sessions and small clock disorder sorts',()=>{
  const p=A.parse('23:59:59 click (1,1)\n00:00:00 Scheduler: Start task `New`\n00:00:01 click (2,2)\n00:00:00.500 click (3,3)');assert(p.events[1].timeMs>p.events[0].timeMs);assert.deepEqual(A.trajectories(p.events)[1].events.map(e=>e.x),[3,2]);
});
test('invalid date stays missing and missing time prevents invented time order',()=>{
  const p=A.parse('2026-02-30 09:00:00 click (1,1)\n25:00:00 click (2,2)\nclick (3,3)');assert(p.events.every(e=>e.timeMs===null));assert.equal(A.trajectories(p.events)[0].timed,false);
});
test('trajectory breaks across sources, accounts, tasks and sessions',()=>{
  assert.equal(A.trajectories([ev(1,1),ev(2,2,{source:'other'}),ev(3,3,{account:'b'}),ev(4,4,{task:'other'}),ev(5,5,{session:2})]).length,5);
});
test('CSV output protects formula fields and preserves data in ordinary round trip',()=>{
  const p=A.parse('x,y,time,task,account,button\n1,2,09:00:00,t,a,=HYPERLINK()');const csv=A.csv(p.events);assert(csv.includes("'=HYPERLINK()"));const again=A.parse(csv);assert.equal(again.events[0].x,1);assert.equal(again.events[0].task,'t');
});
test('dense near-repeat analysis scales to 20k duplicate events',()=>{
  const s=A.analyze(Array.from({length:20000},()=>ev(50,50)));assert.equal(s.total,20000);assert.equal(s.unique,1);assert.equal(s.nearRatio,19999/20000);
});
