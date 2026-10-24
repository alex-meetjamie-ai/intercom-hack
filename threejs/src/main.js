import './style.css';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createWorld } from './world.js';
import { stops, sampleJourney, boundaries, atTime, phase } from './journey.js';
import { journeyFrame, fitFrame, blendFrames, presentationFor } from './camera.js';
import {createIntercomClient} from '@intercom/client';
import {TERRACE,OFFICE_ORIGIN} from './layout.js';

const $ = id => document.getElementById(id);
const restart=$('restart');
const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
let renderer;
try {
  renderer=new THREE.WebGLRenderer({canvas:$('office-canvas'),antialias:true,alpha:true});
} catch(error) {
  $('loading').hidden=true;$('render-error').hidden=false;
  $('call-jamie').disabled=restart.disabled=true;
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

  let current=0,busy=false,viewSize=30,aspect=1.5,elapsed=0,last=performance.now();
  let toastTimer,denied=false,freeOrbit=false,playhead=stops[0].duration*.32,decisionAnimation=null;
  let callStatus='idle',interactionStarted=false;
  let backendState=null,accepted=false,pendingRequest=false;
  let playback=null;
  let state=sampleJourney(0,.32),canonical=journeyFrame(0,.32,aspect);

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
    $('step-title').textContent=stop.title;
    restart.disabled=busy;
    $('call-jamie').disabled=busy;
    $('call-lift').hidden=true;
    $('allow').hidden=$('deny').hidden=!(current===1&&!busy);
    $('allow').disabled=$('deny').disabled=busy;
    $('viewport').setAttribute('aria-busy',String(busy));
  }
  function showApiError(error){
    clearTimeout(toastTimer);$('api-feedback').textContent=error.message||'Voice backend unavailable.';
    $('api-feedback').hidden=false;toastTimer=setTimeout(()=>$('api-feedback').hidden=true,8000);
  }
  const client=createIntercomClient({baseUrl:import.meta.env.VITE_API_BASE_URL||'',audio:$('remote-audio'),onError:showApiError,
    onAudioBlocked:blocked=>{$('play-audio').hidden=!blocked;},
    onState:state=>{
      callStatus=state;
    },onRequestReady:()=>{
      if(interactionStarted)pendingRequest=true;
    },onStatus:status=>{
      backendState=status;
      const message=status.transcript?.at(-1);
      $('live-transcript').textContent=message?`${message.speaker}: ${message.text}`:'';
      $('live-transcript').hidden=!message;

    },
  });
  function pressIntercom(){
    if(busy||current!==0)return;
    if(client.active){client.disconnect().catch(showApiError);return;}
    interactionStarted=true;
    playhead=stops[0].duration*.32;
    goTo(0,{replay:true});
    client.ring();
  }
  $('call-jamie').addEventListener('click',pressIntercom);

  $('play-audio').addEventListener('click',client.playAudio);
  function goTo(index,{replay=false,progress=1}={}){
    if(busy||(index===current&&!replay))return;
    // Keep the same playhead and traverse every intermediate position, even
    // when rewinding or skipping. No midpoint reset, hidden swap or dissolve.
    controls.enableDamping=false;controls.update();controls.enableDamping=true;
    const fromCamera=freeOrbit?snapshotCamera():null;
    controls.enabled=false;freeOrbit=false;
    const target=boundaries[index]+stops[index].duration*progress;
    const from=playhead;
    playback={start:performance.now(),duration:reducedMotion.matches?0:Math.min(14000,Math.max(700,Math.abs(target-from))),from,to:target,camera:fromCamera};
    current=index;busy=true;denied=false;updateUI();

  }

  function chooseOnPhone(choice){
    if(busy||current!==1)return;
    freeOrbit=false;controls.enabled=false;busy=true;
    decisionAnimation={choice,start:performance.now(),sent:false,settled:false,error:null};updateUI();
  }
  restart.addEventListener('click',()=>{
    client.disconnect().catch(showApiError);interactionStarted=false;
    accepted=false;pendingRequest=false;current=0;playback=null;playhead=stops[0].duration*.32;freeOrbit=false;updateUI();
  });
  $('allow').addEventListener('click',()=>chooseOnPhone('yes'));
  $('deny').addEventListener('click',()=>chooseOnPhone('no'));
  let pointerStart=null;
  function pointer(event){
    const rect=renderer.domElement.getBoundingClientRect();
    return new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2);
  }
  function hitAction(event){
    if(busy)return null;
    const point=pointer(event);
    if(current===1)return world.pickPhoneChoice(point,camera);
    const hit=world.pickInteraction(point,camera);
    return current===0&&hit==='intercom'?hit:null;
  }
  // Hit-test before OrbitControls sees pointer-down. Otherwise its start
  // event reframes the scene and moves the button before pointer-up arrives.
  renderer.domElement.addEventListener('pointerdown',event=>{
    pointerStart={x:event.clientX,y:event.clientY,action:hitAction(event)};
    if(pointerStart.action)event.stopImmediatePropagation();
  },true);
  renderer.domElement.addEventListener('pointerup',event=>{
    const start=pointerStart;pointerStart=null;
    if(!start?.action)return;
    event.stopImmediatePropagation();
    if(Math.hypot(event.clientX-start.x,event.clientY-start.y)>6)return;
    freeOrbit=false;
    if(start.action==='intercom')pressIntercom();
    else if(start.action==='yes'||start.action==='no')chooseOnPhone(start.action);
  },true);
  renderer.domElement.addEventListener('pointercancel',()=>{pointerStart=null;});
  renderer.domElement.addEventListener('pointermove',event=>{
    if(pointerStart&&!pointerStart.action&&!busy&&Math.hypot(event.clientX-pointerStart.x,event.clientY-pointerStart.y)>6)freeOrbit=true;
    renderer.domElement.style.cursor=hitAction(event)?'pointer':'grab';
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&client.active)client.disconnect().catch(showApiError);
  });
  const observer=new ResizeObserver(resize);observer.observe($('viewport'));resize();updateUI();controls.enabled=true;

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
    if(decisionAnimation){
      const pending=decisionAnimation;
      if(!pending.sent&&now-pending.start>=440){
        pending.sent=true;
        client.decide(pending.choice==='yes').then(()=>{pending.settled=true;}).catch(error=>{pending.error=error;pending.settled=true;});
      }
      if(pending.settled&&now-pending.start>=1100){
        decisionAnimation=null;busy=false;controls.enabled=true;
        if(pending.error){showApiError(pending.error);updateUI();}
        else if(pending.choice==='yes'){accepted=true;goTo(2);}
        else{denied=true;accepted=false;pendingRequest=false;interactionStarted=false;goTo(0,{replay:true});}
      }
    }
    if(!review&&!busy&&!decisionAnimation){
      if(pendingRequest&&current===0){pendingRequest=false;goTo(1);}
      else if(current===2)goTo(3);
      else if(current===3&&playhead>=boundaries[4]-.01)goTo(4);
      else if(current===4)goTo(5);
    }
    const cursor=atTime(playhead);
    state={...cursor.state,presentation:presentationFor(),callStatus};
    if(!review&&!accepted&&current<=1)state.streetDoor=0;
    if(!interactionStarted&&!review&&current===0){state.intercomReach=0;state.intercomPress=0;state.ring=0;}
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

    renderer.render(scene,camera);$('loading').hidden=true;
  });
}
