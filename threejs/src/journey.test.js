import test from 'node:test';
import assert from 'node:assert/strict';
import {sampleJourney,stops,TOP,STREET,WAITING,CABIN,route,atTime,boundaries} from './journey.js';
import {journeyFrame} from './camera.js';
import {OFFICE_DOOR,TERRACE,officeLocal,LIFT_OPENING} from './layout.js';

test('arrival and approval keep the entrance locked until the decision',()=>{
  assert.equal(sampleJourney(0,1).streetDoor,0);
  assert.equal(sampleJourney(1,1).streetDoor,0);
  assert.equal(sampleJourney(2,0).streetDoor,0);
  assert.equal(sampleJourney(2,1).streetDoor,1);
});
test('courier follows the courtyard route before the lift arrives',()=>{
  assert.deepEqual(sampleJourney(3,0).visitor,STREET);
  assert.deepEqual(sampleJourney(3,1).visitor,WAITING);
  assert.equal(sampleJourney(3,0).liftY,TOP);
  assert.equal(sampleJourney(3,1).liftY,0);
  assert.equal(sampleJourney(3,.5).liftDoor,0);
  assert.equal(sampleJourney(3,1).liftDoor,1);
});
test('lift moves only after boarding with closed doors and carries the courier',()=>{
  for(const p of [.35,.5,.7,.8]) {
    const s=sampleJourney(4,p);
    assert.equal(s.liftDoor,0);
    assert.equal(s.visitor[1],s.liftY);
    assert.equal(s.walking,false);
    assert.equal(s.visitor[0],CABIN[0]);assert.equal(s.visitor[2],CABIN[2]);
  }
  assert.equal(sampleJourney(4,1).liftY,TOP);
  assert.equal(sampleJourney(4,1).liftDoor,1);
});
test('arrival remains continuous between walking, boarding, and rooftop exit',()=>{
  for(const [a,b] of [[2,3],[3,4],[4,5]]) {
    const previous=sampleJourney(a,1),next=sampleJourney(b,0);
    assert.deepEqual(previous.visitor,next.visitor);
    assert.equal(previous.liftY,next.liftY);
    assert.equal(previous.liftDoor,next.liftDoor);
  }
  assert.equal(sampleJourney(5,1).greet,1);
  assert.equal(sampleJourney(5,1).officeDoor,1);
  assert.equal(sampleJourney(5,1).visitor[1],TOP);
});
test('all stops and camera paths can be sought independently with finite values',()=>{
  stops.forEach((_,i)=>{
    for(const p of [0,.2,.5,.8,1]) {
      const s=sampleJourney(i,p),c=journeyFrame(i,p);
      assert.ok([...s.visitor,...s.egor,s.liftY,...c.position,...c.target,c.size].every(Number.isFinite));
      assert.ok(s.liftDoor>=0&&s.liftDoor<=1);
    }
  });
  assert.deepEqual(sampleJourney(0,1).visitor,STREET);
});
test('path interpolation follows corners and clamps both ends',()=>{
  assert.deepEqual(route([[0,0,0],[2,0,0],[2,0,2]],-.1).position,[0,0,0]);
  assert.deepEqual(route([[0,0,0],[2,0,0],[2,0,2]],.5).position,[2,0,0]);
  assert.deepEqual(route([[0,0,0],[2,0,0],[2,0,2]],2).position,[2,0,2]);
});

test('courier and pizza pass through the center of the street doorway',()=>{
  let samples=0;
  for(let n=0;n<=1000;n++){
    const s=sampleJourney(3,n/1000);
    if(s.visitor[2]>9.5&&s.visitor[2]<11.2){
      assert.ok(Math.abs(s.visitor[0])<.1,'courier is centered in the arch');samples++;
    }
  }
  assert.ok(samples>0);
});
test('Egor crosses the courtyard-facing doorway only after it opens',()=>{
  let crossed=false;
  for(let n=0;n<=100;n++){
    const s=sampleJourney(5,n/100);
    if(s.egor[2]>OFFICE_DOOR[2]){
      crossed=true;assert.equal(s.officeDoor,1);
      assert.ok(Math.abs(officeLocal(s.egor)[0]+6)<.8);
    }
  }
  assert.equal(crossed,true);
});

test('all physical state is continuous across forward and reverse stop boundaries',()=>{
  for(let next=1;next<6;next++){
    const a=sampleJourney(next-1,1),b=sampleJourney(next,0);
    for(const key of ['visitor','egor'])a[key].forEach((value,i)=>assert.ok(Math.abs(value-b[key][i])<1e-9,`${next} ${key}`));
    for(const key of ['streetDoor','liftY','liftDoor','officeDoor','facade','leftWing','phone','notification','ring','greet'])assert.ok(Math.abs(a[key]-b[key])<1e-9,`${next} ${key}`);
    for(const key of ['visitorYaw','egorYaw'])assert.ok(Math.abs(Math.sin((a[key]-b[key])/2))<1e-9,`${next} ${key}`);
    const before=atTime(boundaries[next]-.001).state,after=atTime(boundaries[next]+.001).state;
    assert.ok(Math.hypot(...before.visitor.map((v,i)=>v-after.visitor[i]))<.001,'no teleport when crossing either direction');
  }
});
test('the playhead stays on its traversed route while rewinding or skipping',()=>{
  let previous=atTime(boundaries.at(-1)).state;
  for(let t=boundaries.at(-1)-10;t>=0;t-=10){
    const state=atTime(t).state;
    assert.ok(Math.hypot(...previous.visitor.map((v,i)=>v-state.visitor[i]))<.1,'continuous reverse journey');
    assert.ok(Math.abs(previous.liftY-state.liftY)<.1,'continuous reverse lift');previous=state;
  }
});

test('the rooftop route stays within the compact attached terrace',()=>{
  let exited=false;
  for(let n=0;n<=1000;n++){
    const [x,,z]=sampleJourney(5,n/1000).visitor;
    if(x<LIFT_OPENING.left-.3)exited=true;
    assert.ok(x>TERRACE.left+.5&&x<TERRACE.right-.5);
    assert.ok(z>TERRACE.back+.5&&z<TERRACE.front-.5);
    if(exited)assert.ok(x<LIFT_OPENING.left-.3,'courier stays clear of shaft after exit');
  }
  assert.equal(exited,true);
});

test('the courier approaches and boards horizontally from the right',()=>{
  assert.ok(WAITING[0]>CABIN[0]);assert.equal(WAITING[2],CABIN[2]);
  let previous=WAITING[0];
  for(let n=3;n<=20;n++){
    const state=sampleJourney(4,n/100);
    assert.ok(state.visitor[0]<=previous,'walks left into the cabin');
    assert.equal(state.visitor[2],CABIN[2]);
    assert.ok(Math.abs(state.visitorYaw+Math.PI/2)<1e-9);
    previous=state.visitor[0];
  }
});
