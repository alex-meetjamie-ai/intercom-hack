import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { journeyFrame, blendFrames, presentationFor } from './camera.js';
import { sampleJourney, stops } from './journey.js';

function cameraFor(frame,aspect){
  const camera=new THREE.OrthographicCamera(-frame.size*aspect/2,frame.size*aspect/2,frame.size/2,-frame.size/2,.1,220);
  camera.position.fromArray(frame.position);camera.lookAt(new THREE.Vector3(...frame.target));camera.updateMatrixWorld();return camera;
}
test('each camera action starts exactly where the preceding action ends',()=>{
  for(const aspect of [.6,1,1.8,2.3])for(let next=1;next<stops.length;next++){
    const a=journeyFrame(next-1,1,aspect),b=journeyFrame(next,0,aspect);
    for(const property of ['position','target'])assert.ok(new THREE.Vector3(...a[property]).distanceTo(new THREE.Vector3(...b[property]))<1e-9,`${next}: ${property}`);
    assert.ok(Math.abs(a.size-b.size)<1e-9);
  }
});
test('the courier remains in the tracking shot throughout walking, boarding and arrival',()=>{
  for(const aspect of [.6,1,1.8,2.3])for(const index of [3,4,5])for(let n=0;n<=100;n++){
    const progress=n/100,frame=journeyFrame(index,progress,aspect),camera=cameraFor(frame,aspect);
    const state=sampleJourney(index,progress);
    for(const height of [0,1.5,3]){
      const point=new THREE.Vector3(...state.visitor);point.y+=height;point.project(camera);
      assert.ok(Math.abs(point.x)<.85&&Math.abs(point.y)<.85,`${index} p=${progress} aspect=${aspect}: courier in frame`);
      assert.ok(Math.abs(point.z)<1,'courier clear of near and far planes');
    }
  }
});
test('the middle of the lift ride tracks the cabin elevation exactly',()=>{
  for(const p of [.34,.45,.55,.65,.72]){
    const frame=journeyFrame(4,p),state=sampleJourney(4,p);
    assert.ok(Math.abs(frame.target[1]-state.liftY-2.8)<1e-9);
    assert.ok(Math.abs(frame.target[0]-state.visitor[0])<1e-9);
  }
});
test('camera samples are continuous within actions and orbit return preserves its endpoints',()=>{
  for(let index=0;index<6;index++){
    let previous=journeyFrame(index,0);
    for(let n=1;n<=1000;n++){
      const frame=journeyFrame(index,n/1000);
      assert.ok([...frame.position,...frame.target,frame.size].every(Number.isFinite));
      assert.ok(new THREE.Vector3(...frame.position).distanceTo(new THREE.Vector3(...frame.target))>79.99);
      assert.ok(new THREE.Vector3(...frame.position).distanceTo(new THREE.Vector3(...previous.position))<.5,`camera jump in stage ${index}`);
      assert.ok(Math.abs(frame.size-previous.size)<.4);previous=frame;
    }
  }
  const source=journeyFrame(0,1),destination=journeyFrame(3,.3);
  assert.deepEqual(blendFrames(source,destination,1),destination);
  const first=blendFrames(source,destination,0);
  assert.ok(new THREE.Vector3(...source.position).distanceTo(new THREE.Vector3(...first.position))<1e-9);
});
test('every step retains the same connected architecture',()=>{
  for(let i=0;i<6;i++)assert.deepEqual(presentationFor(i),{street:1,courtyard:1,loft:1,terrace:1,shaft:1,lowerShaft:1});
});
