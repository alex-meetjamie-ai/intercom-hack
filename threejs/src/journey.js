// A deterministic timeline: every stop can be replayed or revisited independently.
import {TOP,ROOM_ROTATION,roomPoint,officePoint,HOST_LANDING,COURIER_LANDING,LIFT_POSITION} from './layout.js';
export {TOP} from './layout.js';
export const STREET = [2.5, 0, 11.55];
export const WAITING = [LIFT_POSITION[0]+2.7, 0, LIFT_POSITION[2]];
export const CABIN = [...LIFT_POSITION];
export const DESK = roomPoint([.15,0,3.8]);
export const clamp = x => Math.max(0, Math.min(1, x));
export const smooth = x => { const t = clamp(x); return t * t * (3 - 2 * t); };
export const phase = (p, a, b) => smooth((p - a) / (b - a));
const lerp = (a, b, p) => a + (b - a) * p;

export function route(points, p) {
  if (p >= 1) {
    const a=points.at(-2),b=points.at(-1);
    return {position:[...b],yaw:Math.atan2(b[0]-a[0],b[2]-a[2])};
  }
  const lengths = points.slice(1).map((b, i) => Math.hypot(...b.map((v, j) => v - points[i][j])));
  let remaining = clamp(p) * lengths.reduce((a, b) => a + b, 0);
  for (let i = 0; i < lengths.length; i++) {
    if (remaining <= lengths[i] || i === lengths.length - 1) {
      const a = points[i], b = points[i + 1], t = lengths[i] ? Math.min(1, remaining / lengths[i]) : 1;
      return { position: a.map((v, j) => lerp(v, b[j], t)), yaw: Math.atan2(b[0] - a[0], b[2] - a[2]) };
    }
    remaining -= lengths[i];
  }
}

export function sampleJourney(index, progress) {
  const p = clamp(progress);
  const s = {
    visitor: [...STREET], visitorYaw: Math.PI, walking: false, ring: 0,
    stage:index, focus:['street','office','street','courtyard','lift','terrace'][index],
    egor: [...DESK], egorYaw: .2+ROOM_ROTATION, phone: 0, notification: 0, approved: 0,
    streetDoor: 0, liftY: TOP, liftDoor: 0, officeDoor: 0, greet: 0, facade: 1, leftWing:1,
  };
  if (index === 0) s.ring = phase(p, .15, .5);
  if (index >= 1) s.ring = index === 1 ? 1 - phase(p, 0, .15) : 0;
  if (index === 1) { s.phone = phase(p, .60, .82); s.notification = phase(p, .72, .95); s.facade=1-.94*phase(p,.08,.4); }
  if (index === 2) { s.approved = 1; s.phone=1-phase(p,0,.18); s.notification=1-phase(p,0,.18); s.streetDoor = phase(p, .65, .96); s.facade=.06+.94*phase(p,.5,.82); }
  if (index >= 3) { s.approved = 1; s.streetDoor = 1; s.facade = index === 3 ? 1 - .94*phase(p, .04, .27) : .06; }
  if (index === 3) {
    const walk = walkingRoute([STREET, [0, 0, 12.3], [0, 0, 8], [0, 0, LIFT_POSITION[2]], WAITING], phase(p, .1, .64));
    s.visitor = walk.position; s.visitorYaw = turn(Math.PI, walk.yaw, phase(p,0,.1));
    if(p>.60)s.visitorYaw=turn(s.visitorYaw,-Math.PI/2,phase(p,.60,.68));
    s.walking = p > .1 && p < .64;
    s.liftY = TOP * (1 - phase(p, .64, .9));
    s.liftDoor = phase(p, .9, 1);
  }
  if (index === 4) {
    const enter = walkingRoute([WAITING, CABIN], phase(p, .03, .2));
    s.liftY = TOP * phase(p, .32, .82);
    s.leftWing=1-.94*phase(p,.28,.55);
    s.visitor = [enter.position[0], s.liftY, enter.position[2]];
    s.visitorYaw = -Math.PI/2;
    s.walking = p > .03 && p < .2;
    s.liftDoor = 1 - phase(p, .2, .3) + phase(p, .86, .98);
  }
  if (index === 5) {
    s.leftWing=.06;
    const walk = walkingRoute([[CABIN[0], TOP, CABIN[2]], [-11.1, TOP, CABIN[2]], [COURIER_LANDING[0], TOP, CABIN[2]], COURIER_LANDING], phase(p, .12, .76));
    s.visitor = walk.position; s.visitorYaw = turn(-Math.PI/2,walk.yaw,phase(p,.08,.17));
    if(p>.72)s.visitorYaw=turn(s.visitorYaw,Math.PI,phase(p,.72,.84));
    s.walking = p > .12 && p < .76;
    const host = walkingRoute([DESK, officePoint([-6,0,4.8]), HOST_LANDING], phase(p, .08, .62));
    s.egor = host.position; s.egorYaw = turn(.2+ROOM_ROTATION,host.yaw,phase(p,.03,.12));
    if(p>.58)s.egorYaw=turn(s.egorYaw,0,phase(p,.58,.7));
    s.egorWalking = p > .08 && p < .62;
    s.liftDoor = 1; s.officeDoor = phase(p, .07, .25); s.greet = phase(p, .68, .9);
  }
  return s;
}

export const stops = [
  {
    id: 'doorbell', category: '01 / LINIENSTRASSE 144', caption: 'AT THE STREET DOOR',
    title: 'Good things come in pizza boxes.',
    description: 'Our courier rings the intercom at the street entrance. Someone upstairs gets the message.',
    hero: ['Pizza’s here.', 'Almost.'], note: 'A little delivery, from the street to our rooftop.',
    duration: 2200,
    nextLabel: 'Next',
  },
  {
    id: 'notification', category: '02 / THE ROOFTOP OFFICE', caption: 'EGOR’S WORKSPACE',
    title: 'Egor, there’s someone downstairs.',
    description: 'A push notification arrives. Egor checks who’s at the door and decides whether to let them in.',
    hero: ['A little ping.', 'A big decision.'], note: 'The delivery starts with a yes from upstairs.',
    duration: 6200,
    nextLabel: 'Let them in',
  },
  {
    id: 'access-granted', category: '03 / BACK AT THE ENTRANCE', caption: 'THE DOOR IS OPEN',
    title: '“Yes! Come on through.”',
    description: 'Egor lets the courier in. Through the courtyard, then left to the lift — we’ll bring you up.',
    hero: ['Come on in.', 'We’re upstairs.'], note: 'The familiar directions. You know the ones.',
    duration: 5600,
    nextLabel: 'Next',
  },
  {
    id: 'courtyard', category: '04 / THROUGH THE COURTYARD', caption: 'LEFT TO THE ELEVATOR',
    title: 'Through the courtyard. Left to the lift.',
    description: 'Past the trees to the far-left corner. The courier approaches the lift from its right side and waits for it to come down.',
    hero: ['A courtyard.', 'A small detour.'], note: 'A few footsteps closer to lunch.',
    duration: 11000,
    nextLabel: 'Next',
  },
  {
    id: 'elevator-ride', category: '05 / ALL THE WAY UP', caption: 'NEXT STOP: THE TOP',
    title: 'Going up. Pizza included.',
    description: 'The courier steps in, the doors close, and the glass lift carries our lunch to the top floor.',
    hero: ['One lift.', 'All the way up.'], note: 'Keep an eye on that little glass elevator.',
    duration: 11000,
    nextLabel: 'Next',
  },
  {
    id: 'rooftop-greeting', category: '06 / WELCOME TO OUR OFFICE', caption: 'THE ROOFTOP TERRACE',
    title: 'A rooftop hello. And a very warm pizza.',
    description: 'The lift opens onto the attached front terrace. A short walk across the deck leads to Egor at the office door.',
    hero: ['Made it.', 'Welcome up.'], note: 'Same little world. This time, it’s our office.',
    duration: 5200,
    nextLabel: 'Take it again',
  },
];

// One playhead is shared by the actors, doors and camera. Adjacent stops
// meet at the same physical instant; seeking travels through this timeline.
export const boundaries = stops.reduce((points,stop)=>[...points,points.at(-1)+stop.duration],[0]);
export function atTime(milliseconds) {
  const time=Math.max(0,Math.min(boundaries.at(-1),milliseconds));
  const index=stops.findIndex((_,i)=>time<=boundaries[i+1]);
  const progress=clamp((time-boundaries[index])/stops[index].duration);
  return {index,progress,state:sampleJourney(index,progress)};
}
export function turn(from,to,amount) {
  return from+Math.atan2(Math.sin(to-from),Math.cos(to-from))*amount;
}
function walkingRoute(points,p) {
  const result=route(points,p);
  const before=route(points,Math.max(0,p-.025)).position;
  const after=route(points,Math.min(1,p+.025)).position;
  result.yaw=Math.atan2(after[0]-before[0],after[2]-before[2]);
  return result;
}
