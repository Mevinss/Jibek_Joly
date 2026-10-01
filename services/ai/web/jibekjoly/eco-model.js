// Synthetic acceleration rates, not a validated braking curve.
export function ecoAdvice({distanceKm,currentKmh,capKmh,nowMin,openMin,massTons=1000,acceleration=.1,deceleration=.12}){
 const base={status:'UNKNOWN',recommended_speed_kmh:null,cruise_speed_kmh:null,full_stop_avoided:false,recommended_speed_profile:[],target_arrival_time:null,energy_proxy_units:null,baseline_energy_proxy_units:null,energy_proxy_delta:null,synthetic_only:true};
 if(openMin===null||openMin===undefined)return base;
 if(![distanceKm,currentKmh,capKmh,nowMin,openMin,massTons,acceleration,deceleration].every(Number.isFinite)||distanceKm<0||currentKmh<0||capKmh<=0||massTons<=0||acceleration<=0||deceleration<=0)return {...base,status:'INVALID'};
 base.target_arrival_time=new Date(Date.parse('2026-10-02T08:00:00+05:00')+openMin*60000).toISOString();
 const seconds=(openMin-nowMin)*60;
 if(seconds<=0)return {...base,status:'EXPIRED'};
 if(currentKmh<=0||distanceKm<=0)return {...base,status:'STOPPED'};
 const profile=u=>{const rate=(u<currentKmh?deceleration:acceleration)*3.6,tau=Math.min(seconds,Math.abs(u-currentKmh)/rate),v=currentKmh+Math.sign(u-currentKmh)*rate*tau,first=(currentKmh+v)/2*tau/3600;return {tau,v,first,distance:first+v*(seconds-tau)/3600};};
 if(profile(capKmh).distance<distanceKm-1e-8)return {...base,status:'UNREACHABLE'};
 if(profile(5).distance>distanceKm+1e-8)return {...base,status:'HOLD'};
 let lo=5,hi=capKmh;for(let i=0;i<55;i++){const mid=(lo+hi)/2;if(profile(mid).distance>distanceKm)hi=mid;else lo=mid;}
 const cruise=(lo+hi)/2,p=profile(cruise),mean=distanceKm*3600/seconds;
 const samples=[{elapsed_seconds:0,distance_km:0,speed_kmh:currentKmh}];
 if(p.tau>1e-6)samples.push({elapsed_seconds:p.tau,distance_km:p.first,speed_kmh:p.v});
 if(seconds-p.tau>1e-6)samples.push({elapsed_seconds:seconds,distance_km:distanceKm,speed_kmh:p.v});
 const baseline=distanceKm/capKmh*3600,avoided=baseline<seconds-1e-6,mass=massTons/1000;
 const ramp=p.tau/3600*(.15*(currentKmh+p.v)/2+.85*(currentKmh**3+currentKmh**2*p.v+currentKmh*p.v**2+p.v**3)/4/capKmh**2);
 const after=mass*(ramp+(distanceKm-p.first)*(.15+.85*(p.v/capKmh)**2)+3*Math.max(0,p.v**2-currentKmh**2)/capKmh**2);
 const before=mass*(distanceKm+3*Number(avoided)+.05*Math.max(0,seconds-baseline)/60);
 return {...base,status:'AVAILABLE',recommended_speed_kmh:mean,cruise_speed_kmh:cruise,full_stop_avoided:avoided,baseline_energy_proxy_units:before,energy_proxy_units:after,energy_proxy_delta:after-before,recommended_speed_profile:samples};
}
