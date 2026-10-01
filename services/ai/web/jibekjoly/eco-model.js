// Pure counterpart of /eco/advice. Synthetic, instantaneous transitions.
export function ecoAdvice({distanceKm,currentKmh,capKmh,nowMin,openMin,massTons=1000}){
 const base={status:'UNKNOWN',recommended_speed_kmh:null,full_stop_avoided:false,recommended_speed_profile:[],target_arrival_time:null,energy_proxy_units:null,baseline_energy_proxy_units:null,energy_proxy_delta:null,synthetic_only:true};
 if(openMin===null||openMin===undefined)return base;
 if(![distanceKm,currentKmh,capKmh,nowMin,openMin,massTons].every(Number.isFinite)||distanceKm<0||currentKmh<0||capKmh<=0||massTons<=0)return {...base,status:'INVALID'};
 base.target_arrival_time=new Date(Date.parse('2026-10-02T08:00:00+05:00')+openMin*60000).toISOString();
 const seconds=(openMin-nowMin)*60;
 if(seconds<=0)return {...base,status:'EXPIRED'};
 if(currentKmh<=0||distanceKm<=0)return {...base,status:'STOPPED'};
 const speed=distanceKm*3600/seconds;
 if(speed>capKmh)return {...base,status:'UNREACHABLE'};
 if(speed<5)return {...base,status:'HOLD'};
 const baseline=distanceKm/currentKmh*3600,avoided=baseline<seconds-1e-6,mass=massTons/1000;
 const rolling=v=>distanceKm*(.15+.85*(v/capKmh)**2);
 const before=mass*(rolling(currentKmh)+3*Number(avoided)+.05*Math.max(0,seconds-baseline)/60),after=mass*(rolling(speed)+2*((currentKmh-speed)/capKmh)**2);
 return {...base,status:'AVAILABLE',recommended_speed_kmh:speed,full_stop_avoided:avoided,baseline_energy_proxy_units:before,energy_proxy_units:after,energy_proxy_delta:after-before,recommended_speed_profile:[{elapsed_seconds:0,distance_km:0,speed_kmh:speed},{elapsed_seconds:seconds/2,distance_km:distanceKm/2,speed_kmh:speed},{elapsed_seconds:seconds,distance_km:distanceKm,speed_kmh:speed}]};
}
