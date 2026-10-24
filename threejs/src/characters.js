import * as THREE from 'three';
import { group, box, ball, cylinder, label, material } from './geometry.js';
import {PHONE_POSE,PHONE_CHOICES} from './layout.js';

let dhlTexture;
function dhlLogo(parent,width,position){
  if(!dhlTexture){
    dhlTexture=new THREE.TextureLoader().load(`${import.meta.env.BASE_URL}branding/dhl.svg`);
    dhlTexture.colorSpace=THREE.SRGBColorSpace;
    dhlTexture.anisotropy=8;
  }
  const logo=new THREE.Mesh(new THREE.PlaneGeometry(width,width*65/284),new THREE.MeshBasicMaterial({map:dhlTexture,transparent:false,alphaTest:.5,depthWrite:true,side:THREE.FrontSide}));
  logo.name='DHL logo';logo.position.fromArray(position);parent.add(logo);return logo;
}

export function createPerson(parent, { name, position = [0, 0, 0], shirt = 'teal', courier = false, glasses = false }) {
  const root = group(parent, name, position);
  const body = group(root, 'Body');
  box(body, [.69, .82, .4], [0, 1.15, 0], shirt, .15);
  cylinder(body, .11, .17, [0, 1.65, 0], 'skin');
  const head=ball(body, .32, [0, 1.97, 0], 'skin', [.9, 1.1, .9]);head.name='Head';
  // A real cap covers the skull crown; a flattened sphere left the scalp exposed.
  const hair=new THREE.Mesh(new THREE.SphereGeometry(.335,24,16,0,Math.PI*2,0,1.38),material('hair'));
  hair.name='Hair cap';hair.position.set(0,1.97,0);hair.scale.set(.94,courier?.98:1.12,.97);hair.castShadow=true;body.add(hair);
  for(const side of [-1,1])ball(body,.13,[side*.253,2.06,-.055],'hair',[.3,.78,.85]);
  ball(body, .055, [0, 1.94, .285], 'skin');
  for (const x of [-.105, .105]) ball(body, .028, [x, 2, .277], 'charcoal');
  if (glasses) {
    for (const x of [-.12, .12]) {
      const lens = new THREE.Mesh(new THREE.TorusGeometry(.092, .014, 6, 16), material('charcoal'));
      lens.position.set(x, 2, .28); body.add(lens);
    }
    box(body, [.08, .023, .02], [0, 2, .285], 'charcoal', 0);
  }
  const elbows = [], hands = [];
  const arms = [-1, 1].map(side => {
    const pivot = group(body, 'Arm', [side * .44, 1.48, 0]);
    box(pivot, [.23, .35, .24], [0, -.135, 0], shirt, .085);
    const elbow = group(pivot, 'Forearm', [0, -.31, 0]);
    box(elbow, [.205, .29, .21], [0, -.115, 0], shirt, .07);
    hands.push(ball(elbow, .12, [0, -.31, 0], 'skin'));
    elbows.push(elbow); return pivot;
  });
  const legs = [-1, 1].map(side => {
    const pivot = group(body, 'Leg', [side * .19, .78, 0]);
    box(pivot, [.26, .66, .29], [0, -.31, 0], 'charcoal', .075);
    box(pivot, [.29, .17, .45], [0, -.66, .075], 'navy', .06); return pivot;
  });
  // Independent two-bone reach rigs let fingertips meet real world controls.
  const reachRigs=[-1,1].map((side,index)=>{
    const rig=group(body,side===1?'Right interaction arm':'Left interaction arm');
    const upper=box(rig,[.23,1,.24],[0,0,0],shirt,.06);
    const lower=box(rig,[.19,1,.20],[0,0,0],shirt,.06);
    const palm=ball(rig,.105,[0,0,0],'skin');
    const finger=cylinder(rig,.032,1,[0,0,0],'skin');
    const tip=ball(rig,.034,[0,0,0],'skin');tip.name=side===1?'Right fingertip':'Left fingertip';
    rig.visible=false;
    return {rig,upper,lower,palm,finger,tip,side,index};
  });
  const up=new THREE.Vector3(0,1,0);
  function segment(mesh,a,b){
    mesh.position.copy(a).add(b).multiplyScalar(.5);
    mesh.quaternion.setFromUnitVectors(up,b.clone().sub(a).normalize());
    mesh.scale.y=a.distanceTo(b);
  }
  function reach(index,contactWorld,normalWorld,amount){
    const rig=reachRigs[index];rig.rig.visible=amount>.001;arms[index].visible=!rig.rig.visible;
    if(!rig.rig.visible)return;
    body.updateWorldMatrix(true,true);
    const shoulder=new THREE.Vector3(rig.side*.44,1.48,0);
    const resting=body.worldToLocal(hands[index].getWorldPosition(new THREE.Vector3()));
    const contact=body.worldToLocal(new THREE.Vector3(...contactWorld));
    const inverse=body.getWorldQuaternion(new THREE.Quaternion()).invert();
    const normal=new THREE.Vector3(...normalWorld).applyQuaternion(inverse).normalize();
    const wrist=resting.clone().lerp(contact.clone().addScaledVector(normal,.13),amount);
    const tip=resting.clone().addScaledVector(normal,-.13).lerp(contact,amount);
    const delta=wrist.clone().sub(shoulder),distance=delta.length(),axis=delta.normalize();
    const bend=new THREE.Vector3(rig.side,-.25,-.3).addScaledVector(axis,-new THREE.Vector3(rig.side,-.25,-.3).dot(axis)).normalize();
    const elbow=shoulder.clone().addScaledVector(axis,distance*.5).addScaledVector(bend,Math.sqrt(Math.max(0,.36*.36-distance*distance*.25)));
    segment(rig.upper,shoulder,elbow);segment(rig.lower,elbow,wrist);
    rig.palm.position.copy(wrist);segment(rig.finger,wrist,tip);rig.tip.position.copy(tip);
  }
  const phone = group(body, 'Phone', PHONE_POSE.position);
  phone.rotation.set(PHONE_POSE.rotationX,0,PHONE_POSE.rotationZ);
  const frame=box(phone,[.354,.714,.039],[0,0,0],material('#74817e',{metalness:.7,roughness:.3}),.032);
  frame.name='Phone frame';
  box(phone,[.341,.700,.042],[0,0,.001],'#17201e',.032);
  box(phone,[.312,.646,.006],[0,0,.024],material('#edf1ed',{roughness:.25}),.024);
  // Earpiece, camera, side keys and home indicator give it a phone silhouette.
  box(phone,[.069,.014,.003],[0,.290,.030],'#182320',.006);
  ball(phone,.008,[.053,.29,.031],'#182320',[1,1,.2]);
  box(phone,[.006,.063,.014],[.179,.15,0],'steel',.003);
  box(phone,[.006,.040,.014],[-.179,.17,0],'steel',.003);
  box(phone,[.006,.040,.014],[-.179,.11,0],'steel',.003);
  box(phone,[.090,.006,.002],[0,-.305,.029],'#8d9991',.003);
  label(phone,'9:41',.055,.026,[-.104,.29,.029],{background:'#edf1ed',color:'#273d32',size:.7});
  label(phone,'•••',.050,.026,[.104,.29,.029],{background:'#edf1ed',color:'#273d32',size:.65});
  box(phone,[.280,.276,.004],[0,.039,.029],'#ffffff',.018);
  label(phone,'INTERCOM',.238,.032,[0,.135,.032],{background:'#ffffff',color:'#74847b',size:.56});
  const visitorTitle=label(phone,'No visitor request',.244,.046,[0,.069,.032],{background:'#ffffff',color:'#233c30',size:.69});
  const deliveryTitle=label(phone,'Waiting for Jamie',.242,.037,[0,.014,.032],{background:'#ffffff',color:'#53685b',size:.65});
  const requestStatus=label(phone,'Intercom',.230,.031,[0,-.046,.032],{background:'#ffffff',color:'#85948b',size:.55});
  box(phone,[.133,.096,.003],[.076,-.205,.027],'#2d5542',.016);
  box(phone,[.133,.096,.003],[-.076,-.205,.027],'#dce4dd',.016);
  const yes=label(phone,'Yes',.108,.061,PHONE_CHOICES.yes,{background:'#2d5542',color:'#ffffff',size:.57});yes.name='Phone yes';
  const no=label(phone,'No',.108,.061,PHONE_CHOICES.no,{background:'#dce4dd',color:'#3e5346',size:.57});no.name='Phone no';
  yes.userData.phoneChoice='yes';no.userData.phoneChoice='no';
  phone.visible = false;
  let parcel=null;
  if (courier) {
    const yellow='#ffcc00',red='#d40511';
    ball(body,.33,[0,2.2,0],yellow,[1,.42,1]);
    box(body,[.49,.045,.37],[0,2.19,.24],yellow,.045);
    dhlLogo(body,.24,[0,2.22,.328]);
    box(body,[.69,.08,.014],[0,1.46,.207],red,.004);
    dhlLogo(body,.35,[0,1.22,.204]);
    const backLogo=dhlLogo(body,.45,[0,1.22,-.204]);
    backLogo.rotation.y=Math.PI;
    parcel=group(body,'DHL parcel',[-.08,1.22,.45]);
    box(parcel,[.86,.55,.44],[0,0,0],'#c99a64',.025);
    box(parcel,[.10,.006,.44],[0,.278,0],'#e5ca99',.002);
    box(parcel,[.10,.55,.006],[0,0,.224],'#e5ca99',.002);
    const shipping=dhlLogo(parcel,.27,[.22,.285,.015]);
    shipping.rotation.x=-Math.PI/2;
    for(let i=0;i<9;i++)box(parcel,[.012+(i%3)*.003,.003,.075],[.12+i*.023,.284,-.065],'charcoal',0);
  }
  const tag = label(root, courier ? 'DHL DELIVERY' : name.toUpperCase(), courier ? 1.75 : 1.2, .28, [0, 2.85, 0]);
  tag.material.depthWrite = false;
  const worldRotation = new THREE.Quaternion();
  function updateView(camera) {
    if (!camera || !tag.visible) return;
    root.updateWorldMatrix(true, false);
    root.getWorldQuaternion(worldRotation).invert();
    tag.quaternion.copy(worldRotation).multiply(camera.quaternion);
  }
  function update({ position: pos, yaw = 0, walking = false, ring = false, waving = false, usePhone = false, phoneAmount = usePhone?1:0, phoneTap = 0, phoneChoice = null, visitorRequest = null, delivered = false, reachTarget = null, reachNormal = [0,0,1], reachAmount = 0, showLabel = true, time = 0 }) {
    if (pos) root.position.fromArray(pos);
    if(parcel)parcel.visible=!delivered;
    root.rotation.y = yaw;
    const swing = walking ? Math.sin(time * 10) * .48 : 0;
    legs[0].rotation.x = swing; legs[1].rotation.x = -swing;
    body.position.y = walking ? Math.abs(Math.sin(time * 10)) * .055 : 0;
    arms[0].rotation.set(courier&&!delivered ? -.35 : -swing * .6, 0, courier ? -.06 : 0);
    arms[1].rotation.set(courier&&!delivered ? -.35 : swing * .6, 0, courier ? .06 : 0);
    elbows.forEach(elbow => elbow.rotation.set(courier&&!delivered ? -1 : -.12, 0, 0));
    if (ring) {
      arms[1].rotation.set(-1.13, 0, .32);
      elbows[1].rotation.x = -.25;
    }
    if (waving) {
      // Keep the greeting below shoulder height, clear of faces and the parcel.
      arms[1].rotation.set(-.15, 0, -.45 + Math.sin(time * 3) * .05);
      elbows[1].rotation.x = -.25;
    }
    phone.visible=phoneAmount>.001;
    visitorTitle.userData.setText(visitorRequest?.name?`${visitorRequest.name} is here`:'No visitor request');
    deliveryTitle.userData.setText(visitorRequest?.matched_records?.[0]?.title|| (visitorRequest?'Entry request':'Waiting for Jamie'));
    requestStatus.userData.setText(({pending:'Awaiting your approval',allowed:'Entry approved',denied:'Entry denied',expired:'Request expired',cancelled:'Call ended',arriving:'New visitor detected'})[visitorRequest?.status]||'Intercom');
    phone.position.set(PHONE_POSE.position[0],PHONE_POSE.position[1]-.45*(1-phoneAmount),PHONE_POSE.position[2]);
    phone.scale.setScalar(.8+.2*phoneAmount);
    arms.forEach(arm=>arm.visible=true);reachRigs.forEach(rig=>rig.rig.visible=false);
    if(phone.visible){
      body.updateWorldMatrix(true,true);
      const normal=new THREE.Vector3(0,0,1).transformDirection(phone.matrixWorld).toArray();
      const hold=phone.localToWorld(new THREE.Vector3(.155,-.255,.025)).toArray();
      reach(0,hold,normal,phoneAmount);
      const button=(phoneChoice==='no'?no:yes).getWorldPosition(new THREE.Vector3());
      const target=button.addScaledVector(new THREE.Vector3(...normal),.025).toArray();
      reach(1,target,normal,phoneAmount*phoneTap);
      yes.material.color.set(phoneChoice==='yes'&&phoneTap>.7?'#83c79c':'#ffffff');
      no.material.color.set(phoneChoice==='no'&&phoneTap>.7?'#e5bba1':'#ffffff');
    }else if(reachTarget)reach(1,reachTarget,reachNormal,reachAmount);
    tag.visible = showLabel;
    tag.quaternion.copy(root.quaternion).invert();
  }
  return { root, update, updateView, phone, phoneButtons:[yes,no] };
}

// Friendly low-poly surprise visitor, built from the same rounded materials.
export function createRaptor(parent){
  const root=group(parent,'Raptor visitor');root.visible=false;
  const body=group(root,'Raptor body');
  const green='#688965',light='#c9d5a4',dark='#354e3b',claw='#f1e6ce';
  function bone(mesh,a,b){mesh.position.copy(a).add(b).multiplyScalar(.5);mesh.scale.y=a.distanceTo(b);mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.clone().sub(a).normalize());}
  function limb(parent,a,b,r,color=green){
    const mesh=cylinder(parent,r,1,[0,0,0],color,r*.8);bone(mesh,new THREE.Vector3(...a),new THREE.Vector3(...b));return mesh;
  }
  // Forward-leaning hips and chest, with a pale throat and belly.
  const torso=ball(body,.53,[0,1.13,-.05],green,[.72,.96,1.28]);torso.rotation.x=.28;
  ball(body,.32,[0,1.35,.29],light,[.82,1.28,.52]);
  const neck=ball(body,.25,[0,1.72,.28],green,[.9,1.5,1]);neck.rotation.x=.27;
  ball(body,.2,[0,1.68,.43],light,[.76,1.35,.58]);
  // A long, tapered tail counterbalances the head instead of a short cone.
  const tail=group(body,'Sweeping tail');
  const curve=new THREE.CatmullRomCurve3([new THREE.Vector3(0,1.15,-.38),new THREE.Vector3(.04,1.06,-1.05),new THREE.Vector3(.19,1.2,-1.8),new THREE.Vector3(.38,1.42,-2.45)]);
  const vertices=[],indices=[],rings=24,sides=12;
  for(let i=0;i<=rings;i++){
    const t=i/rings,center=curve.getPoint(t),tangent=curve.getTangent(t).normalize();
    const side=new THREE.Vector3(0,1,0).cross(tangent).normalize(),up=tangent.clone().cross(side).normalize();
    const radius=.23*Math.pow(1-t,1.2)+.006;
    for(let j=0;j<sides;j++){
      const angle=j/sides*Math.PI*2,point=center.clone().addScaledVector(side,Math.cos(angle)*radius).addScaledVector(up,Math.sin(angle)*radius);
      vertices.push(point.x,point.y,point.z);
      if(i<rings){const a=i*sides+j,b=i*sides+(j+1)%sides;indices.push(a,b,a+sides,b,b+sides,a+sides);}
    }
  }
  const tailGeometry=new THREE.BufferGeometry();tailGeometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));tailGeometry.setIndex(indices);tailGeometry.computeVertexNormals();
  const tailMesh=new THREE.Mesh(tailGeometry,material(green));tailMesh.castShadow=true;tailMesh.receiveShadow=true;tail.add(tailMesh);
  // Wedge-shaped muzzle, separate lower jaw, nostrils and alert amber eyes.
  const head=group(body,'Raptor head',[0,2.03,.42]);
  ball(head,.31,[0,.08,0],green,[1.05,.92,1.05]);
  box(head,[.50,.27,.57],[0,-.01,.32],green,.10);
  const jaw=group(head,'Lower jaw',[0,-.13,.02]);
  box(jaw,[.43,.085,.51],[0,-.06,.29],light,.025);
  box(head,[.46,.023,.44],[0,-.125,.34],dark,.008);
  for(const side of [-1,1]){
    ball(head,.123,[side*.285,.16,.15],'#dfb950',[.43,1,1]);
    ball(head,.07,[side*.337,.16,.18],dark,[.24,1.1,.7]);
    ball(head,.025,[side*.354,.19,.195],'ivory',[.3,1,1]);
    const brow=box(head,[.09,.07,.25],[side*.29,.27,.13],dark,.024);brow.rotation.x=-.13;
    ball(head,.027,[side*.185,.035,.608],dark,[1,.7,.4]);
    for(let i=0;i<4;i++){
      const tooth=cylinder(head,.024,.065,[side*.205,-.15,.16+i*.105],claw,0);tooth.rotation.z=Math.PI;
    }
    // Subtle flank markings read at presentation distance.
    for(let i=0;i<3;i++){
      const stripe=ball(body,.11,[side*(.36-i*.025),1.15+i*.11,-.28+i*.16],dark,[.20,1.3,.7]);stripe.rotation.x=-.5;
    }
  }
  const legs=[-1,1].map(side=>{
    const leg=group(body,'Bent raptor leg',[side*.31,1.02,-.12]);
    const thigh=ball(leg,.24,[0,-.22,.12],green,[.9,1.3,1]);thigh.rotation.x=-.45;
    limb(leg,[0,-.35,.22],[0,-.68,-.07],.095);
    ball(leg,.105,[0,-.68,-.07],green);
    limb(leg,[0,-.68,-.07],[0,-.92,.12],.065);
    box(leg,[.25,.105,.31],[0,-.96,.22],green,.04);
    for(const x of [-.09,0,.09]){
      limb(leg,[x,-.955,.26],[x,-.98,.48],.034);
      const nail=cylinder(leg,.042,.16,[x,-.98,.53],claw,0);nail.rotation.x=Math.PI/2;
    }
    // The lifted inner sickle claw makes the silhouette unmistakably raptor-like.
    const sickle=cylinder(leg,.065,.24,[-side*.15,-.81,.37],dark,0);sickle.rotation.x=.72;
    return leg;
  });
  const upper=box(body,[.15,1,.15],[0,0,0],green,.045);
  const lower=box(body,[.11,1,.11],[0,0,0],green,.035);
  function makeHand(side){
    const hand=group(body,'Clawed hand');ball(hand,.085,[0,0,0],green,[1,.7,1.2]);
    for(let i=0;i<3;i++){
      const x=(i-1)*.052;
      limb(hand,[x,0,.035],[x,-.015,.14],.023);
      const nail=cylinder(hand,.022,.10,[x,-.035,.17],claw,0);nail.rotation.x=1.1;
    }
    return hand;
  }
  const hand=makeHand(1),other=makeHand(-1);other.position.set(-.42,1.29,.57);
  limb(body,[-.33,1.57,.23],[-.49,1.35,.39],.072);
  limb(body,[-.49,1.35,.39],[-.42,1.29,.57],.055);
  const mouthInterior=box(head,[.40,.59,.22],[0,-.37,.31],'#241717',.06);mouthInterior.visible=false;
  const tongue=box(jaw,[.27,.025,.28],[0,-.007,.34],'#bc7777',.02);
  for(const x of [-.16,-.08,0,.08,.16]){
    const tooth=cylinder(jaw,.027,.085,[x,.045,.50],claw,0);
  }
  const mouth=group(head,'Bite point',[0,-.11,.57]);
  function update({position,yaw,walking,press,bite=0,viewerBite=0,scale=1,time=0}){
    root.visible=Boolean(position);if(!position)return;
    root.position.fromArray(position);root.rotation.y=yaw;root.scale.setScalar(scale);
    body.position.y=walking?Math.abs(Math.sin(time*9))*.05:Math.sin(time*2)*.012;
    legs.forEach((leg,i)=>leg.rotation.x=walking?Math.sin(time*9+i*Math.PI)*.36:0);
    tail.rotation.y=Math.sin(time*2)*.07;head.rotation.z=Math.sin(time*1.7)*.025;
    const ease=(a,b)=>{const t=Math.max(0,Math.min(1,(bite-a)/(b-a)));return t*t*(3-2*t);};
    const lunge=ease(.08,.36)*(1-ease(.48,.7));
    body.position.x=.20*lunge;
    head.position.set(.24*lunge,2.03-.22*lunge,.42+.02*lunge-.22*ease(.48,.72));
    head.rotation.x=.08*lunge+Math.sin(bite*45)*.04*ease(.58,.7)*(1-ease(.88,1));
    jaw.rotation.x=.65*ease(.05,.25)*(1-ease(.35,.47)) + Math.max(0,Math.sin(bite*55))*.22*ease(.6,.7)*(1-ease(.9,1));
    if(viewerBite>0){
      head.rotation.z=0;head.rotation.x=-.05*viewerBite;
      jaw.rotation.x=Math.max(jaw.rotation.x,1.1*viewerBite);
    }
    mouthInterior.visible=viewerBite>.1;
    if(bite>0)press*=1-ease(0,.15);
    root.updateWorldMatrix(true,true);
    const shoulder=new THREE.Vector3(.34,1.58,.24),rest=new THREE.Vector3(.44,1.24,.60);
    const touch=body.worldToLocal(new THREE.Vector3(2.5,1.7,10.874));touch.z-=.17;
    const target=rest.lerp(touch,press);
    const elbow=shoulder.clone().lerp(target,.5).add(new THREE.Vector3(.18,-.1,0));
    bone(upper,shoulder,elbow);bone(lower,elbow,target);hand.position.copy(target);
  }
  return {root,update,mouth};
}
