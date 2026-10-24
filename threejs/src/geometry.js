import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

export const palette = {
  cream: '#eee4cf', ivory: '#fcf6e9', wall: '#e4d9bf', stone: '#b8b8a6',
  wood: '#c6a078', brown: '#6d5341', darkWood: '#574b3f', coral: '#d87761',
  pink: '#edb09b', teal: '#528c80', navy: '#304b4d', steel: '#56666a',
  glass: '#b8d6d3', mint: '#b2c5a8', green: '#66875c', yellow: '#dfb854',
  charcoal: '#3f4947', paper: '#fff9ee', skin: '#e5b294', hair: '#644b3b',
};
const materials = new Map();
const geometries = new Map();
export function material(color, options = {}) {
  const key = JSON.stringify([color, options]);
  if (!materials.has(key)) materials.set(key, new THREE.MeshStandardMaterial({
    color: palette[color] || color, roughness: .83, ...options,
  }));
  return materials.get(key);
}
export function group(parent, name, position = [0, 0, 0]) {
  const g = new THREE.Group(); g.name = name; g.position.fromArray(position); parent?.add(g); return g;
}
export function mesh(parent, geometry, color, position = [0, 0, 0]) {
  const m = new THREE.Mesh(geometry, typeof color === 'string' ? material(color) : color);
  m.position.fromArray(position); m.castShadow = true; m.receiveShadow = true; parent.add(m); return m;
}
export function box(parent, size, position, color = 'cream', radius = .03) {
  const key = JSON.stringify(['box', ...size, radius]);
  if (!geometries.has(key)) geometries.set(key, radius > 0
    ? new RoundedBoxGeometry(...size, 2, Math.min(radius, ...size.map(v => v / 3)))
    : new THREE.BoxGeometry(...size));
  return mesh(parent, geometries.get(key), color, position);
}
export function ball(parent, radius, position, color = 'green', scale = [1, 1, 1]) {
  const key = `ball-${radius}`;
  if (!geometries.has(key)) geometries.set(key, new THREE.SphereGeometry(radius, 12, 10));
  const b = mesh(parent, geometries.get(key), color, position); b.scale.fromArray(scale); return b;
}
export function cylinder(parent, radius, height, position, color = 'teal', top = radius) {
  const key = `cyl-${radius}-${top}-${height}`;
  if (!geometries.has(key)) geometries.set(key, new THREE.CylinderGeometry(top, radius, height, 16));
  return mesh(parent, geometries.get(key), color, position);
}
export function beam(parent, start, end, thickness, color = 'steel') {
  const a = new THREE.Vector3(...start), b = new THREE.Vector3(...end);
  const obj = box(parent, [thickness, a.distanceTo(b), thickness], a.clone().add(b).multiplyScalar(.5).toArray(), color, 0);
  obj.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.sub(a).normalize()); return obj;
}
export function label(parent, text, width, height, position, { color = '#304b4d', background = '#fcf6e9', font = '600', size = .53 } = {}) {
  const canvas = document.createElement('canvas'); canvas.width = 1024; canvas.height = Math.round(1024 * height / width);
  const c = canvas.getContext('2d'); c.fillStyle = background; c.fillRect(0, 0, canvas.width, canvas.height);
  c.fillStyle = color; c.font = `${font} ${canvas.height * size}px sans-serif`; c.textAlign = 'center'; c.textBaseline = 'middle';
  c.fillText(text, canvas.width / 2, canvas.height * .52, canvas.width * .91);
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
  const m = mesh(parent, new THREE.PlaneGeometry(width, height), new THREE.MeshBasicMaterial({ map: texture, side: THREE.DoubleSide }), position);
  m.castShadow = false; return m;
}
export function plant(parent, position, scale = 1, autumn = false) {
  const g = group(parent, 'Plant', position); g.scale.setScalar(scale);
  cylinder(g, .26, .48, [0, .24, 0], 'coral', .34);
  cylinder(g, .06, 1.1, [0, 1, 0], 'brown');
  for (const [x, y, z] of [[-.22, .9, 0], [.24, 1.2, .05], [-.12, 1.5, -.12], [.1, 1.8, 0]]) {
    const leaf = ball(g, .28, [x, y, z], autumn ? 'yellow' : 'green', [.75, 1.4, .7]); leaf.rotation.z = -x * 2;
  }
  return g;
}
export function tree(parent, position, color = 'yellow') {
  const g = group(parent, 'Courtyard tree', position);
  cylinder(g, .15, 2.6, [0, 1.3, 0], 'brown', .09);
  for (const [x, y, z, s] of [[0, 3, 0, 1], [-.6, 2.8, .2, .7], [.6, 3.3, 0, .8], [0, 3.8, -.2, .65]])
    ball(g, 1, [x, y, z], color, [s, s * .9, s]);
  return g;
}
export function fadeable(g) {
  const list = [];
  g.traverse((object) => {
    if (!object.isMesh) return;
    object.material = object.material.clone(); list.push(object);
  });
  return (opacity) => {
    g.visible = opacity > .005;
    for (const m of list) {
      m.material.opacity = opacity;
      m.material.transparent = opacity < .999;
      m.material.depthWrite = opacity > .95;
      m.castShadow = opacity > .95;
    }
  };
}
