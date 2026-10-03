// Optional local preview for development; the delivered HTML needs no server.
'use strict';
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'点击分布分析器.html'));
http.createServer((req,res)=>{if(req.url!=='/'&&req.url!=='/index.html'){res.writeHead(404);res.end();return;}res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(html);}).listen(8765,'127.0.0.1',()=>console.log('本地预览 http://127.0.0.1:8765'));
