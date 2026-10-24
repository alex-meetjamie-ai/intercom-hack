import * as THREE from 'three';
import { group, box, ball, cylinder, label, material } from './geometry.js';

export function createPerson(parent, { name, position = [0, 0, 0], shirt = 'teal', courier = false, glasses = false }) {
  const root = group(parent, name, position);
  const body = group(root, 'Body');
  box(body, [.69, .82, .4], [0, 1.15, 0], shirt, .15);
  cylinder(body, .11, .17, [0, 1.65, 0], 'skin');
  ball(body, .32, [0, 1.97, 0], 'skin', [.9, 1.1, .9]);
  ball(body, .31, [0, 2.1, -.025], 'hair', [.94, .6, .93]);
  ball(body, .055, [0, 1.94, .285], 'skin');
  for (const x of [-.105, .105]) ball(body, .028, [x, 2, .277], 'charcoal');
  if (glasses) {
    for (const x of [-.12, .12]) {
      const lens = new THREE.Mesh(new THREE.TorusGeometry(.092, .014, 6, 16), material('charcoal'));
      lens.position.set(x, 2, .28); body.add(lens);
    }
    box(body, [.08, .023, .02], [0, 2, .285], 'charcoal', 0);
  }
  const elbows = [];
  const arms = [-1, 1].map(side => {
    const pivot = group(body, 'Arm', [side * .44, 1.48, 0]);
    box(pivot, [.23, .35, .24], [0, -.135, 0], shirt, .085);
    const elbow = group(pivot, 'Forearm', [0, -.31, 0]);
    box(elbow, [.205, .29, .21], [0, -.115, 0], shirt, .07);
    ball(elbow, .12, [0, -.31, 0], 'skin');
    elbows.push(elbow); return pivot;
  });
  const legs = [-1, 1].map(side => {
    const pivot = group(body, 'Leg', [side * .19, .78, 0]);
    box(pivot, [.26, .66, .29], [0, -.31, 0], 'charcoal', .075);
    box(pivot, [.29, .17, .45], [0, -.66, .075], 'navy', .06); return pivot;
  });
  const phone = group(elbows[1], 'Phone', [0, -.29, .115]);
  box(phone, [.22, .38, .055], [0, 0, 0], 'charcoal', .03);
  box(phone, [.17, .29, .012], [0, 0, .034], 'glass', .01);
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
  function update({ position: pos, yaw = 0, walking = false, ring = false, waving = false, usePhone = false, showLabel = true, time = 0 }) {
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
    if (usePhone) {
      arms[1].rotation.set(-.52, 0, -.12);
      elbows[1].rotation.x = -1.45;
    }
    if (waving) {
      arms[1].rotation.set(-.15, 0, -2.1 + Math.sin(time * 6) * .15);
      elbows[1].rotation.x = -.4;
    }
    phone.visible = usePhone;
    tag.visible = showLabel;
    tag.quaternion.copy(root.quaternion).invert();
  }
  return { root, update, updateView };
}
