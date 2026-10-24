import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createWorld} from './world.js';
import {sampleJourney} from './journey.js';
import {journeyFrame,presentationFor} from './camera.js';
import {TERRACE,OFFICE_DOOR,LIFT_POSITION,LIFT_OPENING,REAR_PASSAGE,REAR_BUILDING} from './layout.js';

globalThis.document={createElement:()=>({width:0,height:0,getContext:()=>({fillRect(){},fillText(){}})})};
test('the same building and lower shaft remain present for every action',()=>{
  const world=createWorld();
  for(let index=0;index<6;index++)for(const progress of [0,.25,.5,.75,1]){
    world.update({...sampleJourney(index,progress),presentation:presentationFor()},1);
    for(const name of ['street','courtyard','loft','terrace','shaft','lowerShaft'])assert.equal(world.layers[name].visible,true,`${name} at ${index}/${progress}`);
  }
});
test('the rendered courier and pizza fit the moving camera throughout the route',()=>{
  const world=createWorld(),courier=world.group.getObjectByName('Courier');
  for(const aspect of [.6,1.8])for(const index of [3,4,5])for(let n=0;n<=50;n++){
    const progress=n/50,frame=journeyFrame(index,progress,aspect);
    const camera=new THREE.OrthographicCamera(-frame.size*aspect/2,frame.size*aspect/2,frame.size/2,-frame.size/2,.1,220);
    camera.position.fromArray(frame.position);camera.lookAt(new THREE.Vector3(...frame.target));camera.updateMatrixWorld();
    world.update({...sampleJourney(index,progress),presentation:presentationFor()},1,camera);world.group.updateMatrixWorld(true);
    const bounds=new THREE.Box3().setFromObject(courier);
    for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z]){
      const p=new THREE.Vector3(x,y,z).project(camera);
      assert.ok(Math.abs(p.x)<1&&Math.abs(p.y)<1&&Math.abs(p.z)<1,`courier at ${index}/${progress}, aspect ${aspect}`);
    }
  }
});

test('office spans the rear with a compact terrace attached along its front edge',()=>{
  const world=createWorld(),office=world.layers.loft;
  assert.equal(office.rotation.y,0,'office is parallel to street frontage');
  world.group.updateMatrixWorld(true);
  const floor=new THREE.Box3().setFromObject(office.children[0]);
  assert.ok(floor.max.x-floor.min.x>floor.max.z-floor.min.z);
  assert.ok(Math.abs(TERRACE.back-floor.max.z)<1e-6,'terrace joins the long courtyard-facing edge');
  assert.ok(TERRACE.right<0,'attachment is to the approaching courier’s left');
  assert.ok(TERRACE.right-TERRACE.left<(floor.max.x-floor.min.x)*.5,'compact annex, not a full side balcony');
  assert.ok(TERRACE.front-TERRACE.back<5,'short projection into courtyard');
  assert.ok(LIFT_OPENING.left>TERRACE.left&&LIFT_OPENING.right<TERRACE.right);
  assert.ok(LIFT_OPENING.back>TERRACE.back&&LIFT_OPENING.front<TERRACE.front);
  assert.ok(OFFICE_DOOR[0]<LIFT_POSITION[0],'terrace connects from lift towards door');
  const door=world.group.getObjectByName('Main office door');
  const direction=new THREE.Vector3(0,0,1).transformDirection(door.matrixWorld);
  assert.ok(direction.z>.99,'door faces the courtyard attachment');
});
test('the corner lift keeps right-side ground entry and opens toward the shifted deck upstairs',()=>{
  const world=createWorld(),leaves=[];
  world.group.traverse(obj=>{if(obj.userData.portal)leaves.push(obj);});
  assert.equal(leaves.length,8);
  world.group.updateMatrixWorld(true);
  const entrance=world.group.getObjectByName('Right-side elevator entrance');
  const facing=new THREE.Vector3(0,0,1).transformDirection(entrance.matrixWorld);
  assert.ok(facing.x>.99&&Math.abs(facing.z)<1e-9,'entry faces right');
  assert.ok(Math.abs(LIFT_POSITION[0]-1.52-(-10.6))<.3,'lift fits beside left wall');
  assert.ok(Math.abs(LIFT_POSITION[2]-1.41-(-8.15))<.3,'lift fits beside rear wall');
  for(const [stage,p,openPortal] of [[3,1,'right'],[4,.5,null],[4,1,'terrace']]){
    world.update({...sampleJourney(stage,p),presentation:presentationFor()},1);
    for(const leaf of leaves){
      const expected=leaf.userData.portal===openPortal?leaf.userData.open:leaf.userData.closed;
      assert.ok(Math.abs(Math.abs(leaf.position.x)-expected)<1e-9);
    }
  }
});

test('only the roof and interior turn while the floor, lift and terrace stay fixed',()=>{
  const world=createWorld();world.group.updateMatrixWorld(true);
  const roof=world.group.getObjectByName('Rotated office roof');
  const room=world.group.getObjectByName('Rotated office interior');
  assert.ok(Math.abs(roof.rotation.y+Math.PI/2)<1e-9);
  assert.ok(Math.abs(room.rotation.y+Math.PI/2)<1e-9);
  assert.deepEqual(world.layers.shaft.position.toArray(),LIFT_POSITION);
  assert.deepEqual(world.layers.terrace.position.toArray(),[0,16,0]);
  const floor=new THREE.Box3().setFromObject(world.layers.loft.children[0]);
  for(const object of [roof,room]){
    const bounds=new THREE.Box3().setFromObject(object);
    assert.ok(bounds.min.x>=floor.min.x-.01&&bounds.max.x<=floor.max.x+.01);
    assert.ok(bounds.min.z>=floor.min.z-.01&&bounds.max.z<=floor.max.z+.01);
  }
});

test('the unchanged lift sits at the right-hand end of the shifted terrace',()=>{
  assert.deepEqual(LIFT_POSITION,[-9,0,-6.55]);
  assert.ok(TERRACE.right-LIFT_OPENING.right<.1);
  assert.ok(LIFT_OPENING.left-TERRACE.left>6);
  const world=createWorld();world.group.updateMatrixWorld(true);
  const entrance=world.group.getObjectByName('Terrace elevator exit');
  assert.ok(new THREE.Vector3(0,0,1).transformDirection(entrance.matrixWorld).x<-.99);
});

test('rear tunnel is open through the entire brick block with solid sides and ceiling',()=>{
  const world=createWorld();world.group.updateMatrixWorld(true);
  const {centerX,width,height}=REAR_PASSAGE;
  const {front,back}=REAR_BUILDING;
  const hits=(x,y)=>new THREE.Raycaster(new THREE.Vector3(x,y,front+.2),new THREE.Vector3(0,0,-1),0,front-back+.4).intersectObject(world.layers.courtyard,true);
  for(const x of [centerX-1.3,centerX,centerX+1.3])for(const y of [.5,1.6,3.7]){
    assert.equal(hits(x,y).length,0,`clear passage at ${x}/${y}`);
  }
  assert.ok(hits(centerX,height+.3).length>0,'building spans above the tunnel');
  assert.ok(hits(centerX-width/2-.3,1.6).length>0,'left side remains solid');
  assert.ok(hits(centerX+width/2+.3,1.6).length>0,'right side remains solid');
});

test('right extension joins the courtyard wing and has a continuous roof',()=>{
  const world=createWorld();world.group.updateMatrixWorld(true);
  const extension=world.group.getObjectByName('Right roof extension');
  const roof=new THREE.Box3().setFromObject(extension);
  const original=new THREE.Box3().setFromObject(world.layers.loft.children[0]);
  assert.ok(Math.abs(roof.min.x-original.max.x)<1e-6);
  assert.ok(Math.abs(roof.max.x-REAR_BUILDING.right)<1e-6);
  assert.equal(REAR_BUILDING.right,11);
  assert.equal(REAR_PASSAGE.centerX,-2.2);
  assert.deepEqual(LIFT_POSITION,[-9,0,-6.55]);
});
