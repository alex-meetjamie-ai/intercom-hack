import * as THREE from 'three';
import { group, box, ball, cylinder, label, material } from './geometry.js';
import {PHONE_POSE,PHONE_CHOICES} from './layout.js';

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
  label(phone,'Someone is here',.244,.046,[0,.069,.032],{background:'#ffffff',color:'#233c30',size:.69});
  const deliveryTitle=label(phone,'Pizza delivery',.242,.037,[0,.014,.032],{background:'#ffffff',color:'#53685b',size:.65});
  const waitingTitle=label(phone,'Waiting outside',.242,.037,[0,.014,.033],{background:'#ffffff',color:'#a36b3a',size:.57});
  label(phone,'Street entrance',.230,.031,[0,-.046,.032],{background:'#ffffff',color:'#85948b',size:.55});
  box(phone,[.133,.096,.003],[.076,-.205,.027],'#2d5542',.016);
  box(phone,[.133,.096,.003],[-.076,-.205,.027],'#dce4dd',.016);
  const yes=label(phone,'Yes',.108,.061,PHONE_CHOICES.yes,{background:'#2d5542',color:'#ffffff',size:.57});yes.name='Phone yes';
  const no=label(phone,'No',.108,.061,PHONE_CHOICES.no,{background:'#dce4dd',color:'#3e5346',size:.57});no.name='Phone no';
  yes.userData.phoneChoice='yes';no.userData.phoneChoice='no';
  phone.visible = false;
  let pizza;
  if (courier) {
    ball(body, .33, [0, 2.2, 0], 'coral', [1, .42, 1]);
    box(body, [.49, .045, .37], [0, 2.19, .24], 'coral', .045);
    box(body, [.68, .79, .36], [0, 1.16, -.34], 'coral', .08);
    pizza = group(body, 'Pizza boxes', [0, 1.31, .72]);
    for (const y of [0, .15]) {
      box(pizza, [.96, .13, .91], [0, y, 0], 'ivory', .035);
      box(pizza, [.99, .027, .94], [0, y + .066, 0], 'coral', .01);
    }
    const pizzaLabel = label(pizza, 'PIZZA', .66, .29, [0, .234, 0], { color: '#b95642', background: '#fcf6e9', size: .67 });
    pizzaLabel.rotation.x = -Math.PI / 2;
  }
  const tag = label(root, courier ? 'PIZZA DELIVERY' : name.toUpperCase(), courier ? 1.75 : 1.2, .28, [0, 2.85, 0]);
  tag.material.depthWrite = false;
  const worldRotation = new THREE.Quaternion();
  function updateView(camera) {
    if (!camera || !tag.visible) return;
    root.updateWorldMatrix(true, false);
    root.getWorldQuaternion(worldRotation).invert();
    tag.quaternion.copy(worldRotation).multiply(camera.quaternion);
  }
  function update({ position: pos, yaw = 0, walking = false, ring = false, waving = false, usePhone = false, phoneAmount = usePhone?1:0, phoneTap = 0, phoneChoice = null, reachTarget = null, reachNormal = [0,0,1], reachAmount = 0, showLabel = true, time = 0 }) {
    if (pos) root.position.fromArray(pos);
    root.rotation.y = yaw;
    const swing = walking ? Math.sin(time * 10) * .48 : 0;
    legs[0].rotation.x = swing; legs[1].rotation.x = -swing;
    body.position.y = walking ? Math.abs(Math.sin(time * 10)) * .055 : 0;
    arms[0].rotation.set(courier ? -.35 : -swing * .6, 0, courier ? -.06 : 0);
    arms[1].rotation.set(courier ? -.35 : swing * .6, 0, courier ? .06 : 0);
    elbows.forEach(elbow => elbow.rotation.set(courier ? -1 : -.12, 0, 0));
    if (ring) {
      arms[1].rotation.set(-1.13, 0, .32);
      elbows[1].rotation.x = -.25;
    }
    if (waving) {
      arms[1].rotation.set(-.15, 0, -2.1 + Math.sin(time * 6) * .15);
      elbows[1].rotation.x = -.4;
    }
    phone.visible=phoneAmount>.001;
    waitingTitle.visible=phoneChoice==='no'&&phoneTap===0;deliveryTitle.visible=!waitingTitle.visible;
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
