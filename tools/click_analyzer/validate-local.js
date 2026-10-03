// Read-only acceptance against the user's OAS logs. No OAS module is imported.
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),A=require('./core.js');
const crypto=require('node:crypto');
const dir=process.argv[2];if(!dir)throw new Error('请指定 OAS log 路径');
const names=fs.readdirSync(dir).filter(n=>/^2026-10-02_(?:小号[123]|模拟器|Desktop)\.txt$/.test(n));
const summaries=[];
for(const name of names){const bytes=fs.readFileSync(path.join(dir,name)),input=bytes.toString('utf8'),parsed=A.parse(input,name),stats=A.analyze(parsed.events);
  const reference=input.split(/\r?\n/).filter(l=>/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(l)&&/\|\s*(?:INFO|DEBUG|WARNING)\s*\|\s*Click\s*\(\s*\d+\s*,\s*\d+\s*\)/.test(l)).length;
  assert.equal(parsed.events.length,reference,'独立点击行计数应与解析器一致：'+name);
  assert(parsed.events.every(e=>e.timeMs!==null),'真实日志点击应保留有效时间');
  summaries.push({source:name,bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),clicks:parsed.events.length,referenceClicks:reference,valid:stats.total,outside:stats.outside.length,resolutionMismatch:stats.mismatch.length,unknownAccount:stats.valid.filter(e=>e.account===A.UNKNOWN).length,taskCount:new Set(stats.valid.map(e=>e.task)).size,accountCount:new Set(stats.valid.filter(e=>e.account!==A.UNKNOWN).map(e=>e.account)).size,repeatRatio:stats.repeatRatio,nearRatio:stats.nearRatio,top1:stats.top1,top5:stats.top5,hhi:stats.hhi,topRegions:stats.regions.slice(0,5),diagnostics:parsed.rejected.length});
}
assert(summaries.length>=3,'至少应验证三个真实日志文件');
const report={checkedAt:new Date().toISOString(),readOnly:true,method:'按时间前缀、日志级别和 Click 消息独立计数，比较解析器；只保存汇总，不复制原始日志或账号凭据',files:summaries};
fs.writeFileSync(path.join(__dirname,'真实日志验收.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
