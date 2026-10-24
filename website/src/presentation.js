// Explanatory presentation only. Opening the demo never starts a call.
import {buildFullSystem} from '/diagram.js';

const $ = id => document.getElementById(id);
const problem = $('problem'), solution = $('solution');
const previous = $('previous-slide'), next = $('next-slide');
const diagram=buildFullSystem({presentation:true});
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
const viewport=$('system-svg');
const revealElements=[...viewport.querySelectorAll('[data-reveal-step]')];
function revealThrough(step){
  revealElements.forEach(el=>{
    const visible=step>=Number(el.dataset.revealStep), wasHidden=el.style.display==='none';
    el.style.display=visible?'':'none';
    el.setAttribute('aria-hidden',String(!visible));
    el.classList.toggle('build-enter',visible&&wasHidden);
  });
}
// Keep earlier modules visible in the letterboxed area as the camera moves.
// The viewport boundary crops the drawing; reveal steps hide future modules.
function setCamera(values){
  viewport.setAttribute('viewBox',values.join(' '));
}
const steps = [
  {hash:'problem', title:'The problem', view:'pins', reveal:0, phase:0},
  {hash:'solution', title:'SKS wiring', view:'pins', reveal:1, phase:0},
  {hash:'solution-bridge', title:'Add the PCB', view:'bridge', reveal:2, phase:0},
  {hash:'solution-network', title:'Connect the network', view:'hardware', reveal:3, phase:0},
  {hash:'solution-network2', title:'Raspberry Pi bridge', view:'software', reveal:3, phase:0},
  {hash:'solution-agent', title:'Add Jamie', view:'software', reveal:4, phase:1},
  {hash:'solution-tools', title:'Agent tools', view:'software', reveal:5, phase:3},
  {hash:'solution-overview', title:'Overview', view:'all', reveal:5, phase:0},
  {hash:'solution-demo', title:'Demo', view:'all', reveal:5, phase:0},
];
let current = 0;
const views={
  pins:[0,50,950,590],
  bridge:[0,45,1380,610],
  hardware:[0,20,1700,640],
  software:[0,665,1700,450],
  all:[0,0,1700,1135],
};
let cameraFrame;
function focusDiagram(name, animate=true){
  cancelAnimationFrame(cameraFrame);
  const to=views[name], from=viewport.getAttribute('viewBox').split(/\s+/).map(Number);
  if(!animate || reducedMotion.matches){setCamera(to);return;}
  const start=performance.now();
  function move(now){
    const t=Math.min(1,(now-start)/650), ease=1-Math.pow(1-t,3);
    setCamera(from.map((n,i)=>n+(to[i]-n)*ease));
    if(t<1)cameraFrame=requestAnimationFrame(move);
  }
  cameraFrame=requestAnimationFrame(move);
}
let lastFrame, flowTime=0;
function animateDiagram(now){
  if(!solution.hidden && !viewport.hasAttribute('hidden') && !document.hidden && !reducedMotion.matches){
    flowTime+=Math.min(now-(lastFrame??now),80);
    diagram.animate(flowTime);
  }
  lastFrame=now;requestAnimationFrame(animateDiagram);
}
requestAnimationFrame(animateDiagram);
function showStep(index, updateHash=true, scrollToBuild=false) {
  current=Math.max(0,Math.min(steps.length-1,index));
  const step=steps[current];
  const isProblem=current===0, demo=current===steps.length-1, overview=current===steps.length-2;
  const slideNumber=isProblem?1:demo?4:overview?3:2;
  const slideTitle=isProblem?'The problem':demo?'Demo':overview?'Overview':'The solution';
  problem.hidden=!isProblem;problem.inert=!isProblem;problem.classList.toggle('is-active',isProblem);
  solution.hidden=isProblem;solution.inert=isProblem;solution.classList.toggle('is-active',!isProblem);
  solution.classList.toggle('demo-view',demo);
  revealThrough(step.reveal);
  diagram.render(step.phase,'Alex');
  viewport.toggleAttribute('hidden',demo);
  $('demo-svg').toggleAttribute('hidden',!demo);
  focusDiagram(step.view,updateHash&&!isProblem);
  $('pin-inspector').hidden=current>=4;
  previous.disabled=isProblem;
  next.textContent=demo?'↗':'→';
  next.setAttribute('aria-label',demo?'Open the demo':'Next step');
  next.title=demo?'Open demo · Right arrow or Space':'Next · Right arrow or Space';
  solution.setAttribute('aria-label',`${slideNumber} of 4 — ${slideTitle}`);
  $('deck-progress').style.width=`${(current+1)/steps.length*100}%`;
  $('slide-announcement').textContent=`${current+1} of ${steps.length}: ${steps[current].title}`;
  if(updateHash)history.replaceState(null,'',`#${steps[current].hash}`);
  if(scrollToBuild)solution.scrollTop=0;
  $('architecture-viewport').scrollLeft=0;
}
function advance() {
  if(current===steps.length-1){
    const demoUrl=new URL('/',window.location.href);
    demoUrl.port='5173';
    window.location.assign(demoUrl.href);
    return;
  }
  showStep(current+1,true,true);
}
function back(){showStep(current-1,true,true);}
function fromHash(){
  const oldHashes={sks:1,doorman:2,network:3,network2:4,agent:5,tools:6,overview:7,demo:8};
  const hash=location.hash.slice(1);
  const index=steps.findIndex(step=>step.hash===hash);
  showStep(index<0?(oldHashes[hash]??0):index,false);
}
previous.addEventListener('click',back);next.addEventListener('click',advance);
window.addEventListener('hashchange',fromHash);
document.addEventListener('keydown',event=>{
  if(event.altKey || event.ctrlKey || event.metaKey || event.repeat)return;
  if(event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
  if(event.code==='Space' && event.target.closest('[role="button"]'))return;
  if(event.code==='Space' && event.target.closest('a,button') && !event.target.closest('#previous-slide,#next-slide'))return;
  if(['ArrowRight','ArrowDown'].includes(event.key) || event.code==='Space'){
    event.preventDefault();event.shiftKey?back():advance();
  }else if(['ArrowLeft','ArrowUp'].includes(event.key)){
    event.preventDefault();back();
  }else if(event.key==='Home'||event.key==='End'){
    event.preventDefault();showStep(event.key==='Home'?0:steps.length-1,true,true);
  }
});
let touchStart;
$('presentation').addEventListener('touchstart',event=>{
  if(event.touches.length===1&&!event.target.closest('a,button,.architecture-panel'))touchStart=[event.touches[0].clientX,event.touches[0].clientY];
},{passive:true});
$('presentation').addEventListener('touchend',event=>{
  if(!touchStart)return;
  const dx=event.changedTouches[0].clientX-touchStart[0],dy=event.changedTouches[0].clientY-touchStart[1];
  if(Math.abs(dx)>65&&Math.abs(dx)>Math.abs(dy)*1.5)dx<0?advance():back();
  touchStart=null;
},{passive:true});
$('presentation').addEventListener('touchcancel',()=>{touchStart=null;},{passive:true});
const fullscreen=$('fullscreen');
if(!document.documentElement.requestFullscreen)fullscreen.hidden=true;
fullscreen.addEventListener('click',async()=>{
  try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}
  catch{$('slide-announcement').textContent='Fullscreen is unavailable in this browser. You can continue presenting here.';}
});
document.addEventListener('fullscreenchange',()=>{
  fullscreen.setAttribute('aria-label',document.fullscreenElement?'Exit fullscreen':'Enter fullscreen');
  fullscreen.title=document.fullscreenElement?'Exit fullscreen':'Fullscreen';
});
fromHash();
