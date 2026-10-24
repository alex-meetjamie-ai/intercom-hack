import {stops} from './journey.js';

export function createDemoStatus({onStop=()=>{},onDecision=()=>{},onRaptor=()=>{},onSound=()=>true}={}){
  const panel=document.createElement('aside');panel.className='demo-status';
  panel.innerHTML='<div class="admin-kicker">JAMIE · LIVE ADMIN</div><div class="demo-body"><div class="admin-state"><div><span>Door</span><strong data-door>Closed</strong></div><div><span>Elevator</span><strong data-lift>Floor 5</strong></div></div><section class="admin-activity"><span class="admin-label">LATEST ACTION</span><p data-action>Waiting for a call</p></section><section class="admin-conversation" hidden><span class="admin-label" data-speaker></span><p data-words></p></section><button type="button" class="demo-stop" aria-label="Stop demo and call"><span aria-hidden="true" data-control-icon>■</span><span data-control-label>Stop</span></button></div>';
  panel.setAttribute('aria-label','Presentation status');document.getElementById('app').append(panel);
  const stack=document.createElement('div');stack.className='presentation-sidebar';
  panel.replaceWith(stack);stack.append(panel);
  const phone=document.createElement('section');phone.className='presentation-phone';phone.hidden=true;
  phone.setAttribute('aria-label',"Egor's phone");
  phone.innerHTML='<div class="phone-speaker" aria-hidden="true"></div><div class="phone-owner">EGOR’S PHONE</div><div class="phone-notification"><span class="phone-app">JAMIE · INTERCOM</span><h2 data-visitor>Visitor at the door</h2><p data-visit-detail>Entry request</p><span data-approval-state hidden></span></div><div class="admin-decisions"><button type="button" data-decision="no">No</button><button type="button" data-decision="yes">Yes</button></div><div class="phone-home" aria-hidden="true"></div>';
  stack.append(phone);
  let index=0,connection='idle',running=false,approval=null,lastRequest=null,transitioning=false,phoneScene=false,conversationStarted=false,readyToStart=true;
  const stop=panel.querySelector('.demo-stop');
  stop.classList.add('emergency-stop');
  const links=document.createElement('nav');links.className='demo-shortcuts';links.setAttribute('aria-label','Demo controls and pages');
  links.append(stop);
  const raptorShortcut=document.createElement('button');raptorShortcut.type='button';raptorShortcut.className='raptor-shortcut';
  raptorShortcut.textContent='★';raptorShortcut.title='Restart raptor scene';raptorShortcut.setAttribute('aria-label','Restart raptor scene');
  raptorShortcut.addEventListener('click',onRaptor);links.append(raptorShortcut);
  const sound=document.createElement('button');sound.type='button';sound.className='ambience-toggle';sound.textContent='♫';sound.title='Mute ambience';sound.setAttribute('aria-label','Mute ambience');sound.setAttribute('aria-pressed','true');
  sound.addEventListener('click',()=>{const enabled=onSound();sound.textContent=enabled?'♫':'♪';sound.setAttribute('aria-pressed',String(enabled));sound.title=enabled?'Mute ambience':'Enable ambience';sound.setAttribute('aria-label',sound.title);});links.append(sound);
  const pages=document.createElement('nav');pages.className='demo-pages';pages.setAttribute('aria-label','Related pages');
  for(const [name,path] of [['Intercom','/'],['How it works','/how-it-works'],['Admin','/admin']]){
    const link=document.createElement('a');
    link.textContent=name+' ↗';link.href=new URL(path,import.meta.env.VITE_WEBSITE_URL).href;
    link.target='_blank';link.rel='noopener noreferrer';link.setAttribute('aria-label',name+' (opens in a new tab)');
    pages.append(link);
  }
  document.getElementById('app').append(links,pages);
  stop.addEventListener('click',onStop);
  const decisions=[...phone.querySelectorAll('[data-decision]')];
  decisions.forEach(button=>button.addEventListener('click',()=>onDecision(button.dataset.decision)));
  function updateApproval(request){
    approval=request?.status==='pending'?request:null;
    if(request)lastRequest=request;
    else if(index===0)lastRequest=null;
    phone.querySelector('[data-visitor]').textContent=lastRequest?.name?`${lastRequest.name} is at the door`:'Visitor at the door';
    const detail=lastRequest?.matched_records?.[0]?.title||'';
    phone.querySelector('[data-visit-detail]').textContent=detail;
    phone.querySelector('[data-visit-detail]').hidden=!detail;
    phone.querySelector('[data-approval-state]').textContent=({pending:'Waiting for your approval',allowed:'Entry approved',denied:'Entry denied',expired:'Request expired',cancelled:'Call ended'})[lastRequest?.status]||'No pending request';
    render();
  }
  function render(){
    const showPhone=phoneScene||index===1||Boolean(approval);
    phone.hidden=!showPhone;stack.classList.toggle('has-phone',showPhone);
    decisions.forEach(button=>{button.disabled=!approval||transitioning||(index!==1&&index!==10);});
    const active=running||['connecting','connected','disconnecting'].includes(connection);
    const mode=active?'stop':readyToStart?'start':'restart';
    if(stop.dataset.mode!==mode){
      stop.dataset.mode=mode;
      stop.querySelector('[data-control-icon]').textContent=active?'■':readyToStart?'▶':'↻';
      stop.querySelector('[data-control-label]').textContent=active?'Stop':readyToStart?'Start':'Restart';
      stop.setAttribute('aria-label',active?'Stop demo and call':readyToStart?'Start presentation':'Restart presentation');
    }
    stop.disabled=false;
    panel.dataset.connection=connection;
  }
  function event(){ /* Errors are displayed by the main demo. */ }
  function updateFrame(next,state,busy){readyToStart=Boolean(state.readyToStart);index=next;phoneScene=Boolean(state.phoneNotice&&state.phone>.1);
    if(state.phoneNotice){
      phone.querySelector('[data-visitor]').textContent='Another visitor?';
      phone.querySelector('[data-visit-detail]').textContent='Movement at the street door';
      phone.querySelector('[data-approval-state]').textContent='New visitor detected';
    }
    transitioning=busy;running=busy||(index>0&&index<stops.length-1);render();}
  function updateBackend(state){
    panel.querySelector('[data-door]').textContent=state.door==='open'?'Open':'Closed';
    panel.querySelector('[data-door]').dataset.open=String(state.door==='open');
    panel.querySelector('[data-lift]').textContent=`Floor ${state.elevator?.label??'—'}`;
    const action=state.actions?.at(-1);
    const names={check_calendar_emails:'Checking email & calendar',employee_approval:'Waiting for your approval',employee_decision:'Decision sent to Jamie',open_door:'Opening the door',send_elevator:'Sending the elevator',elevator_auto_return:'Elevator returning to office'};
    panel.querySelector('[data-action]').textContent=action?(action.ok?names[action.tool]||action.text:action.text):'Waiting for a call';
    const message=conversationStarted?state.transcript?.at(-1):null;
    panel.querySelector('.admin-conversation').hidden=!message;
    panel.querySelector('[data-speaker]').textContent=message?.speaker==='You'?'VISITOR':message?.speaker||'';
    panel.querySelector('[data-words]').textContent=message?.text||'';
  }
  function resetConversation(){
    conversationStarted=false;
    panel.querySelector('.admin-conversation').hidden=true;
    panel.querySelector('[data-speaker]').textContent='';
    panel.querySelector('[data-words]').textContent='';
  }
  function setCall(state){
    if(state==='connecting')resetConversation();
    if(state==='connected')conversationStarted=true;
    connection=state;render();
  }
  render();return {event,updateFrame,updateBackend,updateApproval,setCall,resetConversation};
}
