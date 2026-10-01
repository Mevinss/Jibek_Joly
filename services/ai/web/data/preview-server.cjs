// Local frontend-only preview. API routes intentionally return 404.
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const web=path.resolve(__dirname,'..');
const types={'.html':'text/html;charset=utf-8','.css':'text/css;charset=utf-8',
  '.js':'text/javascript;charset=utf-8','.mjs':'text/javascript;charset=utf-8',
  '.json':'application/json','.geojson':'application/geo+json','.svg':'image/svg+xml',
  '.woff2':'font/woff2'};
http.createServer((request,response)=>{
  const url=new URL(request.url,'http://localhost');
  const pathname=decodeURIComponent(url.pathname);
  if(pathname==='/'||pathname==='/frontend'||pathname==='/frontend/'){
    response.writeHead(302,{Location:'/dispatch-dashboard.html?mode=MOCK'});
    response.end();return;
  }
  if(pathname==='/dispatch-dashboard.html'&&!url.searchParams.has('mode')){
    response.writeHead(302,{Location:'/dispatch-dashboard.html?mode=MOCK'});
    response.end();return;
  }
  const target=path.resolve(web,'.'+pathname);
  if(!target.startsWith(web+path.sep)){
    response.writeHead(403);response.end();return;
  }
  fs.readFile(target,(error,body)=>{
    if(error){response.writeHead(404);response.end('Not found');return;}
    response.writeHead(200,{'Content-Type':types[path.extname(target)]||'application/octet-stream'});
    response.end(body);
  });
}).listen(8765,'127.0.0.1',()=>process.stdout.write('Frontend preview: http://127.0.0.1:8765/dispatch-dashboard.html\n'));
