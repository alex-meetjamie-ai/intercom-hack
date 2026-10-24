// Presentation adapter only. SIP, microphone audio and backend status use Alex's client.
import {createIntercomClient as createSipClient} from '@intercom/client';

export function createIntercomClient(options){
  const {baseUrl='',onApproval=()=>{},onRequestReady=()=>{},onError=()=>{},onEvent=()=>{}}=options;
  let socket=null,approval=null,starting=false,version=0,startedAt=0,pending=null,retry=null;
  function close(){
    clearTimeout(retry);
    const old=socket;socket=null;old?.close();approval=null;
    if(pending){clearTimeout(pending.timer);pending.reject(new Error('Call ended before approval was confirmed.'));pending=null;}
  }
  const sip=createSipClient({...options,onRequestReady:()=>{},onState:state=>{
    options.onState?.(state);
    if(state==='idle'&&!starting){version++;close();}
  }});
  async function notifications(id){
    const response=await fetch(`${baseUrl.replace(/\/$/,'')}/api/config`);
    if(!response.ok)throw new Error('Could not connect employee notifications.');
    const {token}=await response.json();
    if(id!==version)return;
    const url=new URL(`${baseUrl.replace(/\/$/,'')}/employee`,location.href);
    url.protocol=url.protocol==='https:'?'wss:':'ws:';url.searchParams.set('token',token);
    await new Promise((resolve,reject)=>{
      const current=socket=new WebSocket(url);let ready=false;
      const timeout=setTimeout(()=>{reject(new Error('Employee notifications timed out.'));current.close();},5000);
      current.onmessage=event=>{
        if(id!==version)return;
        const data=JSON.parse(event.data);
        if(data.type==='approvals'){
          if(!ready){ready=true;clearTimeout(timeout);resolve();}
          const requests=data.requests.filter(item=>Date.parse(item.created_at)>=startedAt);
          if(pending){
            const result=requests.find(item=>item.id===pending.id);
            if(result&&result.status!=='pending'){
              const done=pending;pending=null;clearTimeout(done.timer);
              if(result.status===done.expected)done.resolve(result);
              else done.reject(new Error(`Entry request ${result.status}.`));
            }
          }
          const next=requests.find(item=>item.status==='pending');
          const fresh=next&&next.id!==approval?.id;
          approval=next||null;onApproval(next||requests.at(-1)||null);
          if(fresh)onRequestReady(next);
        }else if(data.type==='error'){
          const error=new Error(data.message);
          if(pending){clearTimeout(pending.timer);pending.reject(error);pending=null;}else onError(error);
        }
      };
      current.onclose=()=>{
        clearTimeout(timeout);if(!ready)reject(new Error('Employee notifications disconnected.'));
        if(socket===current)socket=null;
        if(id===version&&sip.active)retry=setTimeout(()=>notifications(id).catch(onError),1500);
      };
      current.onerror=()=>current.close();
    });
  }
  async function ring(){
    if(starting||sip.active)return;
    starting=true;const id=++version;startedAt=Date.now();onApproval(null);options.onState?.('connecting');
    try{await notifications(id);if(id===version)await sip.ring();}
    catch(error){onError(error);close();options.onState?.('idle');}
    finally{starting=false;}
  }
  async function disconnect(){version++;starting=false;close();onApproval(null);return sip.disconnect();}
  async function decide(allow){
    if(!approval||!socket||socket.readyState!==WebSocket.OPEN)throw new Error('No connected entry request is awaiting approval.');
    if(pending)throw new Error('Your decision is already being sent.');
    const result=await new Promise((resolve,reject)=>{
      pending={id:approval.id,expected:allow?'allowed':'denied',resolve,reject,
        timer:setTimeout(()=>{pending=null;reject(new Error('Decision confirmation timed out.'));},5000)};
      socket.send(JSON.stringify({type:'decision',id:approval.id,decision:allow?'allow':'deny'}));
    });
    onEvent({kind:'Employee approval',title:allow?'Entry approved':'Entry denied',state:'success'});
    return result;
  }
  return {ring,connect:ring,disconnect,decide,getStatus:sip.getStatus,playAudio:sip.playAudio,
    destroy:()=>{version++;close();return sip.destroy();},get active(){return starting||sip.active;}};
}
