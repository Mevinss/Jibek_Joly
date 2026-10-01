import { mountRealtime, disposeRealtime } from './realtime.js';
let lang=localStorage.getItem('jol-lang')==='1'?1:0;
let dark=localStorage.getItem('jol-theme')==='dark';
function render(){disposeRealtime();document.documentElement.lang=lang?'kk':'ru';document.body.classList.toggle('light',!dark);mountRealtime({lang,dark,onLanguage:value=>{lang=value;localStorage.setItem('jol-lang',value);render();},onTheme:()=>{dark=!dark;localStorage.setItem('jol-theme',dark?'dark':'light');render();}});}
render();
