import './style.css';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createWorld } from './world.js';
import { stops, sampleJourney, boundaries, atTime, phase } from './journey.js';
import { journeyFrame, fitFrame, blendFrames, presentationFor } from './camera.js';
import { sendTourEvent } from './api.js';
import {TERRACE,OFFICE_ORIGIN} from './layout.js';

const $ = id => document.getElementById(id);
const next=$('next'),back=$('back'),restart=$('restart');
const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
let renderer;
try {
  renderer=new THREE.WebGLRenderer({canvas:$('office-canvas'),antialias:true,alpha:true});
} catch(error) {
  $('loading').hidden=true;$('render-error').hidden=false;
  next.disabled=back.disabled=restart.disabled=true;
  console.error('Unable to start the 3D view.',error);
}
if(renderer)start();

function start(){
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.28;
  const scene=new THREE.Scene();
  scene.background=new THREE.Color(0xe5ece5);
  const camera=new THREE.OrthographicCamera(-20,20,15,-15,.1,220);
  const controls=new OrbitControls(camera,renderer.domElement);
  controls.enableDamping=true;controls.enablePan=false;controls.enableZoom=false;
  controls.minPolarAngle=.25;controls.maxPolarAngle=Math.PI/2.05;controls.rotateSpeed=.6;
  scene.add(new THREE.HemisphereLight(0xfff9e9,0x8eaa9e,2.7));
  const sun=new THREE.DirectionalLight(0xffecd3,3.1);sun.position.set(-13,38,25);
  sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.normalBias=.035;
  Object.assign(sun.shadow.camera,{left:-35,right:35,top:35,bottom:-35,near:.5,far:140});
  sun.target.position.set(0,7,-3);scene.add(sun,sun.target);
  const fill=new THREE.DirectionalLight(0xdeeee5,1.3);fill.position.set(20,25,-18);scene.add(fill);
  const world=createWorld();scene.add(world.group);
  // One fixed ground plane keeps shadows spatially consistent during travel.
  const ground=new THREE.Mesh(new THREE.PlaneGeometry(250,250),new THREE.ShadowMaterial({color:0x646d54,opacity:.11}));
  ground.rotation.x=-Math.PI/2;ground.receiveShadow=true;scene.add(ground);

  let current=0,busy=true,viewSize=30,aspect=1.5,elapsed=0,last=performance.now();
  let controller,toastTimer,denied=false,freeOrbit=false,playhead=0,decisionAnimation=null;
  let playback={start:performance.now(),duration:reducedMotion.matches?0:stops[0].duration,from:0,to:boundaries[1],camera:null};
  let state=sampleJourney(0,0),canonical=journeyFrame(0,0,aspect);
  controls.addEventListener('start',()=>{if(!busy)freeOrbit=true;});

  function applyFrame(frame){
    camera.position.fromArray(frame.position);controls.target.fromArray(frame.target);
    viewSize=frame.size;camera.lookAt(controls.target);
    camera.left=-viewSize*aspect/2;camera.right=viewSize*aspect/2;camera.top=viewSize/2;camera.bottom=-viewSize/2;camera.updateProjectionMatrix();
  }
  function snapshotCamera(){return{position:camera.position.toArray(),target:controls.target.toArray(),size:viewSize,bounds:canonical.bounds};}
  function fitCurrentPose(){applyFrame(fitFrame({...snapshotCamera(),minSize:canonical.size},canonical.bounds,aspect));}
  function resize(){
    const {width,height}=$('viewport').getBoundingClientRect();if(!width||!height)return;
    aspect=width/height;renderer.setSize(width,height,false);
    const cursor=atTime(playhead);canonical=journeyFrame(cursor.index,cursor.progress,aspect);
    if(freeOrbit&&!busy)fitCurrentPose();else applyFrame(canonical);
  }
  function updateUI(){
    const stop=stops[current];
    $('app').dataset.scene=String(current);
    $('step-number').textContent=String(current+1).padStart(2,'0');
    $('step-title').textContent=stop.title;
    $('next-label').textContent=current===1?'Choose on phone':current===5?'Replay':'Next';
    next.disabled=busy||current===1;back.disabled=busy||current===0;restart.disabled=busy;
    $('allow').disabled=$('deny').disabled=busy;
    $('viewport').setAttribute('aria-busy',String(busy));
    $('decision-message').textContent=denied?'Door closed. The courier is waiting.':'Pizza delivery';
    $('notification-panel').classList.toggle('declined',denied);
  }
  function report(stop,event='tour_step_entered'){
    controller?.abort();controller=new AbortController();const active=controller;
    clearTimeout(toastTimer);$('api-feedback').hidden=true;
    const timeout=setTimeout(()=>active.abort(new DOMException('Request timed out','TimeoutError')),5000);
    sendTourEvent(stop.id,{event,signal:active.signal}).catch(error=>{
      if(controller!==active)return;
      console.warn('Could not send the demo event.',error);
      $('api-feedback').textContent='The connection didn’t go through. You can keep exploring and try this stop again.';
      $('api-feedback').hidden=false;toastTimer=setTimeout(()=>$('api-feedback').hidden=true,6500);
    }).finally(()=>clearTimeout(timeout));
  }
  function goTo(index,{replay=false,decision=false}={}){
    if(busy||(index===current&&!replay))return;
    // Keep the same playhead and traverse every intermediate position, even
    // when rewinding or skipping. No midpoint reset, hidden swap or dissolve.
    controls.enableDamping=false;controls.update();controls.enableDamping=true;
    const fromCamera=freeOrbit?snapshotCamera():null;
    controls.enabled=false;freeOrbit=false;
    const target=boundaries[index+1];
    const from=(replay&&current===0)?0:playhead;
    playback={start:performance.now(),duration:reducedMotion.matches?0:Math.min(14000,Math.max(700,Math.abs(target-from))),from,to:target,camera:fromCamera};
    current=index;busy=true;denied=false;$('notification-panel').hidden=true;updateUI();
    report(stops[index],decision?'access_request_approved':'tour_step_entered');
  }

  function chooseOnPhone(choice){
    if(busy||current!==1)return;
    freeOrbit=false;controls.enabled=false;busy=true;
    decisionAnimation={choice,start:performance.now()};updateUI();
  }
  next.addEventListener('click',()=>goTo((current+1)%stops.length));
  back.addEventListener('click',()=>goTo(Math.max(0,current-1)));
  restart.addEventListener('click',()=>goTo(0,{replay:true}));
  $('allow').addEventListener('click',()=>chooseOnPhone('yes'));
  $('deny').addEventListener('click',()=>chooseOnPhone('no'));
  let pointerStart=null;
  function phoneHit(event){
    const rect=renderer.domElement.getBoundingClientRect();
    return world.pickPhoneChoice(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2),camera);
  }
  renderer.domElement.addEventListener('pointerdown',event=>{pointerStart=[event.clientX,event.clientY];});
  renderer.domElement.addEventListener('pointerup',event=>{
    if(current!==1||busy||!pointerStart||Math.hypot(event.clientX-pointerStart[0],event.clientY-pointerStart[1])>6)return;
    const choice=phoneHit(event);if(choice)chooseOnPhone(choice);
  });
  renderer.domElement.addEventListener('pointermove',event=>{
    renderer.domElement.style.cursor=current===1&&!busy&&phoneHit(event)?'pointer':'grab';
  });
  document.addEventListener('keydown',event=>{
    if(event.altKey||event.ctrlKey||event.metaKey||/INPUT|TEXTAREA|SELECT|BUTTON|A/.test(event.target.tagName)||event.target.isContentEditable)return;
    if(event.key==='ArrowRight'||event.code==='Space'){event.preventDefault();next.click();}if(event.key==='ArrowLeft'){event.preventDefault();back.click();}
  });
  const observer=new ResizeObserver(resize);observer.observe($('viewport'));resize();updateUI();controls.enabled=false;

  // Development-only deterministic samples use the same state and camera
  // path as playback, so route geometry can be reviewed without timing shots.
  const params=new URLSearchParams(location.search);
  const review=import.meta.env.DEV&&params.has('reviewTo');
  const planReview=review&&params.has('plan');
  if(planReview){
    const office={left:OFFICE_ORIGIN[0]-10,right:OFFICE_ORIGIN[0]+10,back:OFFICE_ORIGIN[2]-6.395,front:OFFICE_ORIGIN[2]+5.905};
    for(const [rect,color] of [[office,0xeb573f],[TERRACE,0xf4cf31]]){
      const points=[[rect.left,24,rect.back],[rect.right,24,rect.back],[rect.right,24,rect.front],[rect.left,24,rect.front]].map(point=>new THREE.Vector3(...point));
      const outline=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color,depthTest:false}));
      outline.renderOrder=10;scene.add(outline);
    }
  }
  const reviewTo=Math.max(0,Math.min(5,Number(params.get('reviewTo'))||0));
  const reviewFrom=Math.max(0,Math.min(5,Number(params.get('reviewFrom'))||0));
  const reviewAt=Math.max(0,Math.min(1,Number(params.get('reviewAt'))||0));
  const reviewAction=params.get('reviewAction');
  if(review){current=reviewTo;busy=false;controls.enabled=false;updateUI();}

  renderer.setAnimationLoop(now=>{
    const dt=Math.min((now-last)/1000,.05);last=now;if(!document.hidden&&!reducedMotion.matches)elapsed+=dt;
    if(review){
      playhead=reviewAction!==null
        ?boundaries[reviewTo]+Math.max(0,Math.min(1,Number(reviewAction)||0))*stops[reviewTo].duration
        :boundaries[reviewFrom+1]+(boundaries[reviewTo+1]-boundaries[reviewFrom+1])*reviewAt;
    }else if(playback){
      const t=playback.duration===0?1:Math.min(1,(now-playback.start)/playback.duration);
      playhead=playback.from+(playback.to-playback.from)*t;
      if(t===1){playback=null;busy=false;controls.enabled=true;updateUI();}
    }
    if(decisionAnimation&&now-decisionAnimation.start>=1100){
      const choice=decisionAnimation.choice;decisionAnimation=null;busy=false;controls.enabled=true;
      if(choice==='yes')goTo(2,{decision:true});
      else{denied=true;updateUI();report(stops[current],'access_request_denied');}
    }
    const cursor=atTime(playhead);
    state={...cursor.state,presentation:presentationFor()};
    if(denied&&current===1)state.phoneChoice='no';
    if(decisionAnimation){
      const p=Math.min(1,(now-decisionAnimation.start)/1100);
      state.phoneTap=phase(p,0,.40)*(1-phase(p,.70,1));state.phoneChoice=decisionAnimation.choice;
    }
    canonical=journeyFrame(cursor.index,cursor.progress,aspect);
    if(busy||review){
      const blend=playback?.camera?phase(now-playback.start,0,Math.min(900,playback.duration)):1;
      applyFrame(playback?.camera?blendFrames(playback.camera,canonical,blend):canonical);
    }else if(!freeOrbit){applyFrame(canonical);controls.update();}
    else{controls.update();fitCurrentPose();}
    if(planReview){
      state={...state,facade:1,leftWing:1,greet:0};
      camera.up.set(0,0,1);
      applyFrame({position:[0,80,0],target:[0,0,0],size:49});
    }
    ground.position.y=-.67;ground.material.opacity=.1;
    world.update(state,review?1:elapsed,camera);world.updateView(camera);
    $('notification-panel').hidden=busy||current!==1||state.notification<.75;
    $('scene-progress').style.transform=`scaleX(${playhead/boundaries.at(-1)})`;
    renderer.render(scene,camera);$('loading').hidden=true;
  });
}
