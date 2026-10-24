import * as THREE from 'three';
import { group, box, ball, cylinder, beam, label, plant, tree, material } from './geometry.js';
import { createPerson,createRaptor } from './characters.js';
import { TOP } from './journey.js';
import {OFFICE_ROTATION,OFFICE_ORIGIN,TERRACE,COURIER_LANDING,OFFICE_DOOR_LOCAL,LIFT_POSITION,LIFT_OPENING,REAR_BUILDING,REAR_PASSAGE,ROOF_ROTATION,ROOM_ROTATION,roomPoint,INTERCOM_BUTTON,LIFT_CALL_BUTTON} from './layout.js';

// Every mesh belongs to one presentation layer. Optional inner groups multiply
// that layer's alpha, while retaining translucent glass and label settings.
// Snapshotting base values once avoids opacity drift when a tour is replayed.
function presentationFade(root, innerGroups = []) {
  const records = [];
  root.traverse(mesh => {
    if (!mesh.isMesh) return;
    const source = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    const materials = source.map(original => {
      const copy = original.clone();
      return { material: copy, opacity: original.opacity, transparent: original.transparent, depthWrite: original.depthWrite };
    });
    mesh.material = Array.isArray(mesh.material) ? materials.map(item => item.material) : materials[0].material;
    const memberships = innerGroups.filter(inner => {
      for (let p = mesh.parent; p && p !== root; p = p.parent) if (p === inner.group) return true;
      return mesh === inner.group;
    });
    records.push({ mesh, materials, memberships, castShadow: mesh.castShadow });
  });
  let previous = '';
  return (value = 1, state = {}) => {
    const opacity = THREE.MathUtils.clamp(value, 0, 1);
    const innerValues = innerGroups.map(inner => THREE.MathUtils.clamp(inner.value(state), 0, 1));
    const signature = [opacity, ...innerValues].join(',');
    root.visible = opacity > .003;
    innerGroups.forEach((inner, i) => { inner.group.visible = innerValues[i] > .003; });
    if (signature === previous) return;
    previous = signature;
    for (const record of records) {
      const alpha = record.memberships.reduce((current, inner) => current * innerValues[innerGroups.indexOf(inner)], opacity);
      for (const original of record.materials) {
        const { material } = original;
        const transparent = original.transparent || alpha < .999;
        if (material.transparent !== transparent) { material.transparent = transparent; material.needsUpdate = true; }
        material.opacity = original.opacity * alpha;
        material.depthWrite = original.depthWrite && alpha > .98;
      }
      record.mesh.castShadow = record.castShadow && alpha > .95;
    }
  };
}

function windowUnit(parent, x, y, z, width = 1.2, height = 1.85, rotation = 0) {
  const g = group(parent, 'Sash window', [x, y, z]); g.rotation.y = rotation;
  box(g, [width + .24, height + .22, .12], [0, 0, 0], 'ivory', .02);
  box(g, [width, height, .08], [0, 0, .085], 'glass', .01);
  box(g, [.055, height, .07], [0, 0, .145], 'ivory', 0);
  box(g, [width, .06, .07], [0, .14, .145], 'ivory', 0);
  box(g, [width + .37, .11, .33], [0, -height / 2 - .12, .09], 'ivory', .015);
}

function bicycle(parent, position, rotation) {
  const g = group(parent, 'Street bicycle', position); g.rotation.y = rotation;
  for (const x of [-.62, .62]) {
    const tire = new THREE.Mesh(new THREE.TorusGeometry(.39, .043, 7, 20), material('charcoal'));
    tire.position.set(x, .43, 0); g.add(tire);
    for (const a of [0, Math.PI / 3, Math.PI * 2 / 3]) {
      beam(g, [x - Math.cos(a) * .36, .43 - Math.sin(a) * .36, 0], [x + Math.cos(a) * .36, .43 + Math.sin(a) * .36, 0], .015, 'stone');
    }
  }
  for (const [a, b] of [
    [[-.62,.43,0],[-.2,1,0]], [[-.2,1,0],[.2,.43,0]], [[.2,.43,0],[-.62,.43,0]],
    [[-.2,1,0],[.43,1,0]], [[.43,1,0],[.2,.43,0]], [[.43,1,0],[.62,.43,0]],
    [[.43,1,0],[.42,1.2,0]],
  ]) beam(g, a, b, .045, 'teal');
  box(g, [.33, .07, .18], [-.2, 1.08, 0], 'charcoal');
  box(g, [.09, .06, .42], [.42, 1.21, 0], 'charcoal');
}

function buildStreet(parent) {
  const street = group(parent, 'Linienstraße entrance');
  box(street, [27, .22, 5.4], [0, -.09, 15.2], 'stone');
  box(street, [28, .08, 3.5], [0, -.18, 19.4], '#969d94');
  for (let x = -13; x < 13; x += .85) box(street, [.02, .012, 5.2], [x, .028, 15.2], '#9eaa9e', 0);
  for (let z = 13; z < 17.8; z += .85) box(street, [26, .012, .02], [0, .029, z], '#9eaa9e', 0);
  for (const x of [-10, -5, 0, 5, 10]) box(street, [1.8, .014, .09], [x, -.13, 19.1], 'ivory', 0);

  const facade = group(street, 'Street facade');
  // Three sections leave an actual opening through the arched entrance.
  for (const x of [-6.45, 6.45]) box(facade, [9.25, 13.6, 1.2], [x, 6.8, 10], 'wall', .06);
  box(facade, [3.7, 8.7, 1.2], [0, 9.25, 10], 'wall', .05);
  // The lower trim must also leave the passage clear at the character's feet.
  for (const x of [-6.55, 6.55]) box(facade, [9.4, .18, 1.46], [x, .35, 10], 'ivory');
  for (const y of [4.9, 9.15, 13.65]) box(facade, [22.5, .18, 1.46], [0, y, 10], 'ivory');
  box(facade, [22.8, .23, 1.65], [0, 13.9, 10], 'ivory');
  for (const x of [-9.2, -5.6, -2.7, 2.7, 5.6, 9.2]) {
    for (const y of [2.65, 6.95, 11.2]) windowUnit(facade, x===2.7&&y<4?4:x, y, 10.65, 1.18, y < 4 ? 2.0 : 2.1);
  }
  windowUnit(facade, 0, 7.05, 10.65, 1.23, 2.1);
  windowUnit(facade, 0, 11.2, 10.65, 1.23, 2.1);
  for (const z of [8.7, 11.3]) {
    const roof = box(facade, [23, .18, 3.05], [0, 14.85, z], '#ae735d', 0);
    roof.rotation.x = z < 10 ? -.6 : .6;
    for (let x = -11; x <= 11; x += .7) {
      const seam = box(facade, [.035, .025, 3.02], [x, 14.96, z], '#8e6554', 0); seam.rotation.x = roof.rotation.x;
    }
  }

  // A separate arch and two jambs avoid a hole touching the outer shape at
  // ground level, which produced fill triangles across the original opening.
  for (const side of [-1, 1]) box(facade, [.37, 3.3, .23], [side * 1.645, 1.65, 10.785], 'ivory', .015);
  const frameShape = new THREE.Shape();
  frameShape.moveTo(1.83, 3.3);
  frameShape.absarc(0, 3.3, 1.83, 0, Math.PI, false);
  frameShape.lineTo(-1.46, 3.3);
  frameShape.absarc(0, 3.3, 1.46, Math.PI, 0, true);
  frameShape.closePath();
  const frame = new THREE.Mesh(new THREE.ExtrudeGeometry(frameShape, { depth: .23, bevelEnabled: false }), material('ivory'));
  frame.position.z = 10.67; facade.add(frame);
  const transomShape = new THREE.Shape(); transomShape.moveTo(-1.42, 0); transomShape.absarc(0, 0, 1.42, Math.PI, 0, true); transomShape.closePath();
  const transom = new THREE.Mesh(new THREE.ShapeGeometry(transomShape), material('darkWood'));
  transom.position.set(0, 3.3, 10.76); facade.add(transom);
  beam(facade, [-1.3,3.4,10.79], [1.3,3.4,10.79], .06, 'wood');
  beam(facade, [0,3.3,10.79], [0,4.64,10.79], .05, 'wood');
  const leaves = [];
  for (const side of [-1, 1]) {
    const pivot = group(facade, 'Street door leaf', [side * 1.45, 0, 10.7]);
    box(pivot, [1.45, 3.3, .18], [-side * .725, 1.65, 0], 'darkWood');
    for (const y of [.63, 1.65, 2.63]) {
      box(pivot, [1.08, .68, .05], [-side * .725, y, .115], 'brown');
      box(pivot, [.85, .47, .025], [-side * .725, y, .15], 'darkWood');
    }
    box(pivot, [.055, .4, .08], [-side * 1.26, 1.44, .16], 'yellow');
    leaves.push({ pivot, side });
  }
  label(facade, '144', 1.15, .42, [-2.28, 3.9, 10.71], { background: '#eee4cf' });
  const plaque = group(facade, 'Intercom', [2.5, 1.8, 10.67]);
  box(plaque, [.62, .9, .14], [0, 0, 0], 'steel');
  const bellMaterial = material('#bdc4b4').clone();
  for(let y=.06;y<=.26;y+=.05)box(plaque,[.38,.016,.012],[0,y,.085],'charcoal',0);
  const bell=box(plaque,[.50,.19,.08],[0,-.10,.11],bellMaterial,.03);bell.name='Intercom button';
  const jamieLabels={};
  for(const [key,text] of Object.entries({idle:'Jamie',connecting:'Cancel',connected:'End call',disconnecting:'Ending…',offline:'Jamie',denied:'Denied'})){
    jamieLabels[key]=label(plaque,text,.45,.125,[0,-.10,.17],{background:'#355648',color:'#ffffff',size:.61});
    jamieLabels[key].visible=key==='idle';
  }
  label(street, 'LINIENSTRASSE', 3, .35, [-7.5, .04, 16.3]).rotation.x = -Math.PI / 2;
  bicycle(street, [-5, .05, 12.4], .15); bicycle(street, [6.8, .05, 12.4], -.1);
  return { group: street, facade, leaves, bell, plaque, jamieLabels };
}

function buildCourtyard(parent) {
  const g = group(parent, 'Courtyard');
  // Leave a real shaft pit in every paving layer. The moving wooden cabin
  // floor must never occupy the same surface as the static courtyard paving.
  function groundSlab(size,position,color){
    const [width,height,depth]=size,[x,y,z]=position;
    const left=x-width/2,right=x+width/2,back=z-depth/2,front=z+depth/2;
    const cut={left:Math.max(left,LIFT_OPENING.left),right:Math.min(right,LIFT_OPENING.right),back:Math.max(back,LIFT_OPENING.back),front:Math.min(front,LIFT_OPENING.front)};
    if(cut.left>=cut.right||cut.back>=cut.front){box(g,size,position,color,0);return;}
    for(const [l,r,b,f] of [[left,cut.left,back,front],[cut.right,right,back,front],[cut.left,cut.right,back,cut.back],[cut.left,cut.right,cut.front,front]])
      if(r-l>.001&&f-b>.001)box(g,[r-l,height,f-b],[(l+r)/2,y,(b+f)/2],color,0);
  }
  groundSlab([23.5,.36,29],[0,-.36,1],'stone');
  groundSlab([22.5,.08,20.3],[0,-.12,.5],'#8e9287');
  groundSlab([2.6,.08,18.6],[0,-.035,1],'#596264');
  groundSlab([10.6,.08,2.6],[-5.3,-.03,-6.55],'#596264');
  for(let z=-7.6;z<10.4;z+=.47)for(const x of [-.94,-.47,0,.47,.94])
    groundSlab([.43,.012,.43],[x,-.005,z],'#697172');
  for(let x=-10.1;x<0;x+=.47)for(const z of [-7.45,-6.98,-6.51,-6.04,-5.57])
    groundSlab([.43,.012,.43],[x,-.005,z],'#697172');
  // Low-poly slate beds and the dark central path from the courtyard photos.
  const rockGeometry=new THREE.IcosahedronGeometry(.34,0);
  let seed=174;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
  for(let z=-5.8;z<9.8;z+=.7)for(let x=-9.6;x<9.7;x+=.7){
    if(Math.abs(x)<1.6||(x<.2&&z< -5.2))continue;
    const rock=new THREE.Mesh(rockGeometry,material(['#6e7779','#8a9290','#747c80'][Math.floor(random()*3)]));
    rock.position.set(x+(random()-.5)*.3,.09,z+(random()-.5)*.3);
    rock.rotation.set(random()*2,random()*6,random()*2);rock.scale.set(.8+random()*.7,.45+random()*.5,.7+random());
    rock.castShadow=true;rock.receiveShadow=true;g.add(rock);
  }
  let rightWing,leftWing;
  for (const x of [-11.1, 11.1]) {
    const wing=group(g,x>0?'Cutaway right wing':'Left courtyard wing');
    box(wing, [1, 13.2, 18.2], [x, 6.6, .4], 'cream');
    for (const y of [2.5, 6.1, 9.9]) for (const z of [-6.1, -1.8, 2.5, 6.8])
      windowUnit(wing, x < 0 ? x + .57 : x - .57, y, z, 1.2, 1.95, x < 0 ? Math.PI/2 : -Math.PI/2);
    box(wing, [2.3, .16, 18.7], [x, 13.6, .4], '#b9765a', 0);
    if(x>0)rightWing=wing;else leftWing=wing;
  }
  const back = group(g, 'Rear brick building');
  const canvas=document.createElement('canvas');canvas.width=512;canvas.height=512;
  const context=canvas.getContext('2d');context.fillStyle='#8e806c';context.fillRect(0,0,512,512);
  const brickColors=['#c4a47d','#cdb18b','#b79772','#d0b993','#b58e70'];
  for(let row=0;row<16;row++)for(let col=-1;col<9;col++){
    context.fillStyle=brickColors[(row*7+col+10)%brickColors.length];
    context.fillRect(col*64+(row%2)*32+2,row*32+2,60,28);
  }
  const brickTexture=new THREE.CanvasTexture(canvas);brickTexture.colorSpace=THREE.SRGBColorSpace;
  brickTexture.wrapS=brickTexture.wrapT=THREE.RepeatWrapping;brickTexture.repeat.set(1,1);
  const brick=new THREE.MeshStandardMaterial({map:brickTexture,roughness:1});
  function brickWall(size,position){
    const wall=box(back,size,position,brick,.01);
    wall.geometry=wall.geometry.clone();
    const points=wall.geometry.attributes.position,normals=wall.geometry.attributes.normal,uv=wall.geometry.attributes.uv;
    for(let i=0;i<points.count;i++){
      const x=points.getX(i)+position[0],y=points.getY(i)+position[1],z=points.getZ(i)+position[2];
      const nx=Math.abs(normals.getX(i)),ny=Math.abs(normals.getY(i)),nz=Math.abs(normals.getZ(i));
      uv.setXY(i,(nx>nz&&nx>ny?z:x)/4,ny>nx&&ny>nz?z/5.3:y/5.3);
    }
    uv.needsUpdate=true;return wall;
  }
  // The rear block spans the courtyard, parallel to the street frontage.
  const {left,right,back:backEdge,front}=REAR_BUILDING;
  const width=right-left,depth=front-backEdge,centerZ=(front+backEdge)/2,centerX=(left+right)/2;
  box(back,[width+.4,.24,depth+.4],[centerX,-.15,centerZ],'stone',.03);
  // Three structural volumes leave a real, full-depth passage. There is no
  // dark decal or solid wall behind this opening.
  const passageLeft=REAR_PASSAGE.centerX-REAR_PASSAGE.width/2;
  const passageRight=REAR_PASSAGE.centerX+REAR_PASSAGE.width/2;
  const shellHeight=TOP-.25;
  for(const [a,b,name] of [[left,passageLeft,'Left pier'],[passageRight,right,'Right pier']]){
    brickWall([b-a,shellHeight,depth],[(a+b)/2,shellHeight/2,centerZ]).name=name;
  }
  brickWall([REAR_PASSAGE.width,shellHeight-REAR_PASSAGE.height,depth],
    [REAR_PASSAGE.centerX,(shellHeight+REAR_PASSAGE.height)/2,centerZ]).name='Brick above rear passage';
  const tunnel=group(back,'Rear passage');
  const interior=material('#7d735f');
  for(const x of [passageLeft,passageRight])box(tunnel,[.065,REAR_PASSAGE.height,depth],[x,REAR_PASSAGE.height/2,centerZ],interior,.005);
  box(tunnel,[REAR_PASSAGE.width,.08,depth],[REAR_PASSAGE.centerX,REAR_PASSAGE.height-.04,centerZ],interior,.005);
  box(tunnel,[REAR_PASSAGE.width,.035,depth+1],[REAR_PASSAGE.centerX,.005,centerZ],'#5b6260',.005);
  // A light rear landing and a small plant give the open passage depth.
  box(tunnel,[6,.08,3],[REAR_PASSAGE.centerX,-.035,backEdge-1.5],'stone',.01);
  box(tunnel,[6,4,.2],[REAR_PASSAGE.centerX,2,backEdge-3],'ivory',.01);
  box(tunnel,[1.2,2.7,.035],[REAR_PASSAGE.centerX-.8,1.35,backEdge-2.87],'glass',.01);
  plant(tunnel,[REAR_PASSAGE.centerX+1.6,.03,backEdge-2],.7);
  for(const y of [3,6.9,10.8,14.3]){
    // Keep the original facade bays fixed as the block extends east.
    for(const x of [-15.1,-10.8,-6.5,-2.2,2.1,6.4,9.7]){
      if(y<REAR_PASSAGE.height+1&&Math.abs(x-REAR_PASSAGE.centerX)<REAR_PASSAGE.width/2+1.1)continue;
      box(back,[2.2,2.3,.12],[x,y,front+.06],'charcoal',.025);
      box(back,[1.98,2.09,.08],[x,y,front+.14],'glass',.01);
      box(back,[.06,2.13,.06],[x,y,front+.2],'charcoal',0);
      box(back,[2.3,.13,.4],[x,y-1.22,front+.1],'brown',.01);
    }
    box(back,[width+.2,.2,.2],[centerX,y+1.5,front+.12],'#9e654e',0);
  }
  for(const z of [-11,-15,-19])for(const y of [3,7,11,14.3]){
    const sideWindow=group(back,'Side courtyard window',[left-.04,y,z]);sideWindow.rotation.y=-Math.PI/2;
    box(sideWindow,[2.2,2.2,.1],[0,0,0],'charcoal',.02);
    box(sideWindow,[1.99,1.99,.08],[0,0,.09],'glass',.01);
  }

  box(g,[REAR_PASSAGE.width,.04,2.25],[REAR_PASSAGE.centerX,-.02,front+1.05],'#596264',.01);
  tree(g, [-4.5, 0, 4.4]); tree(g, [5, 0, 2.5], 'green'); tree(g, [4.8, 0, -3.8]);
  for (const [x,z] of [[-7.6,5.1],[6.6,-1.2]]) {
    box(g, [2.3,.13,.7], [x,.52,z], 'brown');
    for (const dx of [-.8,.8]) box(g, [.11,.5,.54], [x+dx,.25,z], 'steel');
  }
  box(g,[3.2,.12,3.1],[6.4,.02,5.9],'stone',.02);
  for(const [x,z,angle] of [[5.6,5.6,.13],[7,6.3,-.2]]){
    const sculpture=group(g,'Rust courtyard sculpture',[x,.1,z]);sculpture.rotation.y=angle;
    box(sculpture,[1.1,1.2,1.05],[0,.6,0],'#98624b',.02);
    box(sculpture,[.8,.18,.8],[.25,1.25,0],'#ad7654',.02);
  }
  label(g, 'ZUM AUFZUG  ←', 2.1, .34, [-5, 2.65, -7.8]);
  return {group:g,rightWing,leftWing};
}

function buildLift(parent) {
  const shaft = group(parent, 'External glass elevator', LIFT_POSITION);
  const lowerShaft = group(shaft, 'Lower elevator structure');
  const crown = group(shaft, 'Rooftop elevator structure');
  const glass = material('glass', { transparent: true, opacity: .14, depthWrite: false, side: THREE.DoubleSide });
  for (const x of [-1.46, 1.46]) for (const z of [-1.35, 1.35]) {
    box(lowerShaft, [.12, TOP, .12], [x,TOP/2,z], 'steel', 0);
    box(crown, [.12,4.3,.12], [x,TOP+2.15,z], 'steel', 0);
  }
  for (const y of [0,4,8,12,16,19.6]) {
    const structure = y < TOP ? lowerShaft : crown;
    const height = y === TOP ? TOP + .05 : y;
    for (const z of [-1.35,1.35]) box(structure,[3,.1,.12],[0,height,z],'steel',0);
    for (const x of [-1.46,1.46]) box(structure,[.12,.1,2.7],[x,height,0],'steel',0);
  }
  for (const [structure, bottom, height] of [[lowerShaft,0,TOP],[crown,TOP,3.4]]) {
    for (const x of [-1.42,1.42]) {
      if(x<0&&structure===lowerShaft)box(structure,[.02,height,2.6],[x,bottom+height/2,0],glass,0);
      else if(x>0&&structure===crown)box(structure,[.02,height,2.6],[x,bottom+height/2,0],glass,0);
      else if(x>0&&structure===lowerShaft)box(structure,[.02,height-3.3,2.6],[x,bottom+3.3+(height-3.3)/2,0],glass,0);
    }
    box(structure,[2.8,height,.025],[0,bottom+height/2,1.32],glass,0);
    box(structure,[2.8,height,.025],[0,bottom+height/2,-1.32],glass,0);
  }
  for (const [structure, bottom, height] of [[lowerShaft,0,TOP],[crown,TOP,3]]) {
    for (const x of [-1.2,1.2]) box(structure,[.055,height,.06],[x,bottom+height/2,-1.12],'stone',0);
  }
  box(crown,[3.6,.15,3.25],[0,TOP+4.25,0],'steel',0);
  for (const [a,b] of [[[-1.3,TOP+3,-1.2],[1.3,TOP+4.05,-1.2]],[[1.3,TOP+3,-1.2],[-1.3,TOP+4.05,-1.2]]]) beam(crown,a,b,.08);
  const cabin = group(shaft,'Elevator cabin');
  // Cabin floor and terrace now meet the character's sole height at a stop.
  box(cabin,[2.7,.16,2.5],[0,-.16,0],'steel');
  box(cabin,[2.6,.06,2.4],[0,-.03,0],'wood',0);
  box(cabin,[2.7,.16,.14],[0,3.05,-1.2],'charcoal');
  box(cabin,[2.8,.13,2.6],[0,3.25,0],'steel');

  for(const z of [-1.22,1.22])box(cabin,[2.5,3.2,.07],[0,1.65,z],glass,0);
  box(cabin,[2.25,.08,.07],[0,1.3,-1.12],'wood');
  // Two telescoping leaves per side park in shallow pockets inside the shaft.
  // A single full-width leaf cannot clear the entrance without passing through
  // the glass sides, which was particularly visible during the ride.
  const doors = [];
  for(const portal of ['right','terrace']){
    const portalGroup=group(cabin,portal==='right'?'Right-side elevator entrance':'Terrace elevator exit');
    portalGroup.rotation.y=portal==='right'?Math.PI/2:-Math.PI/2;
    for (const side of [-1, 1]) {
      for (let panel = 0; panel < 2; panel++) {
        const door = group(portalGroup,'Telescoping glazed leaf',[side*(.245+panel*.49),1.525,1.26+panel*.065]);
        door.userData = { side, portal, closed: .245 + panel * .49, open: 1.105 + panel * .015 };
        for (const x of [-.2275,.2275]) box(door,[.045,2.95,.055],[x,0,0],'steel',.01);
        for (const y of [-1.4475,1.4475]) box(door,[.5,.055,.055],[0,y,0],'steel',.01);
        box(door,[.41,2.39,.018],[0,.245,0],glass,0);
        box(door,[.5,.48,.055],[0,-1.225,0],'steel',.012);
        box(door,[.027,1.38,.014],[side*.212,.06,.034],'stone',.006);
        doors.push(door);
      }
      box(portalGroup,[.43,3.07,.22],[side*1.145,1.54,1.335],'charcoal',.025);
    }
    box(portalGroup,[2.75,.13,.2],[0,3.08,1.325],'steel');
    label(portalGroup,'↑',.5,.25,[0,3.45,1.3],{color:'#f9edce',background:'#304b4d'});
  }
  // A reachable call pedestal beside the right-hand entrance.
  const call=group(lowerShaft,'Lift call pedestal',[LIFT_CALL_BUTTON[0]-LIFT_POSITION[0]-.15875,0,LIFT_CALL_BUTTON[2]-LIFT_POSITION[2]]);
  box(call,[.13,1.1,.15],[0,.55,0],'steel',.02);
  box(call,[.22,.44,.30],[0,1.25,0],'charcoal',.035);
  const callButton=ball(call,.065,[.12,1.25,0],material('#b7c6b8'),[.35,1,1]);callButton.name='Elevator call button';
  const dispatch=group(lowerShaft,'Lift dispatch notice',[LIFT_CALL_BUTTON[0]-LIFT_POSITION[0]+.1,2,LIFT_CALL_BUTTON[2]-LIFT_POSITION[2]]);
  dispatch.rotation.y=Math.PI/2;
  label(dispatch,'Jamie · sending lift',1.9,.26,[0,0,0],{background:'#355648',color:'#fff9e8'});
  return {group:shaft,lowerShaft,crown,cabin,doors,callButton,dispatch};
}

function chair(parent, position, rotation = 0, color = 'charcoal') {
  const g=group(parent,'Desk chair',position); g.rotation.y=rotation;
  box(g,[.7,.13,.67],[0,.58,0],color,.09);
  box(g,[.7,.68,.1],[0,1,.29],color,.07);
  cylinder(g,.05,.47,[0,.28,0],'steel');
  for(const angle of [0,Math.PI/2]) {const f=box(g,[.76,.07,.07],[0,.07,0],'steel');f.rotation.y=angle;}
  return g;
}

function buildLoft(parent) {
  const loft=group(parent,'Our rooftop loft',OFFICE_ORIGIN);
  loft.rotation.y=OFFICE_ROTATION;
  // Meet the terrace edge exactly, avoiding coincident floor surfaces and the
  // rear corner of the lift opening which the old oversized slab filled in.
  box(loft,[20,.3,12.3],[0,-.17,-.245],'stone');
  box(loft,[18.2,.06,12.15],[0,0,-.17],'ivory');
  // Continue the roof over the new right-hand bays without shifting the loft.
  const extensionLeft=OFFICE_ORIGIN[0]+10;
  const extensionWidth=REAR_BUILDING.right-extensionLeft;
  const extensionCenter=(extensionLeft+REAR_BUILDING.right)/2-OFFICE_ORIGIN[0];
  const extension=group(loft,'Right roof extension');
  box(extension,[extensionWidth,.3,12.3],[extensionCenter,-.17,-.245],'stone');
  box(extension,[extensionWidth-.3,.06,12],[extensionCenter,0,-.245],'ivory');
  box(extension,[.18,.48,12.3],[REAR_BUILDING.right-OFFICE_ORIGIN[0]-.09,.22,-.245],'stone');
  box(extension,[extensionWidth,.48,.18],[extensionCenter,.22,-6.305],'stone');

  // Rotate the roof within the existing rectangular footprint. Only the
  // roof geometry is fitted to that footprint; furniture retains its scale.
  const roof=group(loft,'Rotated office roof',[0,0,-.245]);
  roof.rotation.y=ROOF_ROTATION;
  roof.scale.set(2/3,1,1.5);
  box(roof,[18.3,4.5,.18],[0,2.2,-6],'stone');
  // Curved timber slats and steel ribs, with a cutaway front for the tour camera.
  const roofY=x=>1.15+4.65*Math.sqrt(Math.max(0,1-(x/9.1)**2));
  for(let x=-8.95;x<=8.95;x+=.28) box(roof,[.105,.11,4.5],[x,roofY(x),-3.6],'wood',.012);
  for(const z of [-5.85,-3.8,-1.55]) {
    const points=Array.from({length:41},(_,i)=>{const x=-9+i*18/40;return new THREE.Vector3(x,roofY(x)-.13,z);});
    const rib=new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),48,.06,6,false),material('steel'));roof.add(rib);
  }
  const warm=material('#fff0b7',{emissive:'#f5c570',emissiveIntensity:.65});
  for(const x of [-6,-3,0,3,6]) for(const z of [-4.7,-2.5]) box(roof,[.19,.065,1.25],[x,roofY(x)-.16,z],warm);
  // The broad angled glazing is the other signature feature in the references.
  const roofGlass=material('glass',{transparent:true,opacity:.25,depthWrite:false,side:THREE.DoubleSide});
  const slopeA=[5.3,4.65,0],slopeB=[8.9,1.55,0];
  for(const z of [-4.6,-1.4,1.8,5]) {
    beam(roof,[...slopeA.slice(0,2),z],[...slopeB.slice(0,2),z],.1,'ivory');
    if(z<5) {
      const geometry=new THREE.BufferGeometry();
      geometry.setAttribute('position',new THREE.Float32BufferAttribute([5.3,4.65,z,8.9,1.55,z,8.9,1.55,z+3.05,5.3,4.65,z,8.9,1.55,z+3.05,5.3,4.65,z+3.05],3));
      geometry.computeVertexNormals();roof.add(new THREE.Mesh(geometry,roofGlass));
    }
  }
  for(const t of [0,.5,1]) beam(roof,[5.3+3.6*t,4.65-3.1*t,-5.9],[5.3+3.6*t,4.65-3.1*t,5.9],.08,'ivory');

  const room=group(loft,'Rotated office interior',[0,0,-.245]);
  room.rotation.y=ROOM_ROTATION;
  // Long pale desks, dark monitors, and trestle legs seen in the office photos.
  for(const z of [-2.2,2.1]) for(const x of [-3.8,.15,4.1]) {
    box(room,[3.6,.12,1.25],[x,1.05,z],'ivory');
    for(const dx of [-1.4,1.4]) {
      beam(room,[x+dx-.2,.04,z-.4],[x+dx,1.0,z],.065,'steel');
      beam(room,[x+dx+.2,.04,z+.4],[x+dx,1.0,z],.065,'steel');
    }
    box(room,[1.15,.74,.1],[x,1.58,z-.22],'charcoal');
    box(room,[1.01,.6,.015],[x,1.58,z-.159],material('navy',{emissive:'#719d9a',emissiveIntensity:.2}));
    box(room,[.1,.22,.1],[x,1.2,z-.22],'steel');
    box(room,[.6,.04,.23],[x,1.14,z+.27],'stone');
    cylinder(room,.075,.16,[x+.87,1.2,z+.21],'ivory');
    chair(room,[x,0,z+.95],0,x>3?'yellow':'charcoal');
  }
  for(const x of [-2.6,.6]) {
    box(room,[1.05,2.65,1.2],[x,1.35,-7.3],'charcoal',.16);
    box(room,[.87,2.4,.08],[x,1.33,-6.65],'cream',.1);
    box(room,[.69,1.73,.02],[x,1.46,-6.6],roofGlass,.02);
  }
  box(room,[3.1,.52,1.2],[3.6,.37,-6.8],'charcoal',.15);
  box(room,[3.1,.75,.3],[3.6,.84,-7.3],'charcoal',.12);
  for(const x of [2.6,4.7]) box(room,[.66,.35,.7],[x,.77,-6.8],'mint',.12);
  for(const p of [[-4.7,.03,-7.5],[4.9,.03,-7.5],[-4.9,.03,6.5]]) plant(room,p,1.05);
  label(room,'GOOD THINGS HAPPEN HERE',4,.38,[1.8,3.2,-5.88],{background:'#b8b8a6',color:'#304b4d'});

  const terrace=group(parent,'Wooden rooftop terrace',[0,TOP,0]);
  // The lift travels through an actual opening in the landing rather than
  // intersecting a continuous deck. The small clearance also separates glass
  // and steel surfaces that used to flicker during the upward camera move.
  const shaftOpening=LIFT_OPENING;
  const {left:deckLeft,right:deckRight,back:deckBack,front:deckFront}=TERRACE;
  for (const [left, right, back, front] of [
    [deckLeft, shaftOpening.left, deckBack, deckFront],
    [shaftOpening.right, deckRight, deckBack, deckFront],
    [shaftOpening.left, shaftOpening.right, deckBack, shaftOpening.back],
    [shaftOpening.left, shaftOpening.right, shaftOpening.front, deckFront],
  ]) box(terrace,[right-left,.24,front-back],[(left+right)/2,-.14,(back+front)/2],'steel',.02);
  for(let x=deckLeft+.21;x<deckRight-.19;x+=.43) {
    const insideShaft = x + .195 > shaftOpening.left && x - .195 < shaftOpening.right;
    const spans = insideShaft ? [[deckBack,shaftOpening.back],[shaftOpening.front,deckFront]] : [[deckBack,deckFront]];
    for (const [back, front] of spans) box(terrace,[.39,.07,front-back],[x,-.005,(back+front)/2],'wood',.008);
  }
  // A compact annex sits against the office's courtyard-facing edge.
  // Keep its attached edge open; the outer front edge has the white parapet.
  const deckWidth=deckRight-deckLeft;
  box(terrace,[deckWidth,1,.24],[(deckLeft+deckRight)/2,.5,deckFront-.12],'ivory',.035);
  box(terrace,[deckWidth-.2,.08,.08],[(deckLeft+deckRight)/2,1.12,deckFront-.25],'charcoal',.025);
  for(let x=deckLeft+.8;x<deckRight;x+=1.9)box(terrace,[.07,.05,.25],[x,.95,deckFront-.22],'charcoal',.015);
  for(const x of [deckLeft,deckRight]){
    box(terrace,[.065,.065,deckFront-deckBack],[x,1.08,(deckBack+deckFront)/2],'steel',.015);
    for(const z of [deckBack,deckFront])box(terrace,[.065,1.05,.065],[x,.56,z],'steel',.015);
  }
  plant(terrace,[deckRight-.8,.1,deckFront-1],.75);
  // Glazed main door in the curved metal roof, immediately off the lift landing.
  const doorway=group(loft,'Main office door',OFFICE_DOOR_LOCAL);
  for(const x of [-1.21,1.21])box(doorway,[.28,3.3,.44],[x,1.65,.08],'steel',.09);
  box(doorway,[2.7,.28,.44],[0,3.16,.08],'steel',.09);
  for (const side of [-1,1]) {
    box(doorway,[.17,3.1,.22],[side*1.005,1.55,0],'ivory',.03);
    box(doorway,[.055,2.89,.24],[side*.893,1.465,.025],'charcoal',.012);
  }
  box(doorway,[2.18,.17,.22],[0,3.015,0],'ivory',.03);
  box(doorway,[1.84,.07,.24],[0,2.885,.025],'charcoal',.012);
  box(doorway,[1.83,.035,.31],[0,.015,.055],'steel',.008);
  const door=group(doorway,'Office door hinge',[-.88,.1,.24]);
  for (const x of [.055, 1.695]) box(door,[.11,2.65,.09],[x,1.32,0],'steel',.018);
  for (const y of [.05, 2.595]) box(door,[1.75,.11,.09],[.875,y,0],'steel',.018);
  box(door,[1.53,2.43,.025],[.875,1.32,0],roofGlass,0);
  box(door,[.045,.43,.08],[1.58,1.25,.12],'ivory');
  label(doorway,'HELLO, UP HERE.',2.4,.3,[0,3.45,.12]);
  return {loft,terrace,door};
}

export function createWorld() {
  const root=group(null,'Linienstraße 144');
  const courtyard=buildCourtyard(root);
  const street=buildStreet(root),lift=buildLift(root),office=buildLoft(root);
  const courier=createPerson(root,{name:'Courier',courier:true,shirt:'#ffcc00'});
  const raptor=createRaptor(root);
  const egor=createPerson(root,{name:'Egor',glasses:true,shirt:'teal'});
  const colleague=createPerson(root,{name:'Hello!',shirt:'yellow',position:roomPoint([2.6,0,3.4])});
  const hello=label(root,'Delivered!',2.55,.54,[COURIER_LANDING[0]+.8,TOP+3.9,COURIER_LANDING[2]],{background:'#fcf6e9',color:'#528c80'});
  const rippedMount=box(street.facade,[.53,.76,.012],[2.5,1.8,10.61],'#504d42',.01);rippedMount.visible=false;
  const destruction=group(root,'Cartoon intercom explosion');
  const debris=Array.from({length:22},(_,i)=>{
    const piece=box(destruction,[.04+(i%3)*.03,.05+(i%4)*.03,.04],[0,0,0],i%3===0?'#e8b353':i%2?'#667a74':'#d7ddd0',.007);
    piece.userData={angle:i*2.39996,speed:.8+(i%5)*.28,up:1.4+(i%4)*.35};return piece;
  });
  const flash=ball(destruction,.45,[2.5,1.8,10.85],material('#ffe7a2',{emissive:'#ffb52e',emissiveIntensity:2,transparent:true,opacity:1,depthWrite:false}),[1,1,1]);
  const smoke=Array.from({length:7},(_,i)=>ball(destruction,.22,[0,0,0],material('#b7b4a5',{transparent:true,opacity:.6,depthWrite:false}),[1,1,1]));
  destruction.visible=false;
  const bitePoint=new THREE.Vector3();
  const ringGroup=group(root,'Doorbell signal',[2.5,1.7,10.88]);
  const ringMaterial=new THREE.MeshBasicMaterial({color:'#dc9369',transparent:true,opacity:.8,side:THREE.DoubleSide,depthWrite:false});
  const rings=[.3,.5,.7].map(radius=>{
    const r=new THREE.Mesh(new THREE.RingGeometry(radius,radius+.022,40),ringMaterial);ringGroup.add(r);return r;
  });
  const layers={street:street.group,courtyard:courtyard.group,loft:office.loft,terrace:office.terrace,shaft:lift.group,lowerShaft:lift.lowerShaft,crown:lift.crown,cabin:lift.cabin};
  const fades={
    street:presentationFade(street.group,[{group:street.facade,value:s=>s.facade??1}]),
    courtyard:presentationFade(courtyard.group,[{group:courtyard.rightWing,value:s=>s.facade??1},{group:courtyard.leftWing,value:s=>s.leftWing??1}]),
    loft:presentationFade(office.loft),
    terrace:presentationFade(office.terrace),
    shaft:presentationFade(lift.group,[{group:lift.lowerShaft,value:s=>s.presentation?.lowerShaft??1}]),
    courier:presentationFade(courier.root),
    egor:presentationFade(egor.root),
    colleague:presentationFade(colleague.root),
    hello:presentationFade(hello),
  };
  let state;
  function updateView(camera) {
    courier.updateView(camera); egor.updateView(camera); colleague.updateView(camera);
    if (camera && hello.visible) hello.quaternion.copy(camera.quaternion);
  }
  function update(s,time=0,camera) {
    state=s;
    lift.dispatch.visible=s.stage===3&&s.liftCalled>.15&&s.liftY>.1;
    for(const [key,label] of Object.entries(street.jamieLabels))label.visible=key===(s.deniedGlow?'denied':s.callStatus||'idle');
    const p={street:1,courtyard:1,loft:1,terrace:1,shaft:1,lowerShaft:1,...s.presentation};
    for (const name of ['street','courtyard','loft','terrace','shaft']) fades[name](p[name],s);
    for(const {pivot,side} of street.leaves) pivot.rotation.y=-side*s.streetDoor*1.4;
    ringMaterial.opacity=.8*p.street*(s.facade??1);
    ringGroup.visible=s.ring>.1&&ringMaterial.opacity>.003&&!(s.raptorBite>.47);
    rings.forEach((ring,i)=>{const t=(time*.8+i/3)%1;ring.scale.setScalar(.65+t*.8);});
    street.bell.material.color.set(s.deniedGlow?'#d9644f':s.approved||s.intercomPress>.4 ? '#8db496':'#c3c5b7');
    street.bell.material.emissive.set(s.deniedGlow?'#a52a1d':'#000000');
    street.bell.material.emissiveIntensity=s.deniedGlow?.45+.25*Math.sin(time*5):0;
    street.bell.position.z=.12-.018*(s.intercomPress||0);
    lift.callButton.position.x=.12-.018*(s.liftPress||0);
    lift.callButton.material.color.set(s.liftCalled>.5?'#eac275':'#b7c6b8');
    lift.callButton.material.emissive.set(s.liftCalled>.5?'#6d4b1c':'#000000');
    lift.cabin.position.y=s.liftY;
    lift.doors.forEach(door=>{
      const {side,closed,open,portal}=door.userData;
      const atLanding=portal==='right'?s.liftY<.01:s.liftY>TOP-.01;
      door.position.x=side*THREE.MathUtils.lerp(closed,open,atLanding?s.liftDoor:0);
    });
    office.door.rotation.y=s.officeDoor*1.15;
    raptor.update({position:s.raptor,yaw:s.raptorYaw,walking:s.raptorWalking,press:s.raptorPress||0,bite:s.raptorBite||0,viewerBite:s.viewerBite||0,scale:s.raptorScale||1,time});
    const bite=s.raptorBite||0;
    const burst=(s.raptorFinale||0)-1.55;
    destruction.visible=burst>0;
    if(burst>0){
      const t=Math.min(burst,2.5);
      for(const piece of debris){
        const {angle,speed,up}=piece.userData;
        piece.position.set(2.5+Math.cos(angle)*speed*t,Math.max(.05,1.8+up*t-3*t*t),10.9+Math.abs(Math.sin(angle))*speed*t);
        piece.rotation.set(t*speed*4,angle+t*5,t*3);
      }
      flash.visible=burst<.32;flash.scale.setScalar(.3+Math.min(burst,.32)*5);flash.material.opacity=Math.max(0,1-burst/.32);
      smoke.forEach((puff,i)=>{
        puff.visible=burst<2;
        puff.position.set(2.5+Math.sin(i*2.4)*(.2+t*.3),1.8+t*.65+(i%3)*.13,10.95+Math.cos(i)*.12);
        puff.scale.setScalar(.8+t*2);puff.material.opacity=Math.max(0,.45*(1-burst/2));
      });
    }
    rippedMount.visible=bite>.47;
    street.plaque.visible=bite<.98;
    street.plaque.position.set(2.5,1.8,10.67);street.plaque.rotation.set(0,0,0);street.plaque.scale.setScalar(1);
    if(bite>.47){
      raptor.root.updateWorldMatrix(true,true);
      raptor.mouth.getWorldPosition(bitePoint);
      street.plaque.parent.worldToLocal(bitePoint);
      street.plaque.position.copy(bitePoint);
      street.plaque.rotation.set(.1,Math.PI/2,(bite-.47)*2);
      street.plaque.scale.setScalar(Math.max(0,1-Math.max(0,(bite-.72)/.26)));
    }
    courier.update({position:s.visitor,yaw:s.visitorYaw,walking:s.walking,delivered:s.delivered,reachTarget:s.stage===0?INTERCOM_BUTTON:LIFT_CALL_BUTTON,reachNormal:s.stage===0?[0,0,1]:[1,0,0],reachAmount:s.stage===0?s.intercomReach:s.liftReach,showLabel:false,time});
    egor.update({position:s.egor,yaw:s.egorYaw,walking:s.egorWalking,usePhone:s.phone>.01,phoneAmount:s.phone,phoneTap:s.phoneTap||0,phoneChoice:s.phoneChoice,visitorRequest:s.phoneNotice||s.visitorRequest,waving:s.greet>.5,showLabel:false,time});
    colleague.update({position:roomPoint([2.6,0,3.4]),yaw:-.9+ROOM_ROTATION,waving:s.greet>.3,showLabel:false,time});
    const upstairs=s.visitor[1]>=TOP-.5;
    const courierOpacity=Math.max(p.street,p.courtyard,p.shaft*(upstairs?1:p.lowerShaft),upstairs?p.terrace:0);
    const officeOpacity=Math.max(p.loft,p.terrace);
    fades.courier(s.courierGone?0:courierOpacity,s); fades.egor(officeOpacity,s);
    fades.colleague(officeOpacity,s);
    fades.hello(0,s);
    updateView(camera);
  }
  const phoneRay=new THREE.Raycaster();
  function pickPhoneChoice(pointer,camera){
    if(!egor.phone.visible)return null;
    phoneRay.setFromCamera(pointer,camera);
    return phoneRay.intersectObjects(egor.phoneButtons,false)[0]?.object.userData.phoneChoice||null;
  }
  function pickInteraction(pointer,camera){
    phoneRay.setFromCamera(pointer,camera);
    const objects=[street.bell,...Object.values(street.jamieLabels).filter(item=>item.visible),lift.callButton];
    const hit=phoneRay.intersectObjects(objects,false)[0];
    return hit?(hit.object===lift.callButton?'lift':'intercom'):null;
  }
  return {group:root,layers,update,updateView,pickPhoneChoice,pickInteraction,getState:()=>state};
}
