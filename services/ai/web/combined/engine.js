import {bi,tr} from './locales.js';
export const fleet=[
{id:'SIM-TAL-021',type:bi('ref230'),weight:3,people:320,color:'#28c9b5'},
{id:'SIM-PAS-043',type:bi('ref231'),weight:2,people:480,color:'#619eff'},
{id:'SIM-REG-705',type:bi('ref232'),weight:1.5,people:180,color:'#b299ff'},
{id:'SIM-FRT-208',type:bi('ref233'),weight:1,people:0,color:'#f4b34e'}];
export const scenarios=[
{title:bi('ref234'),tag:bi('ref235'),station:'astana1',description:bi('ref236'),closed:12,release:[0,3,5,0],duration:[4,6,4,12],primary:[0,0,0,0],orders:[[3,1,2,0],[0,2,1,3]],options:[bi('ref237'),bi('ref238')],reason:bi('ref239')},
{title:bi('ref240'),tag:bi('ref241'),station:'nurly',description:bi('ref242'),closed:0,release:[0,5,2,0],duration:[4,5,4,10],primary:[8,0,0,0],orders:[[1,2,3,0],[0,1,2,3]],connection:true,options:[bi('ref243'),bi('ref244')],reason:bi('ref245')},
{title:bi('ref246'),tag:bi('ref247'),station:'almaty1',description:bi('ref248'),closed:0,release:[3,0,5,0],duration:[6,6,6,14],primary:[0,0,0,0],orders:[[3,1,0,2],[1,0,2,3]],options:[bi('ref249'),bi('ref250')],reason:bi('ref251')},
{title:bi('ref252'),tag:bi('ref253'),station:'almaty2',description:bi('ref254'),closed:0,release:[0,4,2,0],duration:[4,6,4,12],primary:[0,0,0,0],deadline:55,orders:[[0,1,2,3],[3,0,2,1]],options:[bi('ref255'),bi('ref256')],reason:bi('ref257')}];
export function simulate(index,choice,previous=[0,0,0,0]){
 const s=scenarios[index];let free=s.closed;const rows=[];
 for(const i of s.orders[choice]){let ready=s.release[i]+previous[i]+s.primary[i];
 if(s.connection&&choice===1&&i===1){const feeder=rows.find(r=>r.i===0);if(feeder)ready=Math.max(ready,feeder.end+5);}
 const start=Math.max(ready,free),end=start+s.duration[i],planned=s.release[i]+s.duration[i];
 rows.push({i,id:fleet[i].id,ready,start,end,planned,delay:Math.max(0,end-planned),wait:Math.max(0,start-(s.release[i]+previous[i]+s.primary[i])),duration:s.duration[i]});free=end+2;}
 rows.sort((a,b)=>a.i-b.i);const delays=rows.map(r=>r.delay),weighted=rows.reduce((n,r)=>n+r.delay*fleet[r.i].weight,0);
 const missed=s.connection&&rows[1].start<rows[0].end+5?60:0;const freightLate=s.deadline?Math.max(0,rows[3].end-s.deadline):0;
 const cost=weighted+missed*45/60+freightLate*4;const quality=Math.max(0,Math.round(100-cost/6));
 const passengerMinutes=rows.reduce((n,r)=>n+r.delay*fleet[r.i].people,0)+missed*45;
 const curve=Array.from({length:Math.ceil(free)+1},(_,t)=>rows.reduce((n,r)=>n+Math.max(0,Math.min(t,r.end)-Math.min(t,r.planned))*fleet[r.i].weight,0));
 return {rows,delays,weighted,cost,quality,missed,freightLate,passengerMinutes,finish:free-2,curve,choice};
}
export function playSequence(choices){let delays=[0,0,0,0],results=[];choices.forEach((c,i)=>{const r=simulate(i,c,delays);results.push(r);delays=r.delays;});return {results,delays,cost:results.reduce((n,r)=>n+r.cost,0)};}
export function bestSequence(){let best=null;for(let n=0;n<16;n++){const choices=[0,1,2,3].map(i=>(n>>i)&1),r=playSequence(choices);if(!best||r.cost<best.cost)best={...r,choices};}return best;}
export const cities=[{id:'kokshetau',name:'Көкшетау',coord:[53.286,69.405]},{id:'astana',name:'Астана',coord:[51.157,71.465]},{id:'almaty',name:'Алматы',coord:[43.29,76.94]}];
export const stations=[
{id:'kok1',city:'kokshetau',name:'Көкшетау-1',coord:[53.2886,69.4222],tracks:4},
{id:'kok2',city:'kokshetau',name:'Көкшетау-2',coord:[53.3597,69.4914],tracks:5},
{id:'astana1',city:'astana',name:'Астана-1',coord:[51.1957,71.4091],tracks:6},
{id:'nurly',city:'astana',name:'Астана Нұрлы жол',coord:[51.1124,71.5318],tracks:6},
{id:'almaty1',city:'almaty',name:'Алматы-1',coord:[43.3404,76.9483],tracks:5},
{id:'almaty2',city:'almaty',name:'Алматы-2',coord:[43.2734,76.9398],tracks:4}];
export const services=stations.flatMap((s,j)=>[0,1].map((v)=>({id:'SIM-'+['021','043','705','208'][((j*2)+v)%4]+'-'+(j+1),station:s.id,type:((j*2)+v)%4,plan:8+j*4+v*12,delay:[0,4,12,22,7,0,18,3,0,9,16,2][j*2+v],cause:[0,0,1,2,3,0,2,1,0,3,2,1][j*2+v],track:1+(j+v)%s.tracks,dest:cities[(j+v+1)%3].name,dir:v?1:-1})));
export const causeNames=[bi('ref009'),bi('ref258'),bi('ref259'),bi('ref246')];
