(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ClickAnalyzer = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  const UNKNOWN = '未记录';
  const number = v => v !== null && v !== undefined && String(v).trim() !== '' && Number.isFinite(Number(v)) ? Number(v) : null;
  const text = v => v == null || v === '' ? UNKNOWN : String(v);
  function fingerprint(s) {let h=2166136261;for(const c of String(s||'')){h^=c.charCodeAt(0);h=Math.imul(h,16777619);}return (h>>>0).toString(16).padStart(8,'0');}
  function parseCSV(input) {
    const rows = []; let row = [], cell = '', quoted = false, line = 1, start = 1;
    for (let i = 0; i < input.length; i++) {
      const c = input[i];
      if (c === '"') { if (quoted && input[i+1] === '"') {cell += '"'; i++;} else quoted = !quoted; }
      else if (c === ',' && !quoted) { row.push(cell); cell = ''; }
      else if (c === '\n' && !quoted) { row.push(cell.replace(/\r$/, '')); rows.push({cells:row,line:start}); row=[];cell='';start=line+1; }
      else cell += c;
      if (c === '\n') line++;
    }
    if (quoted) throw new Error('CSV 引号未闭合');
    if (cell || row.length) { row.push(cell.replace(/\r$/, '')); rows.push({cells:row,line:start}); }
    return rows;
  }
  function timeValue(value, clock) {
    if (value == null || value === '') return null;
    if (typeof value === 'number') return null; // Numeric timestamps need an explicit unit; never guess.
    const s = String(value).trim();
    const full = s.match(/^(\d{4})[-/](\d{2})[-/](\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?(Z|[+-]\d{2}:?\d{2})?$/);
    const simple = s.match(/^(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?$/);
    const m = full ? full.slice(4,8) : simple ? simple.slice(1,5) : null;
    if (!m || +m[0]>23 || +m[1]>59 || +m[2]>59) return null;
    const ms = ((+m[0]*60 + +m[1])*60 + +m[2])*1000 + +(m[3] || '').padEnd(3,'0');
    if (full) {
      const y=+full[1],mo=+full[2]-1,d=+full[3];
      const date=new Date(Date.UTC(y,mo,d));
      if (date.getUTCFullYear()!==y || date.getUTCMonth()!==mo || date.getUTCDate()!==d) return null;
      let result=Date.UTC(y,mo,d)+ms;
      if (full[8] && full[8]!=='Z') {
        const z=full[8].replace(':',''); const h=+z.slice(1,3),min=+z.slice(3,5);
        if(h>23||min>59)return null;
        result-=(z[0]==='+'?1:-1)*(h*60+min)*60000;
      }
      return result;
    }
    // A fall of >12h is treated as midnight; smaller falls are sortable disorder.
    if (clock.last != null && clock.last-ms>43200000) clock.day++;
    clock.last=ms;
    return ms+clock.day*86400000;
  }
  function parse(input, source='粘贴日志') {
    input=String(input).replace(/^\uFEFF/,'').replace(/\x1b\[[0-9;]*m/g,'');
    const events=[], rejected=[], clocks=new Map(); let ignored=0, candidates=0;
    let account=UNKNOWN,task=UNKNOWN,session=0,profile=UNKNOWN,schedulerTask=UNKNOWN,screenWidth=null,screenHeight=null;
    // OAS's filename contains the profile name, which is not necessarily a game account.
    const fileProfile=source.match(/^\d{4}-\d{2}-\d{2}_(.+)\.(?:txt|log)$/i)?.[1];
    if(fileProfile)profile=fileProfile;
    function add(obj, line, raw, format) {
      candidates++;
      const x=number(obj.x),y=number(obj.y);
      if(x===null||y===null){rejected.push({source,line,reason:'坐标缺失或非有限数值',raw});return;}
      const w=number(obj.width),h=number(obj.height);
      const ev={x,y,time:obj.time == null ? '' : String(obj.time),task:text(obj.task),account:text(obj.account),profile:text(obj.profile||profile),button:text(obj.button),source,line,raw,format,
        width:w>0?w:null,height:h>0?h:null,status:obj.status||'attempted',session:obj.session??session,device:text(obj.device)};
      const key=JSON.stringify([ev.profile,ev.account,ev.device]);
      if(!clocks.has(key))clocks.set(key,{day:0,last:null});
      ev.timeMs=timeValue(obj.time,clocks.get(key)); ev.timeKind=ev.timeMs===null?'missing':/^\d{4}[-/]/.test(ev.time)?'dated':'clock';
      if(!['attempted','sent'].includes(ev.status)){rejected.push({source,line,reason:'未发送点击：'+ev.status,raw});return;}
      events.push(ev);
    }
    const lines=input.split(/\r?\n/);
    const first=lines.find(l=>l.trim())||'';
    const csvHeader=first.toLowerCase().replace(/"/g,'').split(',').map(v=>v.trim());
    if(csvHeader.includes('x')&&csvHeader.includes('y')) {
      const rows=parseCSV(input); const head=rows.shift().cells.map(v=>v.trim().toLowerCase());
      for(const row of rows) {
        if(row.cells.every(v=>!v.trim()))continue;
        const o=Object.fromEntries(head.map((h,i)=>[h,row.cells[i]]));
        if(o.event && !/^(click|tap|点击)$/i.test(o.event)){ignored++;continue;}
        add({ ...o, time:o.time||o.timestamp,task:o.task,account:o.account,button:o.button||o.target },row.line,row.cells.join(','),'CSV');
      }
      return {events,rejected,ignored,candidates,lines:lines.length,source};
    }
    for(let i=0;i<lines.length;i++) {
      const raw=lines[i],s=raw.trim(); if(!s)continue;
      if(s.includes('[STAT]')) {
        const at=s.indexOf('{');let stat;
        try{stat=JSON.parse(s.slice(at));}catch{rejected.push({source,line:i+1,reason:'STAT JSON 格式错误',raw});continue;}
        const label=[stat.char||UNKNOWN,stat.svr||UNKNOWN].join(' · ')+' ['+fingerprint(stat.acc)+']';
        if(stat.ev==='switch_start'){account=UNKNOWN;task='账号切换（归属未确认）';session++;}
        if((stat.ev==='switch'&&stat.ok===true)||stat.ev==='acc_start'){account=label;task=schedulerTask;session++;}
        if(stat.ev==='task_start'){account=label;task=stat.task||UNKNOWN;session++;}
        if(stat.ev==='task_end'){task=schedulerTask;session++;}
        if(stat.ev==='acc_end'){account=UNKNOWN;task=schedulerTask;session++;}
        ignored++;continue;
      }
      const size=s.match(/\[Screen_size\]\s*(\d+)\s*[x×]\s*(\d+)/i);
      if(size){screenWidth=+size[1];screenHeight=+size[2];}
      const jsonStart=s.indexOf('{');
      if(jsonStart>=0 && (jsonStart===0||s.includes('CLICK_EVENT'))) {
        let o;try{o=JSON.parse(s.slice(jsonStart));}catch{rejected.push({source,line:i+1,reason:'JSON 格式错误',raw});continue;}
        if(!/^(click|tap|点击)$/i.test(o.event||o.type||'')){ignored++;continue;}
        add({...o,time:o.time||o.timestamp,account:o.account||account,task:o.task||task,button:o.button||o.target},i+1,raw,'JSONL');continue;
      }
      const start=s.match(/Scheduler:\s*Start task\s*[`'"]?([^`'"\s|]+)/i);
      const end=/Scheduler:\s*End task/i.test(s);
      const acc=s.match(/Start scheduler loop:\s*([^\s|]+)/i)||s.match(/\[(?:Account|账号)\]\s*(.+?)(?:\s*[|│]|$)/i);
      if(acc){if(/Start scheduler/i.test(s)){profile=acc[1];account=UNKNOWN;}else account=acc[1];task=UNKNOWN;schedulerTask=UNKNOWN;session++;}
      if(start){task=start[1];schedulerTask=task;session++;} if(end){task=UNKNOWN;schedulerTask=UNKNOWN;session++;}
      const m=s.match(/\b(?:click|tap)\s*\(\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*\)(?:\s*@\s*(.*))?/i)||s.match(/点击(?:坐标)?\s*[(:：\[]\s*([+-]?\d+(?:\.\d+)?)\s*[,，]\s*([+-]?\d+(?:\.\d+)?)/);
      // Source-code/traceback lines and arbitrary x/y pairs are not click records.
      if(m && !/^\s*(?:[│|╭╰]|\d+\s*[│|])/.test(raw) && !/logger\.|self\.|def\s+|['"]Click/.test(s)) {
        const t=s.match(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?(?:Z|[+-]\d{2}:?\d{2})?/)||s.match(/\b\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?/);
        add({x:m[1],y:m[2],time:t?.[0],task,account,width:screenWidth,height:screenHeight,button:m[3]?.replace(/\s+\d+(?:\.\d+)?\s*$/,'').trim()},i+1,raw,'OAS/text');
      } else {if(/\b(?:click|tap)\s*\(|点击坐标/i.test(s)&&!s.includes('self.')&&!s.includes('logger.'))rejected.push({source,line:i+1,reason:'点击行无法识别坐标',raw});else ignored++;}
    }
    return {events,rejected,ignored,candidates,lines:lines.length,source};
  }
  function analyze(events,{width=1280,height=720,cell=40,tolerance=2}={}) {
    if(![width,height,cell].every(v=>Number.isFinite(v)&&v>0)||!Number.isFinite(tolerance)||tolerance<0)throw new Error('画面尺寸、网格和容差无效');
    const valid=[],outside=[],mismatch=[];
    for(const e of events){if((e.width&&e.width!==width)||(e.height&&e.height!==height))mismatch.push(e);else if(e.x<0||e.y<0||e.x>=width||e.y>=height)outside.push(e);else valid.push(e);}
    const regions=new Map(),coords=new Set(),buckets=new Map();let near=0,longest=0,run=0,last='';
    const span=Math.max(tolerance,1);
    for(const e of valid) {
      const rx=Math.floor(e.x/cell),ry=Math.floor(e.y/cell),key=rx+','+ry;
      if(!regions.has(key))regions.set(key,{key,x:rx*cell,y:ry*cell,width:Math.min(cell,width-rx*cell),height:Math.min(cell,height-ry*cell),count:0});regions.get(key).count++;
      // Unknown account identities cannot safely be compared across sessions/files.
      const group=JSON.stringify([e.profile,e.account,e.device,e.account===UNKNOWN?[e.source,e.session]:null]);const ck=group+':'+e.x+','+e.y;
      const bx=Math.floor(e.x/span),by=Math.floor(e.y/span);let repeat=false;
      for(let dx=-1;dx<=1&&!repeat;dx++)for(let dy=-1;dy<=1&&!repeat;dy++)for(const p of buckets.get(group+':'+(bx+dx)+','+(by+dy))||[])if(Math.abs(p.x-e.x)<=tolerance&&Math.abs(p.y-e.y)<=tolerance){repeat=true;break;}
      if(repeat)near++;
      if(!coords.has(ck)){const bk=group+':'+bx+','+by;if(!buckets.has(bk))buckets.set(bk,[]);buckets.get(bk).push(e);}coords.add(ck);
      const rk=JSON.stringify([e.source,e.profile,e.account,e.device,e.task,e.session,key]);run=rk===last?run+1:1;last=rk;longest=Math.max(longest,run);
    }
    const n=valid.length,ranked=[...regions.values()].sort((a,b)=>b.count-a.count||a.y-b.y||a.x-b.x);
    for(const r of ranked)r.share=n?r.count/n:0;
    const hhi=ranked.reduce((s,r)=>s+r.share*r.share,0);
    return {valid,outside,mismatch,total:n,unique:coords.size,repeatRatio:n?(n-coords.size)/n:0,nearRatio:n?near/n:0,
      top1:ranked[0]?.share||0,top5:ranked.slice(0,5).reduce((s,r)=>s+r.share,0),hhi,effectiveRegions:hhi?1/hhi:0,longest,regions:ranked};
  }
  function trajectories(events) {
    const groups=new Map();
    for(const e of events){const k=JSON.stringify([e.source,e.profile,e.account,e.device,e.task,e.session,e.width,e.height]);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(e);}
    return [...groups.values()].map(items=>{
      const kinds=new Set(items.map(e=>e.timeKind));const timed=kinds.size===1&&!kinds.has('missing');
      return {timed,events:timed?items.slice().sort((a,b)=>a.timeMs-b.timeMs||a.line-b.line):items.slice().sort((a,b)=>a.line-b.line)};
    });
  }
  function csv(events) {
    const cols=['source','line','time','x','y','task','account','profile','device','button','status','session','width','height'];
    // Prevent spreadsheet formula evaluation when a log field starts with a formula marker.
    const quote=v=>'"'+String(v??'').replace(/^\s*[=+@-]/,"'$&").replace(/"/g,'""')+'"';
    return '\uFEFF'+cols.join(',')+'\r\n'+events.map(e=>cols.map(k=>quote(e[k])).join(',')).join('\r\n');
  }
  return {parse,analyze,trajectories,csv,parseCSV,UNKNOWN};
});
