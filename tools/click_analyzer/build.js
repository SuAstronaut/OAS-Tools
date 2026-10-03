'use strict';
const fs=require('node:fs'),path=require('node:path');
const here=__dirname;
let html=fs.readFileSync(path.join(here,'index.template.html'),'utf8');
for(const [marker,name] of [['STYLE','style.css'],['CORE','core.js'],['APP','app.js']])html=html.replace('/* '+marker+' */',()=>fs.readFileSync(path.join(here,name),'utf8'));
fs.writeFileSync(path.join(here,'点击分布分析器.html'),html,'utf8');
console.log('已生成可离线双击打开的 点击分布分析器.html');
