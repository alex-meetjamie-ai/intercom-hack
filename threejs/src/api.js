// The whole story works locally. Configure the URL only when your backend is ready.
export async function sendTourEvent(stepId,{event='tour_step_entered',signal}={}) {
  const url=import.meta.env.VITE_TOUR_EVENT_URL?.trim();
  if(!url)return;
  const response=await fetch(url,{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({event,step:stepId}),signal:signal??AbortSignal.timeout(5000),
  });
  if(!response.ok)throw new Error(`Tour event failed (${response.status})`);
}
