'use strict';
const $=id=>document.getElementById(id), A=ClickAnalyzer;
let all=[],parsed=[],current=null,mode='scatter',page=0,region=null,options=null,activeFilters={};
const pct=n=>(n*100).toFixed(1)+'%', escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={task:'全部任务',account:'全部账号',profile:'全部配置',device:'全部设备'};
function load(sources) {
  parsed=sources.map(s=>A.parse(s.text,s.name));all=parsed.flatMap(p=>p.events);page=0;region=null;
  for(const key of Object.keys(names)) {
    $(key).replaceChildren(new Option(names[key],''));
    [...new Set(all.map(e=>e[key]))].sort().forEach(v=>$(key).add(new Option(v,v)));
  }
  const sizes=[...new Set(all.filter(e=>e.width&&e.height).map(e=>e.width+'x'+e.height))];
  if(sizes.length===1){const [w,h]=sizes[0].split('x');$('width').value=w;$('height').value=h;}
  $('from').value='';$('to').value='';
  const rejected=parsed.flatMap(p=>p.rejected),ignored=parsed.reduce((s,p)=>s+p.ignored,0);
  $('status').textContent=`已读取 ${sources.length} 个文件 · 提取 ${all.length.toLocaleString()} 次点击 · 忽略 ${ignored.toLocaleString()} 行非点击内容 · ${rejected.length} 条诊断记录`+(all.length?'':'。未找到坐标，请检查日志或参照 README 中的最小埋点方案。');
  $('rejectTitle').textContent=`解析诊断（${rejected.length} 条）`;
  $('rejects').textContent=rejected.slice(0,100).map(r=>`${r.source}:${r.line} ${r.reason}\n${r.raw}`).join('\n\n')||'未发现解析错误。非点击内容已跳过。';
  apply();
}
function bounds(value, end=false) {
  if(!value.trim())return null;
  const s=value.trim().replace('T',' '),date=/^\d{4}-\d{2}-\d{2} /.test(s),m=s.match(/^(?:\d{4}-\d{2}-\d{2} )?(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$/);
  if(!m||+m[1]>23||+m[2]>59||+m[3]>59)throw new Error('时间请填写 HH:mm:ss 或 YYYY-MM-DD HH:mm:ss，可带毫秒');
  const ms=((+m[1]*60 + +m[2])*60 + +m[3])*1000 + +(m[4]||'').padEnd(3,'0');
  const d=date?Date.parse(s.slice(0,10)+'T00:00:00Z'):0;
  if(!Number.isFinite(d)||(date&&new Date(d).toISOString().slice(0,10)!==s.slice(0,10)))throw new Error('日期无效');
  return {dated:date,ms:d+ms+(end&&!m[4]?999:0)};
}
function apply() {
  try {
    for(const id of ['width','height','cell','tol'])if(!$(id).checkValidity())throw new Error('请检查画面尺寸、网格大小和容差的范围');
    const nextOptions={width:+$('width').value,height:+$('height').value,cell:+$('cell').value,tolerance:+$('tol').value};
    const from=bounds($('from').value),to=bounds($('to').value,true);
    if(from&&to&&from.dated!==to.dated)throw new Error('开始和结束时间需要使用相同格式');
    if(from&&to&&from.dated&&from.ms>to.ms)throw new Error('开始时间不能晚于结束时间');
    const filtered=all.filter(e=>Object.keys(names).every(k=>!$(k).value||e[k]===$(k).value)).filter(e=>{
      if(!from&&!to)return true;if(e.timeMs===null)return false;
      const dated=from?.dated??to.dated;if(dated&&e.timeKind!=='dated')return false;
      const t=dated?e.timeMs:clockMs(e.time);
      if(t===null)return false;
      if(from&&to&&!dated&&from.ms>to.ms)return t>=from.ms||t<=to.ms;
      return (!from||t>=from.ms)&&(!to||t<=to.ms);
    });
    const next=A.analyze(filtered,nextOptions);current=next;options=nextOptions;activeFilters=Object.fromEntries([...Object.keys(names),'from','to'].map(k=>[k,$(k).value]));region=null;page=0;
    const metrics=[['有效点击',current.total.toLocaleString(),'当前筛选 · 画面范围内'],['重复坐标',pct(current.repeatRatio),`${current.unique.toLocaleString()} 个账号/设备内唯一坐标`],['近似重复',pct(current.nearRatio),`X、Y 都在 ±${options.tolerance}px 内`],['最高频区域',pct(current.top1),`${options.cell}px 网格 · 前5区 ${pct(current.top5)}`],['区域集中度 HHI',current.hhi.toFixed(3),`等效区域数 ${current.effectiveRegions.toFixed(1)}`],['同区连续点击',String(current.longest),'按导入行序 · 会话内最长连续次数']];
    $('metrics').innerHTML=metrics.map(m=>`<div class="metric"><small>${escape(m[0])}</small><strong>${escape(m[1])}</strong><span>${escape(m[2])}</span></div>`).join('');
    const missing=current.valid.filter(e=>e.timeMs===null).length,unknown=current.valid.filter(e=>e.account===A.UNKNOWN).length;
    $('notice').textContent=`坐标空间 ${options.width} × ${options.height}（左上角为原点）。已排除 ${current.outside.length} 次越界点击、${current.mismatch.length} 次尺寸不一致点击。${current.valid.some(e=>!e.width||!e.height)?'部分记录未标尺寸，按当前手工尺寸分析。 ':''}${unknown?`${unknown} 次点击的实际账号归属未记录。 `:''}${missing?`${missing} 次点击缺少有效时间，轨迹使用原始行序。 `:''}多文件不会自动去重，请勿同时导入日常日志和它的错误日志副本。`;
    $('regions').innerHTML=current.regions.slice(0,15).map((r,i)=>`<tr data-region="${escape(r.key)}"><td>${String(i+1).padStart(2,'0')}</td><td>[${r.x}, ${r.x+r.width}) × [${r.y}, ${r.y+r.height})</td><td>${r.count}</td><td>${pct(r.share)}</td></tr>`).join('')||'<tr><td colspan="4">没有可分析的点击</td></tr>';
    $('regions').querySelectorAll('tr[data-region]').forEach(tr=>tr.onclick=()=>{region=tr.dataset.region;page=0;records();draw();});
    records();draw();
  }catch(e){$('status').textContent='无法分析：'+e.message;}
}
function clockMs(s){const m=String(s).match(/(?:^|[T ])(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?/);return m?((+m[1]*60 + +m[2])*60 + +m[3])*1000 + +(m[4]||'').padEnd(3,'0'):null;}
function displayed(){return (current?.valid||[]).filter(e=>!region||Math.floor(e.x/options.cell)+','+Math.floor(e.y/options.cell)===region);}
function records(){const list=displayed(),pages=Math.max(1,Math.ceil(list.length/50));page=Math.max(0,Math.min(page,pages-1));
  $('records').innerHTML=list.slice(page*50,(page+1)*50).map(e=>`<tr><td>${escape(e.source)}:${e.line}</td><td>${escape(e.time||'未记录')}</td><td>(${e.x}, ${e.y})</td><td>${escape(e.task)}<br>${escape(e.account)}<br><small>配置：${escape(e.profile)}</small></td><td>${escape(e.button)}</td><td>${escape(e.raw)}</td></tr>`).join('')||'<tr><td colspan="6">没有记录</td></tr>';
  $('recordCaption').textContent=`${list.length.toLocaleString()} 条${region?' · 区域 '+region:''}。每页 50 条；CSV 导出包含当前任务/账号/时间筛选及区域筛选。`;
  $('page').textContent=`${page+1} / ${pages}`;$('prev').disabled=page===0;$('next').disabled=page>=pages-1;$('clearRegion').hidden=!region;
}
function draw(){if(!current)return;const c=$('map');c.width=options.width;c.height=options.height;const ctx=c.getContext('2d'),w=c.width,h=c.height;
  ctx.fillStyle='#000';ctx.fillRect(0,0,w,h);ctx.lineWidth=1;ctx.strokeStyle='#17212c';
  const grid=Math.max(options.cell,40);
  for(let x=grid;x<w;x+=grid){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}for(let y=grid;y<h;y+=grid){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  if(mode==='heat'){
    const max=current.regions[0]?.count||1;
    for(const r of current.regions){const v=Math.log1p(r.count)/Math.log1p(max);ctx.fillStyle=`hsla(${40*(1-v)},100%,${20+v*35}%,${.25+v*.7})`;ctx.fillRect(r.x,r.y,r.width,r.height);if(r.width>=32&&r.height>=24){ctx.fillStyle='#fff';ctx.font='12px Segoe UI';ctx.fillText(r.count,r.x+5,r.y+16);}}
  }else if(mode==='path'){
    for(const group of A.trajectories(current.valid)){const list=group.events;for(let i=0;i<list.length;i++){const e=list[i],f=list.length>1?i/(list.length-1):1;ctx.fillStyle=ctx.strokeStyle=`hsla(${185*(1-f)},90%,60%,.65)`;ctx.lineWidth=1.2;
      if(i){const p=list[i-1];ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(e.x,e.y);ctx.stroke();}
      ctx.beginPath();ctx.arc(e.x,e.y,2.5,0,Math.PI*2);ctx.fill();}
    }
  }else{ctx.fillStyle='rgba(255,58,76,.65)';for(const e of current.valid){ctx.beginPath();ctx.arc(e.x,e.y,2.5,0,Math.PI*2);ctx.fill();}}
  if(region){const r=current.regions.find(r=>r.key===region);if(r){ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.strokeRect(r.x+1,r.y+1,r.width-2,r.height-2);}}
  ctx.fillStyle='#7c8796';ctx.font='12px Segoe UI';ctx.fillText(`0,0   /   ${w} × ${h}`,10,h-10);
  if(!current.total){ctx.fillStyle='#7c8796';ctx.font='20px Microsoft YaHei';ctx.textAlign='center';ctx.fillText('导入日志后显示点击分布',w/2,h/2);}
  $('legend').textContent=mode==='heat'?'暗红 → 黄色 = 网格点击次数（对数色阶）':mode==='path'?'青色 → 红色 = 各会话内从早到晚；无时间按行序':'● 红点 = 点击位置';
  $('chartCaption').textContent=`${current.total.toLocaleString()} 次点击 · ${current.regions.length} 个有点击的网格 · ${mode==='path'?A.trajectories(current.valid).length+' 条独立会话轨迹':'同一画面坐标空间'}`;
}
function download(blob,name){const link=document.createElement('a'),url=URL.createObjectURL(blob);link.href=url;link.download=name;link.hidden=true;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
$('files').onchange=async()=>{const files=[...$('files').files];if(!files.length)return;$('status').textContent='正在读取并解析…';
  try{if(files.reduce((n,f)=>n+f.size,0)>64*1024*1024)throw new Error('一次最多读取 64 MB，请分批分析');const sources=[];for(const f of files){const bytes=await f.arrayBuffer();sources.push({name:f.name,text:new TextDecoder($('encoding').value,{fatal:true}).decode(bytes)});}load(sources);}catch(e){$('status').textContent='导入失败：'+e.message+'。如为旧版中文编码，请选择 GB18030 / GBK 后重新选文件。';}finally{$('files').value='';}};
$('parse').onclick=()=>{try{load([{name:'粘贴日志',text:$('paste').value}]);}catch(e){$('status').textContent='解析失败：'+e.message;}};
$('apply').onclick=apply;for(const id of Object.keys(names))$(id).onchange=apply;
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;document.querySelectorAll('[data-mode]').forEach(n=>n.classList.toggle('active',n===b));draw();});
$('prev').onclick=()=>{page--;records();};$('next').onclick=()=>{page++;records();};$('clearRegion').onclick=()=>{region=null;page=0;records();draw();};
$('map').onmousemove=e=>{if(!current)return;const r=$('map').getBoundingClientRect(),x=Math.floor((e.clientX-r.left)*options.width/r.width),y=Math.floor((e.clientY-r.top)*options.height/r.height),key=Math.floor(x/options.cell)+','+Math.floor(y/options.cell),bin=current.regions.find(b=>b.key===key);$('hover').textContent=`(${x}, ${y}) · 网格 ${bin?.count||0} 次点击 · 点击此处筛选记录`;};
$('map').onclick=e=>{if(!current)return;const r=$('map').getBoundingClientRect(),x=(e.clientX-r.left)*options.width/r.width,y=(e.clientY-r.top)*options.height/r.height;region=Math.floor(x/options.cell)+','+Math.floor(y/options.cell);page=0;records();draw();};
$('png').onclick=()=>{if(current)$('map').toBlob(blob=>{if(blob)download(blob,`点击分布-${mode}.png`);},'image/png');};
$('csv').onclick=()=>download(new Blob([A.csv(displayed())],{type:'text/csv;charset=utf-8'}),'点击记录.csv');
$('report').onclick=()=>{if(!current)return;const {valid,outside,mismatch,...stats}=current;const report={schemaVersion:1,generatedAt:new Date().toISOString(),options,filters:activeFilters,stats,excluded:{outside:outside.length,resolutionMismatch:mismatch.length},sources:parsed.map(p=>({name:p.source,clicks:p.events.length,diagnostics:p.rejected.length})),definitions:{repeat:'同配置/账号/设备内，首次之后完全重复的次数 / 有效点击数；未知账号仅在同文件会话内比较',near:'与此前某点的 X/Y 距离均不超过容差；非聚类占比',heat:'矩形网格计数；对数色阶',hhi:'sum((grid_count / total)^2)'},regionFilter:region};download(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),'点击统计报告.json');};
$('demo').onclick=()=>{const lines=['2026-10-02 09:00:00.000 | INFO | Start scheduler loop: 演示配置','2026-10-02 09:00:00.001 | INFO | [Screen_size] 1280x720','2026-10-02 09:00:00.010 | INFO | Scheduler: Start task `MultiDailyAltAcc`','2026-10-02 09:00:00.020 | INFO | [STAT] {"ev":"acc_start","acc":"demo","char":"演示角色","svr":"演示区"}','2026-10-02 09:00:00.030 | INFO | [STAT] {"ev":"task_start","acc":"demo","char":"演示角色","svr":"演示区","task":"courtyard"}'];
  for(let i=0;i<240;i++){const x=i<100?1112+(i%8):i<160?650+(i%9):150+((i*73)%900),y=i<100?630+(i%6):i<160?370+(i%7):100+((i*37)%450);lines.push(`2026-10-02 09:${String(Math.floor(i/60)).padStart(2,'0')}:${String(i%60).padStart(2,'0')}.100 | control.py:0204 | INFO | Click (${x}, ${y}) @ DEMO_BUTTON`);}load([{name:'演示数据.txt',text:lines.join('\n')}]);};
apply();
