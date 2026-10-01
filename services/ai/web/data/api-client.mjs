export async function requestJson(path, {method='GET',body,timeoutMs=12000,signal}={}) {
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  const abort=()=>controller.abort();
  signal?.addEventListener('abort',abort,{once:true});
  try {
    const response=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},
      body:body?JSON.stringify(body):undefined,signal:controller.signal,cache:'no-store'});
    if(!response.ok) throw Error(`HTTP ${response.status}: ${path}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort',abort);
  }
}
