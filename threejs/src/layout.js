// Plan coordinates: the street is +Z, the courtyard is central, and the
// office spans X across the rear. Its compact lift/terrace annex projects
// into the courtyard from the courier-left part of that long front edge.
export const TOP=16;
export const OFFICE_ROTATION=0;
export const ROOF_ROTATION=-Math.PI/2;
export const ROOM_ROTATION=-Math.PI/2;
export const OFFICE_ORIGIN=[-6.5,TOP,-14];
export function officePoint([x,y,z]) {
  return [OFFICE_ORIGIN[0]+x,OFFICE_ORIGIN[1]+y,OFFICE_ORIGIN[2]+z];
}
export function officeLocal([x,y,z]) {
  return [x-OFFICE_ORIGIN[0],y-OFFICE_ORIGIN[1],z-OFFICE_ORIGIN[2]];
}
// Interior orientation is independent of the fixed floor and terrace.
export function roomPoint([x,y,z]) {
  return officePoint([-z,y,x-.245]);
}
export const OFFICE_DOOR_LOCAL=[-6,0,6.12];
export const OFFICE_DOOR=officePoint(OFFICE_DOOR_LOCAL);
export const HOST_LANDING=officePoint([-6,0,6.7]);
export const COURIER_LANDING=[HOST_LANDING[0],TOP,-6.15];
export const LIFT_POSITION=[-9,0,-6.55];
export const LIFT_OPENING={left:-10.56,right:-7.44,back:-8.06,front:-5.1};
export const TERRACE={left:-17.3,right:-7.4,back:-8.095,front:-3.445};
export const REAR_BUILDING={left:-17.5,right:11,back:-20.55,front:-8.15};

// Rear passage shown to the right of the elevator in the courtyard photo.
export const REAR_PASSAGE={centerX:-2.2,width:3.5,height:4.4};

// Shared physical contact points keep animation, controls and cameras aligned.
export const INTERCOM_BUTTON=[2.04,1.22,10.988];
export const LIFT_CALL_BUTTON=[-6.85,1.25,-5.85];
export const PHONE_POSE={position:[.26,1.42,.60],rotationX:-1.9,rotationZ:Math.PI};
export const PHONE_CHOICES={yes:[.076,-.205,.029],no:[-.076,-.205,.029]};
export function phonePoint(position,yaw,point=[0,0,0]){
  const [px,py,z]=point,c=Math.cos(PHONE_POSE.rotationX),s=Math.sin(PHONE_POSE.rotationX);
  const cz=Math.cos(PHONE_POSE.rotationZ),sz=Math.sin(PHONE_POSE.rotationZ);
  const x=px*cz-py*sz,y=px*sz+py*cz;
  const local=[PHONE_POSE.position[0]+x,PHONE_POSE.position[1]+y*c-z*s,PHONE_POSE.position[2]+y*s+z*c];
  return [position[0]+local[0]*Math.cos(yaw)+local[2]*Math.sin(yaw),position[1]+local[1],position[2]-local[0]*Math.sin(yaw)+local[2]*Math.cos(yaw)];
}
