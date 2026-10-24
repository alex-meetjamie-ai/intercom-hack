import { sampleJourney, phase, TOP, CABIN } from './journey.js';
import {OFFICE_ORIGIN} from './layout.js';

const DISTANCE=80;
const direction=[.62,.43,1];
const mix=(a,b,t)=>a+(b-a)*t;
const add=(a,b)=>a.map((x,i)=>x+b[i]);
const sub=(a,b)=>a.map((x,i)=>x-b[i]);
const scale=(a,k)=>a.map(x=>x*k);
const dot=(a,b)=>a.reduce((sum,x,i)=>sum+x*b[i],0);
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const normalize=a=>scale(a,1/Math.hypot(...a));
const vectorMix=(a,b,t)=>a.map((x,i)=>mix(x,b[i],t));
export const WORLD_BOUNDS={min:[-18,-.65,-24],max:[14.1,22,21.3]};
const streetBounds={min:[-12,-.3,8],max:[12,16,20]};
const officeBounds={min:[-17.6,15.65,-20.5],max:[11.2,22,-3.3]};
const around=(point,radius=4)=>({min:[point[0]-radius,point[1]-2,point[2]-radius],max:[point[0]+radius,point[1]+4,point[2]+radius]});
export function corners(bounds){return [0,1].flatMap(x=>[0,1].flatMap(y=>[0,1].map(z=>[x?bounds.max[0]:bounds.min[0],y?bounds.max[1]:bounds.min[1],z?bounds.max[2]:bounds.min[2]])));}
export function basis(frame){
  const forward=normalize(sub(frame.target,frame.position));
  let right=cross(forward,[0,1,0]);if(Math.hypot(...right)<.00001)right=[1,0,0];
  right=normalize(right);return {forward,right,up:normalize(cross(right,forward))};
}
export function projectPoint(frame,point){const b=basis(frame),relative=sub(point,frame.target);return {x:dot(relative,b.right),y:dot(relative,b.up),depth:dot(sub(point,frame.position),b.forward)};}
export function fitFrame(frame,bounds,aspect=1.5,padding=1.12){
  const b=basis(frame),points=corners(bounds).map(point=>projectPoint(frame,point));
  const xs=points.map(p=>p.x),ys=points.map(p=>p.y);
  const left=Math.min(...xs),right=Math.max(...xs),bottom=Math.min(...ys),top=Math.max(...ys);
  const shift=add(scale(b.right,(left+right)/2),scale(b.up,(bottom+top)/2));
  return {position:add(frame.position,shift),target:add(frame.target,shift),bounds,size:Math.max((top-bottom)*padding,(right-left)*padding/Math.max(.1,aspect),frame.minSize||0)};
}
function shot(target,size,aspect,bounds,viewDirection=direction){
  return {target,position:add(target,scale(normalize(viewDirection),DISTANCE)),size:size*Math.max(1,1/Math.max(.1,aspect)),bounds};
}
export function blendFrames(a,b,t){
  if(t<=0)return a;if(t>=1)return b;
  const av=normalize(sub(a.position,a.target)),bv=normalize(sub(b.position,b.target));
  const yawA=Math.atan2(av[0],av[2]),yawB=Math.atan2(bv[0],bv[2]);
  const yaw=yawA+Math.atan2(Math.sin(yawB-yawA),Math.cos(yawB-yawA))*t;
  const pitch=mix(Math.asin(av[1]),Math.asin(bv[1]),t);
  const facing=[Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch)];
  const target=vectorMix(a.target,b.target,t);
  return {target,position:add(target,scale(facing,DISTANCE)),size:mix(a.size,b.size,t),bounds:b.bounds};
}
function entrance(aspect){return shot([0,5.6,11.2],26,aspect,streetBounds);}
function rooftop(aspect){return fitFrame({...shot([OFFICE_ORIGIN[0]-1.4,TOP+2.3,-12],25,aspect,officeBounds,[-.55,.6,1]),minSize:25},officeBounds,aspect);}
function overhead(aspect){return fitFrame({...shot([0,11.5,-3],43,aspect,WORLD_BOUNDS,[-.15,.85,1]),minSize:43},WORLD_BOUNDS,aspect);}
function officeFlight(p,aspect){
  const start=entrance(aspect),above=overhead(aspect),end=rooftop(aspect);
  if(p<.45)return blendFrames(start,above,phase(p,0,.45));
  return blendFrames(above,end,phase(p,.45,1));
}
// Camera and actors share the same progress. The camera follows the courier
// rather than finishing a separate scene transition before he starts moving.
export function journeyFrame(index,progress,aspect=1.5){
  const p=Math.max(0,Math.min(1,progress)),state=sampleJourney(index,p);
  if(index===0)return entrance(aspect);
  if(index===1)return officeFlight(phase(p,0,.64),aspect);
  if(index===2)return officeFlight(1-phase(p,.08,.72),aspect);
  if(index===3){
    const followTarget=add(state.visitor,[0,2.8,-1.3]);
    const follow=shot(followTarget,15,aspect,around(followTarget,4.5));
    return blendFrames(entrance(aspect),follow,phase(p,0,.28));
  }
  if(index===4){
    // Ease from the waiting position into the car, then match its vertical
    // displacement exactly. Open out to the terrace as it reaches the top.
    const target=add(state.visitor,[0,2.8,-1.3]);
    const follow=shot(target,15,aspect,around(target,4.5));
    const end=rooftop(aspect);
    const frame=blendFrames(follow,end,phase(p,.73,.98));
    const facing=blendFrames(follow,end,phase(p,.28,.98));
    frame.position=frame.target.map((value,i)=>value+facing.position[i]-facing.target[i]);
    return frame;
  }
  return rooftop(aspect);
}
export function sceneFrame(index,aspect=1.5){return journeyFrame(index,1,aspect);}
// All architecture stays in the same world. Only foreground walls become
// transparent cutaways; no scene layer or lower shaft disappears at a stop.
export function presentationFor(){return {street:1,courtyard:1,loft:1,terrace:1,shaft:1,lowerShaft:1};}
