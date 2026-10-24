import {UserAgent,Inviter,SessionState} from 'sip.js';

export function createIntercomClient({baseUrl='',audio,onStatus=()=>{},onState=()=>{},onError=()=>{},onAudioBlocked=()=>{}}){
  const base=baseUrl.replace(/\/$/,'');
  let lastStatus=null;
  async function backendJson(path){
    const response=await fetch(`${base}${path}`,{signal:AbortSignal.timeout(5000)});
    if(!response.ok)throw new Error(`Backend unavailable (${response.status}).`);
    return response.json();
  }
  function sipUrl(token){
    const url=new URL(`${base}/sip`,location.href);
    url.protocol=url.protocol==='https:'?'wss:':'ws:';url.searchParams.set('token',token);
    return url.href;
  }

  let ua,session,starting=false,refreshing=false;
  async function play(){
    try{await audio.play();onAudioBlocked(false);}catch{onAudioBlocked(true);}
  }
  function clean(){
    const old=ua;ua=null;session=null;starting=false;
    audio.pause();audio.srcObject=null;onState('idle');onAudioBlocked(false);
    if(old)old.stop().catch(()=>{});
  }
  async function refresh(){
    if(refreshing)return;
    refreshing=true;
    try{const state=await backendJson('/api/status');lastStatus=state;onStatus(state);return state;}
    catch{onState(session?'connected':'offline');}
    finally{refreshing=false;}
  }
  async function hangup(){
    const current=session;
    try{
      if(current?.state===SessionState.Established)await current.bye();
      else if(current?.state===SessionState.Establishing)await current.cancel();
    }finally{clean();await refresh();}
  }
  async function start(){
    if(starting||session)return;
    starting=true;onState('connecting');
    try{
      const status=await backendJson('/api/status');lastStatus=status;onStatus(status);
      if(!status.agent_configured)throw new Error('This backend needs its ElevenLabs agent configured before voice calls can start.');
      const {token}=await backendJson('/api/config');
      ua=new UserAgent({
        uri:UserAgent.makeURI('sip:visitor@localhost'),displayName:'Pizza delivery',
        transportOptions:{server:sipUrl(token)},logBuiltinEnabled:false,
        sessionDescriptionHandlerFactoryOptions:{constraints:{audio:true,video:false},peerConnectionConfiguration:{iceServers:[]},iceGatheringTimeout:1500},
        delegate:{onDisconnect:()=>{if(session){onError(new Error('Voice connection lost.'));clean();}}},
      });
      await ua.start();
      const current=session=new Inviter(ua,UserAgent.makeURI('sip:jamie@localhost'));
      current.stateChange.addListener(state=>{
        if(state===SessionState.Established){
          starting=false;onState('connected');
          const pc=current.sessionDescriptionHandler?.peerConnection;
          if(pc){audio.srcObject=new MediaStream(pc.getReceivers().map(r=>r.track).filter(Boolean));play();}
        }else if(state===SessionState.Terminated)clean();
      });
      await current.invite({requestDelegate:{onReject:async()=>{
        const status=await refresh();onError(new Error(status?.error||'The voice backend could not answer.'));
      }}});
    }catch(error){
      onError(new Error(error.name==='NotAllowedError'?'Allow microphone access to speak to Jamie.':error.message||'Could not start voice.'));
      clean();
    }
  }
  refresh();const timer=setInterval(refresh,1000);
  window.addEventListener('pagehide',()=>{clearInterval(timer);hangup();},{once:true});
  async function decide(allow){
    if(!allow){await hangup();return lastStatus;}
    const status=await refresh();
    if(status?.door!=='open')throw new Error('Speak to Jamie to request entry. The existing backend has no manual Yes endpoint.');
    return status;
  }
  function destroy(){clearInterval(timer);return hangup();}
  return {ring:start,connect:start,disconnect:hangup,getStatus:refresh,decide,playAudio:play,destroy,get active(){return Boolean(starting||session);}};
}
