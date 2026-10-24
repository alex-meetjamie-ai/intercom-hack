// An explanatory animation only: no microphone, network requests or door tools.
const $ = id => document.getElementById(id);
const ns = 'http://www.w3.org/2000/svg';
function element(name, attrs = {}) {
  const el = document.createElementNS(ns, name);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  return el;
}

if ($('diagram-map')) initializeDiagramPage();

function initializeDiagramPage() {
const map = $('diagram-map'), svg = $('connections');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let playing = !reducedMotion.matches, visitor = 'Alex', step = 0, elapsed = 0, lastTime, view = 'system';
const duration = [4200, 4500, 4400, 4000, 5000, 3500];
const edges = {};
const specs = {
  sip: ['signal', 'SIP / WebSocket', 'call setup', true],
  media: ['audio', 'WebRTC / SRTP', 'two-way audio', true],
  cloud: ['audio', 'PCM / WebSocket', '16 kHz · secure WSS', true],
  tool: ['control', 'open_door tool', 'request + result', true],
  unlock: ['control', 'Check entry', 'name or arrival', false],
  status: ['state', 'Door status', 'HTTP · every 0.5 sec', false],
};
const fullSystem = buildFullSystem({onCaption: caption => {if(view==='system')$('step-caption').textContent=caption;}});
for (const [id, [type, label, detail, both]] of Object.entries(specs)) {
  const group = element('g', {class: `wire ${type}`});
  const path = element('path', {class: 'wire-base', 'marker-end': `url(#arrow-${type})`});
  if (both) path.setAttribute('marker-start', `url(#arrow-${type})`);
  const active = element('path', {class: 'wire-active'});
  const text = element('text', {class: 'wire-label', 'text-anchor': 'middle'});
  const line1 = element('tspan'), line2 = element('tspan', {dy: 12});
  line1.textContent = label; line2.textContent = detail; text.append(line1, line2);
  const dots = [element('circle', {class: 'wire-packet', r: 3}), element('circle', {class: 'wire-packet', r: 2})];
  group.append(path, active, text, ...dots); svg.append(group);
  edges[id] = {group, path, active, text, line1, line2, dots, length: 0, both, lit: false};
}
function rect(id) {
  const r = $(id).getBoundingClientRect(), m = map.getBoundingClientRect();
  return {x: r.left-m.left, y:r.top-m.top, w:r.width, h:r.height,
    r:r.right-m.left, b:r.bottom-m.top, cx:r.left-m.left+r.width/2};
}
function wire(id, d, x, y) {
  const edge = edges[id];
  edge.path.setAttribute('d', d); edge.active.setAttribute('d', d);
  edge.length = edge.path.getTotalLength();
  edge.text.setAttribute('y', y);
  edge.line1.setAttribute('x', x); edge.line2.setAttribute('x', x);
}
function draw() {
  if (map.hidden) return;
  const b = rect('browser-node'), s = rect('backend-node'), a = rect('agent-node'), d = rect('door-node');
  const width = map.clientWidth;
  svg.setAttribute('viewBox', `0 0 ${width} ${map.clientHeight}`);
  if (window.innerWidth > 900) {
    wire('sip', `M${b.r} ${b.y+82}H${s.x}`, (b.r+s.x)/2, b.y+61);
    wire('media', `M${b.r} ${b.y+163}H${s.x}`, (b.r+s.x)/2, b.y+142);
    wire('cloud', `M${s.r} ${s.y+82}H${a.x}`, (s.r+a.x)/2, s.y+61);
    wire('tool', `M${a.x} ${a.y+163}H${s.r}`, (s.r+a.x)/2, s.y+142);
    wire('unlock', `M${s.cx} ${s.b}V${d.y}`, s.cx+48, (s.b+d.y)/2-9);
    wire('status', `M${s.x} ${s.b-29}H${s.x-28}Q${s.x-40} ${s.b-29} ${s.x-40} ${s.b-17}V${s.b+65}Q${s.x-40} ${s.b+77} ${s.x-52} ${s.b+77}H${b.cx+12}Q${b.cx} ${s.b+77} ${b.cx} ${s.b+65}V${b.b}`, b.cx+36, s.b+57);
  } else if (window.innerWidth > 650) {
    wire('sip', `M${b.r} ${b.y+82}H${s.x}`, (b.r+s.x)/2, b.y+61);
    wire('media', `M${b.r} ${b.y+163}H${s.x}`, (b.r+s.x)/2, b.y+142);
    wire('cloud', `M${s.cx+29} ${s.b}V${a.y}`, s.cx+51, (s.b+a.y)/2-26);
    wire('tool', `M${a.cx-29} ${a.y}V${s.b}`, s.cx-50, (s.b+a.y)/2+20);
    wire('unlock', `M${s.x} ${s.b-29}H${s.x-27}Q${s.x-39} ${s.b-29} ${s.x-39} ${s.b-17}V${d.y+51}Q${s.x-39} ${d.y+63} ${s.x-51} ${d.y+63}H${d.r}`, (d.r+s.x)/2, d.y+40);
    wire('status', `M${s.cx} ${s.y}V${s.y-20}Q${s.cx} ${s.y-32} ${s.cx-12} ${s.y-32}H${b.cx+12}Q${b.cx} ${s.y-32} ${b.cx} ${s.y-20}V${b.y}`, (b.cx+s.cx)/2, s.y-43);
  } else {
    wire('sip', `M${b.cx-30} ${b.b}V${s.y}`, b.cx-54, (b.b+s.y)/2-11);
    wire('media', `M${b.cx+30} ${b.b}V${s.y}`, b.cx+55, (b.b+s.y)/2+19);
    wire('cloud', `M${s.cx+30} ${s.b}V${a.y}`, s.cx+55, (s.b+a.y)/2-11);
    wire('tool', `M${a.cx-30} ${a.y}V${s.b}`, s.cx-54, (s.b+a.y)/2+19);
    wire('unlock', `M${s.r} ${s.b-31}H${s.r+19}Q${s.r+31} ${s.b-31} ${s.r+31} ${s.b-19}V${d.y-33}Q${s.r+31} ${d.y-21} ${s.r+19} ${d.y-21}H${d.cx+12}Q${d.cx} ${d.y-21} ${d.cx} ${d.y-9}V${d.y}`, d.cx, d.y-55);
    wire('status', `M${s.x} ${s.y+77}H${s.x-19}Q${s.x-31} ${s.y+77} ${s.x-31} ${s.y+65}V${b.y+89}Q${s.x-31} ${b.y+77} ${s.x-19} ${b.y+77}H${b.x}`, b.x-27, (b.b+s.y)/2-31);
    edges.status.text.setAttribute('transform', `rotate(-90 ${b.x-27} ${(b.b+s.y)/2-31})`);
  }
  if (window.innerWidth > 650) edges.status.text.removeAttribute('transform');
  positionPackets(elapsed);
}
function render() {
  const alex = visitor === 'Alex';
  const stages = [
    {b:'A visitor presses Jamie.', s:'Accepting the SIP call…', a:'Ready to answer.', active:['sip'], nodes:['browser','backend'], caption:'SIP starts the call. Audio uses a separate WebRTC connection.'},
    {b:'You hear Jamie through your speaker.', s:'Returning Jamie’s voice to the browser.', a:'“Hi, this is Jamie. What is your name?”', active:['media','cloud'], nodes:['backend','agent'], caption:'ElevenLabs generates Jamie’s greeting. The backend sends the voice back to your browser.'},
    {b:`“My name is ${visitor}.”`, s:'Turning microphone audio into 16 kHz PCM.', a:`Listening: “My name is ${visitor}.”`, active:['media','cloud'], nodes:['browser','backend','agent'], caption:'Your microphone audio goes to the backend, then streams to ElevenLabs over a secure WebSocket.'},
    {b:'Waiting for Jamie’s answer…', s:'Employee notification → waiting for Allow / Deny.', a:'“Please wait while a colleague confirms.”', active:alex?['tool']:['cloud','media'], nodes:['agent','backend'], caption:alex?'The agent requests open_door. Admin receives a WebSocket notification. The backend waits for the employee to press Allow.':'Admin receives the visitor details over WebSocket. In this example the employee presses Deny; a missing match alone never makes that decision.'},
    {b:alex?'The door indicator turns green.':'The door indicator stays closed.', s:alex?'Employee pressed Allow → simulated door opens.':'Door remains closed.', a:alex?'“Thanks, Alex. The door is open.”':'Access refused.', active:alex?['unlock','status','cloud','media']:['status'], nodes:alex?['backend','door']:['door'], caption:alex?'After employee confirmation, the backend opens its simulated door and returns success to Jamie.':'The employee denied the request. The website continues to show “Door closed”.'},
    {b:'The door indicator shows closed.', s:alex?'Five seconds later → close the door.':'Ready for the next visitor.', a:'Conversation can continue.', active:['status'], nodes:['backend','door'], caption:alex?'After five seconds, the simulated door closes. Ending the call also closes it.':'The simulated door stayed closed throughout Bob’s visit.'},
  ];
  const current = stages[step];
  $('browser-message').textContent=current.b; $('backend-message').textContent=current.s; $('agent-message').textContent=current.a;
  $('step-caption').textContent=current.caption; $('step-count').textContent=`0${step+1} / 06`;
  $('browser-action').textContent=step===0?'PRESS TO CALL':'CALL CONNECTED';
  const open = alex && step===4;
  $('door-node').classList.toggle('door-open', open);
  $('browser-door').classList.toggle('open', open); $('browser-door').textContent=open?'Door open':'Door closed';
  $('diagram-door-title').textContent=open?'Door open':'Door closed'; $('simulation-badge').textContent=open?'OPEN':'CLOSED';
  $('diagram-door-detail').textContent=open?'Alex is admitted. Closes in 5 seconds.': !alex && step>=3?'An employee denied Bob in this example.':'Every visitor needs employee approval.';
  $('door-policy').textContent=open?'✓ Employee pressed Allow':!alex&&step>=3?'Employee pressed Deny':'Waiting for employee confirmation';
  for(const [id,edge] of Object.entries(edges)){edge.lit=current.active.includes(id);edge.group.classList.toggle('lit',edge.lit);}
  for(const id of ['browser','backend','agent','door']) $(id+'-node').classList.toggle('node-active',current.nodes.includes(id));
  document.querySelectorAll('[data-step]').forEach(el=>{if(Number(el.dataset.step)===step)el.setAttribute('aria-current','step');else el.removeAttribute('aria-current');});
  document.querySelectorAll('[data-visitor]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.visitor===visitor)));
  const labels = view === 'system' ? ['Ring','Ask','Listen','Decide','Unlock','Status'] : ['Connect','Ask','Listen','Decide','Act','Reset'];
  document.querySelectorAll('[data-step]').forEach((el,i)=>el.lastChild.textContent=labels[i]);
  fullSystem.render(step, visitor);
  updatePlayback();
}
function updatePlayback(){
  map.classList.toggle('is-paused',!playing);
  $('play-label').textContent=playing?'Pause':'Play'; $('toggle-play').setAttribute('aria-label',playing?'Pause animation':'Play animation');
  $('pause-icon').firstElementChild.setAttribute('d',playing?'M7 4v12M13 4v12':'M6 3l10 7-10 7Z');
}
function positionPackets(time){
  if (view === 'system') fullSystem.animate(time);
  for(const edge of Object.values(edges)){
    if(!edge.lit||!edge.length)continue;
    edge.dots.forEach((dot,i)=>{
      let t=(time/1800+i*.5)%1;
      if(edge.both&&i===1)t=1-t;
      const p=edge.path.getPointAtLength(t*edge.length);
      dot.setAttribute('cx',p.x);dot.setAttribute('cy',p.y);
    });
  }
  $('step-progress').style.transform=`scaleX(${Math.min(1,elapsed/duration[step])})`;
}
function frame(time){
  if(lastTime!==undefined&&playing&&!document.hidden){
    elapsed+=Math.min(time-lastTime,100);
    if(elapsed>=duration[step]){elapsed=0;step=(step+1)%6;render();}
    positionPackets(elapsed);
  }
  lastTime=time;
  requestAnimationFrame(frame);
}
$('toggle-play').onclick=()=>{playing=!playing;updatePlayback();};
$('replay').onclick=()=>{step=0;elapsed=0;playing=!reducedMotion.matches;render();positionPackets(0);};
document.querySelectorAll('[data-visitor]').forEach(el=>el.onclick=()=>{visitor=el.dataset.visitor;step=0;elapsed=0;render();positionPackets(0);});
document.querySelectorAll('[data-step]').forEach(el=>el.onclick=()=>{step=Number(el.dataset.step);elapsed=0;playing=false;render();positionPackets(0);});
reducedMotion.addEventListener('change',()=>{if(reducedMotion.matches){playing=false;updatePlayback();}});
document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>{
  view=el.dataset.view;
  $('system-view').hidden=view!=='system'; map.hidden=view!=='browser'; $('system-evidence').hidden=view!=='system';
  document.querySelectorAll('[data-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.view===view)));
  step=0;elapsed=0;render();draw();positionPackets(0);
});
$('system-zoom').onchange=()=>{$('system-svg').classList.toggle('detail-zoom',$('system-zoom').value==='detail');};
new ResizeObserver(draw).observe(map);
render();draw();document.fonts.ready.then(draw);requestAnimationFrame(frame);

}

export function buildFullSystem({root=document.getElementById('system-svg'), inspector=document.getElementById('pin-inspector'), onCaption=()=>{}, presentation=false} = {}) {
  const $ = id => root.querySelector(`#${id}`);
  // Photo order, not manufacturer pin numbers. Doorman terminal mapping is unknown.
  const pins=[
    ['a+','Red','#bd6655','Audio / control bus','Audio and control bus. The red wire stays on a+. A parallel tap is only proposed; no Doorman input terminal is verified.'],
    ['b−','Blue','#6197b4','Audio / control bus','Bus return, blue wire. It stays on b−. Do not assume b− is the same as the separate GND terminal; the Doorman tap remains unverified.'],
    ['E−','Red (2)','#bd6655','Floor bell','Floor/apartment bell, second red wire. Continues to E− on the indoor station. No connection to Doorman; this is not an unlock contact.'],
    ['E+','Black','#51584e','Floor bell','Floor/apartment bell, black wire. Continues to E+ on the indoor station. No connection to Doorman; this is not an unlock contact.'],
    ['+22','Green','#789f6a','Station supply','Indoor/video-station supply, green wire. Continues to +22 on the station. Do not feed the Pi or Doorman from this terminal in the proposed design.'],
    ['GND','White (1)','#f5f4ea','Supply return','Station supply return, first white wire. Continues to GND on the station. No proposed connection to Pi ground or Doorman ground.'],
    ['V+','White (2)','#f5f4ea','Video pair','Video signal, second white wire. Continues to V+ on the station. Video capture is not part of this adapter plan; a working camera feed is not verified.'],
    ['V−','Yellow','#d4b561','Video pair','Video signal, yellow wire. Continues to V− on the station. No connection to the proposed audio/control adapter.'],
  ];
  const text=(x,y,value,cls='sys-copy',extra='')=>`<text x="${x}" y="${y}" class="${cls}" ${extra}>${value}</text>`;
  const box=(x,y,w,h,cls='')=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="14" class="system-card ${cls}"/>`;
  const chip=(x,y,w,value,planned=false)=>`<rect x="${x}" y="${y}" width="${w}" height="22" rx="5" class="sys-chip ${planned?'planned':''}"/>${text(x+9,y+15,value,'sys-chip-text'+(planned?' planned':''))}`;
  root.innerHTML=`
    <title id="system-title">Jamie: SKS wall terminals, proposed ${presentation?'PCB':'Doorman adapter'}, network, Raspberry Pi, UniFi and voice agent</title>
    <desc id="system-description">All eight SKS terminals continue to the indoor station. Only a+ and b− have a proposed parallel branch, with a visible gap because ${presentation?'PCB':'Doorman'} compatibility and pin mapping are unverified. The adapter would use Wi-Fi to the LAN and a Raspberry Pi would use Ethernet. The Pi would host the emulator and voice backend. ${presentation?'Jamie uses tools for records, employee approval, door release and the elevator.':'Browser demo and ElevenLabs audio work on the Mac today; hardware and UniFi-to-agent integration remain planned.'}</desc>
    ${presentation?'':text(30,36,'01 / THE BUILDING &amp; THE ADAPTER','sys-kicker')}
    ${presentation?'':text(1670,36,'SOLID = EXISTING WIRING · DASHED = PLANNED', 'sys-small','text-anchor="end"')}
    <g id="full-paths"></g>
    <g id="full-building">${box(30,70,225,270)}
      ${text(50,101,'EXISTING SKS SYSTEM','sys-kicker')}${text(50,136,'Entrance panel','sys-title')}
      ${text(50,164,'The outside panel stays as is.')}
      ${text(50,206,'Bus a+','sys-mono')}${text(50,246,'Bus b−','sys-mono')}
      <path d="M50 269H235" class="sys-rule"/>
      ${text(50,295,'Building controller → door release')}
      ${text(50,318,'Unlock returns over the same bus.','sys-small')}
    </g>
    ${presentation?`<g id="full-pin-photo">
      <defs><clipPath id="sks-pins-photo-clip"><rect x="30" y="365" width="225" height="192" rx="14"/></clipPath></defs>
      <image href="/presentation-assets/sks-pins.png" x="30" y="365" width="225" height="192" preserveAspectRatio="xMidYMid meet" clip-path="url(#sks-pins-photo-clip)" role="img" aria-label="Photo of the SKS wall connector and its eight wired terminals"/>
    </g>`:`${text(35,403,'OTHER EXISTING CIRCUITS','sys-kicker')}
    ${text(35,434,'E− / E+ → floor bell')}${text(35,461,'+22 / GND → station power')}${text(35,488,'V+ / V− → video wiring')}
    ${text(35,521,'No camera feed verified here.','sys-small')}`}
    ${box(310,70,220,470)}
    ${text(332,102,'WALL CONNECTOR','sys-kicker')}${text(332,137,'SKS · 8 terminals','sys-title')}
    ${text(332,164,'Photo order: left → right','sys-small')}
    ${box(670,70,240,470)}
    ${text(690,102,'EXISTING INDOOR STATION','sys-kicker')}${text(690,137,'BSV2012','sys-title')}
    ${text(690,164,'All eight connections retained','sys-small')}
    <g id="full-pins"></g>
    ${text(332,567,'Measured: a+/b− 25.7 V DC','sys-small')}
    ${text(332,590,'+22/GND 28 V DC','sys-small')}
    ${text(332,613,'DC readings do not prove compatibility.','sys-small')}
    <g data-reveal-step="2">
    ${text(675,565,'PROPOSED PARALLEL TAP','sys-kicker')}
    ${presentation?'':text(675,640,'Other six terminals: no adapter tap.','sys-small')}
    <g id="full-doorman">${box(1070,70,290,330,'planned')}
      ${text(1090,102,'CANDIDATE ADAPTER','sys-kicker')}${presentation?`${text(1090,137,'Printed circuit board','sys-title')}${text(1090,167,'(PCB)','sys-title')}`:text(1090,137,'Doorman S3','sys-title')}
      ${presentation?'':chip(1090,151,184,'SKS SUPPORT UNVERIFIED',true)}
      ${text(1090,204,'ESP32-S3 · Wi-Fi')}
      ${text(1090,231,'+ separate audio extension')}
      ${text(1090,258,'Candidate audio / FSK receive + send','sys-small')}
      ${presentation?'':`<rect x="1086" y="277" width="258" height="69" rx="7" class="sys-unverified"/>
      ${text(1100,298,'SKS INPUT / OUTPUT: TBD','sys-unverified-text')}
      ${text(1100,321,'Exact pads, levels &amp; firmware unknown','sys-small')}
      ${text(1090,375,'No assumed SKS → A/B pin assignment','sys-small')}`}
    </g>
    <path d="M1018 279l-9 19m9 21-9 19M1043 279l-9 19m9 21-9 19" class="sys-gap"/>
    ${presentation?'':`${text(1023,240,'GAP','sys-unverified-text','text-anchor="middle"')}
    ${text(1012,437,'VERIFY BEFORE WIRING','sys-unverified-text')}
    ${text(1012,459,'This branch is not a wiring instruction.','sys-small')}`}
    ${presentation?'':`${box(1105,505,230,70,'planned')}
    ${text(1122,534,'Doorman: separate supply','sys-copy')}
    ${text(1122,555,'Power method / isolation to verify','sys-small')}`}
    </g>
    <g id="full-lan" data-reveal-step="3">${box(1450,125,220,220)}
      ${text(1470,157,'OFFICE NETWORK','sys-kicker')}${text(1470,192,'UniFi AP + LAN','sys-title')}
      ${text(1470,224,presentation?'PCB joins over Wi-Fi.':'Doorman joins over Wi-Fi.')}
      ${text(1470,251,'Pi connects over Ethernet.')}
      ${text(1470,278,'Updates from your Mac → Pi')}
      ${text(1470,317,'Local audio/control transport: planned','sys-small')}
    </g>
    ${presentation?'':text(30,680,'02 / SOFTWARE &amp; THE CONVERSATION','sys-kicker','data-reveal-step="3"')}
    ${presentation?`<g id="full-tools" data-reveal-step="5">
      <g id="full-tool-records">${box(30,750,250,94)}
        ${text(50,789,'Emails &amp; calendar','sys-title sys-tool-title')}
        ${text(50,819,'Mock records')}
      </g>
      <g id="full-tool-door">${box(30,867,250,94)}
        ${text(50,906,'Open door','sys-title sys-tool-title')}
        ${text(50,936,'Employee approval')}
      </g>
      <g id="full-tool-elevator">${box(30,984,250,94)}
        ${text(50,1023,'Call elevator','sys-title sys-tool-title')}
        ${text(50,1053,'Floor 0 → 5')}
      </g>
    </g>`:`<g id="full-browser" data-reveal-step="4">${box(30,775,250,225)}
      ${text(50,808,'TESTED ON THIS MAC','sys-kicker')}${text(50,843,'Browser intercom','sys-title')}
      <rect x="50" y="862" width="210" height="46" rx="7" fill="#df784f"/>
      ${text(68,891,'↗  Jamie','sys-title')}
      ${text(50,939,'SIP.js + microphone / speaker')}
      ${text(50,973,'Optional test entry point','sys-small')}
    </g>`}
    <g id="full-agent" data-reveal-step="4">${box(390,775,300,225)}
      ${presentation?`${text(410,843,'Jamie','sys-title')}
      ${text(410,889,'Voice agent')}
      ${text(410,927,'Running in the cloud','sys-small')}`:`
      ${text(410,808,'ELEVENLABS CLOUD','sys-kicker')}${text(410,843,'Jamie, the agent','sys-title')}
      ${text(410,883,'“Hello! What is your name?”','sys-copy','id="full-agent-speech"')}
      ${text(410,920,'Speech → decision → spoken reply')}
      ${text(410,947,'open_door → employee confirmation','sys-copy','data-reveal-step="5"')}
      ${text(410,977,'Internet required for this agent','sys-small')}`}
    </g>
    <g id="full-pi" data-reveal-step="3">${box(850,735,510,300,'dark planned')}
      ${text(875,768,'RASPBERRY PI · PLANNED HOST','sys-kicker sys-muted-white')}
      ${text(875,804,'The local bridge','sys-title sys-white')}
      ${text(875,831,'Current software runs on the Mac. Pi migration is pending.','sys-small sys-muted-white')}
      <rect x="872" y="849" width="466" height="54" rx="6" class="sys-module"/>
      ${text(888,871,'SKS driver ↔ emulated UniFi reader + hub','sys-copy sys-white')}
      ${text(888,891,'Receive ring / audio · send answer / hangup / unlock','sys-small sys-muted-white')}
      <g data-reveal-step="4"><rect x="872" y="914" width="466" height="54" rx="6" class="sys-module"/>
      ${text(888,936,'Voice backend · SIP / WebRTC ↔ PCM','sys-copy sys-white')}
      ${text(888,956,'Arrival lookup + door/lift tools · emulator integration pending','sys-small sys-muted-white')}
      </g>
      <g data-reveal-step="5"><circle cx="883" cy="995" r="5" id="full-door-dot" class="sys-indicator"/>
      ${text(897,999,'Demo: closed · real door position unknown','sys-copy sys-white','id="full-door-state"')}
      </g>
      ${text(875,1023,'Ethernet for updates · own PSU · no direct SKS-to-GPIO wiring','sys-small sys-muted-white')}
    </g>
    <g id="full-unifi" data-reveal-step="3">${box(1450,775,220,225)}
      ${text(1470,808,'OFFICE UDM','sys-kicker')}${text(1470,843,'UniFi Access','sys-title')}
      ${text(1470,881,'App calls &amp; unlock controls')}
      ${text(1470,911,'Separate emulator PoC tested','sys-small')}
      <g data-reveal-step="4">${text(1470,945,'Controller → agent SIP route:','sys-small')}
      ${text(1470,968,'NOT CONNECTED YET','sys-unverified-text')}</g>
    </g>
    ${presentation?'':text(30,1110,'Door release is a bus command to the building controller. E+/E− are bell inputs, not lock contacts.','sys-small')}
    ${presentation?'':text(1670,1110,'Schematic overview · not to scale','sys-small','text-anchor="end"')}
  `;
  const pinLayer=$('full-pins');
  pins.forEach(([name,color,stroke,fn,sourceDescription],i)=>{
    const description=presentation?sourceDescription.replaceAll('Doorman','PCB'):sourceDescription;
    const y=206+i*40;
    const group=element('g',{class:'pin-row',role:'button',tabindex:'0','aria-label':`Terminal ${i+1}: ${name}, ${color}. ${description}`,'aria-pressed':'false','data-pin':String(i+1)});
    group.innerHTML=`<rect x="320" y="${y-22}" width="580" height="35" rx="5" class="pin-bg"/>
      ${text(332,y,String(i+1).padStart(2,'0'),'pin-number')}${text(363,y,name,'pin-label')}${text(425,y,color,'pin-color')}
      ${i===5||i===6?`<path d="M530 ${y-5}H670" class="pin-white-outline"/>`:''}
      <path d="M530 ${y-5}H670" class="pin-wire" stroke="${stroke}"/>
      <circle cx="530" cy="${y-5}" r="5" class="pin-dot" fill="${stroke}"/><circle cx="670" cy="${y-5}" r="5" class="pin-dot" fill="${stroke}"/>
      ${text(690,y,name,'pin-label')}${text(747,y,fn,'pin-function')}`;
    const select=()=>{
      pinLayer.querySelectorAll('.pin-row').forEach(el=>{el.classList.toggle('selected',el===group);el.setAttribute('aria-pressed',String(el===group));});
      inspector.querySelector('span').textContent=`${String(i+1).padStart(2,'0')} / ${name}`;
      inspector.querySelector('p').textContent=description;
    };
    group.onclick=select;
    group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select();}};
    pinLayer.append(group);
  });
  const routes={
    building:['signal','M255 201H310',false],
    buildingReturn:['signal','M255 241H310',false],
    tapA:['control','M565 201V584H960V291H1008',true],
    tapB:['control','M600 241V615H990V331H1008',true],
    wifi:['audio','M1360 200H1450',true],
    ethernet:['audio','M1560 345V595Q1560 615 1540 615H1295V735',true],
    power:['state','M1215 505V400',true],
    sip:['signal','M280 830H305V700H800V861H850',false],
    media:['audio','M280 880H330V729H775V937H850',false],
    cloud:['audio','M850 922H690',false],
    tool:['control','M690 970H850',false],
    native:['signal','M1360 854H1450',true],
    pendingSip:['signal','M1450 929H1360',true],
    status:['state','M850 1005H810V1070H155V1000',false],
  };
  if(presentation){
    // Tools occupy the former browser block; no browser media wires remain.
    for(const id of ['power','sip','media','status'])delete routes[id];
    routes.toolRecords=['control','M390 920H335V797H280',false];
    routes.toolDoor=['control','M390 920H335V914H280',false];
    routes.toolElevator=['control','M390 920H335V1031H280',false];
  }
  // Optional presentation builds: the ordinary How it works page shows everything.
  const revealSteps={building:1,buildingReturn:1,tapA:2,tapB:2,power:2,wifi:3,ethernet:3,native:3,sip:4,media:4,cloud:4,pendingSip:4,tool:5,toolRecords:5,toolDoor:5,toolElevator:5,status:5};
  const flowLayer=$('full-paths'), flows={};
  for(const [id,[type,d,planned]] of Object.entries(routes)){
    const group=element('g',{class:'system-flow','data-flow':id,'data-reveal-step':revealSteps[id]});
    const path=element('path',{d,class:`system-path ${type} ${planned?'planned':''}`});
    const dots=[element('circle',{r:4,class:`system-packet ${type}`}),element('circle',{r:3,class:`system-packet ${type}`})];
    group.append(path,...dots);flowLayer.append(group);flows[id]={group,path,dots,lit:false};
  }
  // Deliberately disconnected stubs: there is no verified Doorman pin mapping.
  flowLayer.insertAdjacentHTML('beforeend',`
    <g data-reveal-step="2"><path d="M1044 291H1070M1044 331H1070" class="system-path planned control"/>
    <circle cx="565" cy="201" r="4" fill="#ba7f52"/><circle cx="600" cy="241" r="4" fill="#ba7f52"/>
    </g>
    <g data-reveal-step="3">${text(1405,179,'Wi-Fi','sys-path-label','text-anchor="middle"')}
    ${text(1427,602,'Ethernet / RJ45','sys-path-label','text-anchor="middle"')}
    ${text(1305,688,'Audio + events ↔ commands','sys-path-label')}
    ${text(1305,709,'Local transport still to implement','sys-path-label warn')}
    </g>
    <g data-reveal-step="4">${presentation?'':`${text(535,690,'SIP over WebSocket · call setup','sys-path-label','text-anchor="middle"')}
    ${text(535,752,'WebRTC / SRTP · microphone ↔ speaker','sys-path-label','text-anchor="middle"')}`}
    ${text(770,895,'PCM / WSS','sys-path-label','text-anchor="middle"')}
    ${text(770,912,'16 kHz audio','sys-path-label','text-anchor="middle"')}
    </g>
    ${text(770,958,'Tool call','sys-path-label','text-anchor="middle" data-reveal-step="5"')}
    ${text(1405,827,'Emulator','sys-path-label','text-anchor="middle" data-reveal-step="3"')}
    ${text(1405,914,'SIP: TBD','sys-path-label warn','text-anchor="middle" data-reveal-step="4"')}
    ${presentation?text(335,772,'Tool calls','sys-path-label','text-anchor="middle" data-reveal-step="5"'):text(480,1055,'Demo door status → browser · HTTP polling','sys-path-label','text-anchor="middle" data-reveal-step="5"')}
  `);
  const stageFlows=[['building','buildingReturn','tapA','tapB','wifi','ethernet','native'],['cloud','ethernet','wifi','tapA','tapB','building','buildingReturn'],['building','buildingReturn','tapA','tapB','wifi','ethernet','cloud'],['tool','toolRecords','toolDoor','toolElevator'],['ethernet','wifi','tapA','tapB','building','buildingReturn','status'],['status']];
  let phase=0, isAlex=true;
  return {
    render(index,name){
      phase=index;isAlex=name==='Alex';
      const captions=[
        'Planned: a visitor rings the unchanged SKS entrance. A parallel a+/b− adapter would report the call over Wi-Fi → LAN → Ethernet → Pi. The orange gap is the unverified SKS/Doorman interface.',
        'Planned: the Pi bridges Jamie’s greeting from ElevenLabs back through Doorman to the visitor. The existing indoor station keeps its own connections.',
        `Planned: “My name is ${name}” travels back over the SKS audio bus, Doorman and the Pi, then streams to ElevenLabs. Browser ↔ backend ↔ agent audio already works on the Mac.`,
        isAlex?'Jamie requests open_door(name: Alex). Admin receives a WebSocket notification and the backend waits for employee confirmation.':'Admin receives Bob’s details over WebSocket. In this example the employee denies him; the original indoor station remains independent.',
        isAlex?'Planned hardware path: backend → SKS driver → Doorman transmit → a+/b− → building door controller. Today only the simulated door opens; E+/E− are never used for unlocking.':'Bob is refused. No bus unlock command is sent. The website’s simulated door remains closed.',
        'The demo resets after five seconds. A physical unlock command would not tell us whether the door leaf is open or closed; that needs a separate door-position signal.',
      ];
      onCaption(captions[index]);
      if(!presentation)$('full-agent-speech').textContent=index===2?`“My name is ${name}.”`:index===3?'“Waiting for a colleague.”':index>=4?(isAlex?'“Thanks, Alex.”':'“Sorry, Bob.”'):'“Hello! What is your name?”';
      const open=isAlex&&index===4;
      $('full-door-state').textContent=open?'Demo: open · physical unlock not connected':'Demo: closed · real door position unknown';
      $('full-door-dot').classList.toggle('open',open);
      const active=!isAlex&&index===3?['cloud']:!isAlex&&index===4?['status']:stageFlows[index];
      for(const [id,edge] of Object.entries(flows)){edge.lit=active.includes(id);edge.group.classList.toggle('active',edge.lit);}
    },
    animate(time){
      for(const [id,edge] of Object.entries(flows)){
        if(!edge.lit || edge.group.style.display==='none')continue;
        const length=edge.path.getTotalLength();
        edge.dots.forEach((dot,i)=>{
          let t=(time/2600+i*.5)%1;
          // Packet direction describes messages, not current in individual bus wires.
          if(((phase===4&&isAlex)||phase===1)&&['wifi','ethernet','tapA','tapB','building','buildingReturn'].includes(id))t=1-t;
          if(id==='cloud'&&(phase===1||phase===3))t=1-t;
          const p=edge.path.getPointAtLength(t*length);dot.setAttribute('cx',p.x);dot.setAttribute('cy',p.y);
        });
      }
    },
  };
}
