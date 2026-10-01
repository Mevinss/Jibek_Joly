import {forecast,stressWorld} from './planning.js';
onmessage=e=>{try{const {id,world,config,stress}=e.data;postMessage({id,result:forecast(stress?stressWorld(world,stress):world,config),stress});}catch(error){postMessage({id,error:error.message});}};
