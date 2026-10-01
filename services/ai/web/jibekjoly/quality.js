export const defaultConfig={weights:[30,15,20,20,15],normal:80,critical:50,priorities:[3,2,1]};
let activeConfig=defaultConfig;
export const getQualityConfig=()=>activeConfig;
export const setQualityConfig=c=>{activeConfig=c;};
export function validateConfig(c){if(!c||!Array.isArray(c.weights)||c.weights.length!==5||c.weights.some(x=>!Number.isFinite(x)||x<0||x>100)||c.weights.reduce((a,b)=>a+b,0)<=0||!Number.isFinite(c.normal)||!Number.isFinite(c.critical)||c.critical<0||c.normal>100||c.critical>=c.normal||!Array.isArray(c.priorities)||c.priorities.length!==3||c.priorities.some(x=>!Number.isFinite(x)||x<1||x>10))throw Error('Invalid configuration');return c;}
export function quality(w,c=w.config||activeConfig){
 const ts=w.trains,n=ts.length||1,clamp=x=>Math.max(0,Math.min(100,x));
 const punctuality=clamp(100-ts.reduce((s,t)=>s+t.delay,0)/n*3);
 const demand=ts.filter(t=>t.finished===null&&w.time>=(t.releaseAt||0));
 // Planned waits are included in the fixed schedule; only unplanned queues reduce flow.
 const capacity=demand.length?clamp(100-demand.filter(t=>['queue','blocked','held'].includes(t.state)&&t.delay>.2).length/demand.length*100):100;
 const compliance=clamp(100-ts.reduce((s,t)=>s+(t.signalViolations||0),0)*25);
 let conflicting=0;if(w.mode!=='wave')for(const b of w.blocks){const q=demand.filter(t=>t.segment===null&&(t.dir===1?t.node:t.node-1)===b.i);if(q.length>1&&q.some(t=>t.dir!==q[0].dir))conflicting++;}
 const conflicts=clamp(100-conflicting*25),arrived=ts.filter(t=>t.finished!==null);
 const accuracy=arrived.length?clamp(100-arrived.reduce((s,t)=>s+Math.max(0,Math.abs(t.finished-t.plan)-.2),0)/arrived.length*4):punctuality;
 const factors=[punctuality,capacity,compliance,conflicts,accuracy],sum=c.weights.reduce((a,b)=>a+b,0);
 const index=Math.round(factors.reduce((a,b,i)=>a+b*c.weights[i],0)/sum);
 return {index,factors:factors.map(Math.round),level:index>=c.normal?'good':index<c.critical?'bad':'warn',energy:ts.reduce((s,t)=>s+(t.energy||0),0),reference:ts.reduce((s,t)=>s+(t.distance_work||0)*(t.massTons||1000)/1000,0),conflicting};
}
