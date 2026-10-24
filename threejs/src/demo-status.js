export function createDemoStatus({onStop=()=>{},onDecision=()=>{}}={}){
  const panel=document.createElement('aside');panel.className='demo-status';
  panel.innerHTML='<div class="admin-kicker">JAMIE · LIVE ADMIN</div><div class="demo-body"><div class="admin-state"><div><span>Door</span><strong data-door>Closed</strong></div><div><span>Elevator</span><strong data-lift>Floor 5</strong></div></div><section class="admin-activity"><span class="admin-label">LATEST ACTION</span><p data-action>Waiting for a call</p></section><section class="admin-conversation" hidden><span class="admin-label" data-speaker></span><p data-words></p></section><section class="admin-approval" hidden><span class="admin-label">ENTRY REQUEST</span><p data-visitor></p><div class="admin-decisions"><button type="button" data-decision="no">No</button><button type="button" data-decision="yes">Yes, let them in</button></div></section><button type="button" class="demo-stop" aria-label="Stop demo and call"><span aria-hidden="true">■</span> Stop</button></div>';
  panel.setAttribute('aria-label','Presentation status');document.getElementById('app').append(panel);
  let index=0,connection='idle',running=false,approval=null,transitioning=false;
  const stop=panel.querySelector('.demo-stop');
  stop.classList.add('emergency-stop');
  const links=document.createElement('nav');links.className='demo-shortcuts';links.setAttribute('aria-label','Demo controls and pages');
  links.append(stop);
  for(const [name,path] of [['Intercom','/'],['How it works','/how-it-works'],['Admin','/admin']]){
    const link=document.createElement('a');
    link.textContent=name+' ↗';link.href=new URL(path,import.meta.env.VITE_WEBSITE_URL).href;
    link.target='_blank';link.rel='noopener noreferrer';link.setAttribute('aria-label',name+' (opens in a new tab)');
    links.append(link);
  }
  document.getElementById('app').append(links);
  stop.addEventListener('click',onStop);
  const decisions=[...panel.querySelectorAll('[data-decision]')];
  decisions.forEach(button=>button.addEventListener('click',()=>onDecision(button.dataset.decision)));
  function updateApproval(request){
    approval=request?.status==='pending'?request:null;
    panel.querySelector('.admin-approval').hidden=!approval;
    panel.querySelector('[data-visitor]').textContent=approval?`${approval.name || 'Visitor'} is at the door`:'';
    render();
  }
  function render(){
    decisions.forEach(button=>{button.disabled=!approval||transitioning||index!==1;});
    stop.disabled=!(running||connection==='connecting'||connection==='connected'||connection==='disconnecting');
    panel.dataset.connection=connection;
  }
  function event(){ /* Errors are displayed by the main demo. */ }
  function updateFrame(next,state,busy){index=next;transitioning=busy;running=busy||index>0;render();}
  function updateBackend(state){
    panel.querySelector('[data-door]').textContent=state.door==='open'?'Open':'Closed';
    panel.querySelector('[data-door]').dataset.open=String(state.door==='open');
    panel.querySelector('[data-lift]').textContent=`Floor ${state.elevator?.label??'—'}`;
    const action=state.actions?.at(-1);
    const names={check_calendar_emails:'Checking email & calendar',employee_approval:'Waiting for your approval',employee_decision:'Decision sent to Jamie',open_door:'Opening the door',send_elevator:'Sending the elevator',elevator_auto_return:'Elevator returning to office'};
    panel.querySelector('[data-action]').textContent=action?(action.ok?names[action.tool]||action.text:action.text):'Waiting for a call';
    const message=state.transcript?.at(-1);
    panel.querySelector('.admin-conversation').hidden=!message;
    panel.querySelector('[data-speaker]').textContent=message?.speaker==='You'?'VISITOR':message?.speaker||'';
    panel.querySelector('[data-words]').textContent=message?.text||'';
  }
  function setCall(state){connection=state;render();}
  render();return {event,updateFrame,updateBackend,updateApproval,setCall};
}
