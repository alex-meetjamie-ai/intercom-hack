// Original music loop with a locally bundled Berlin traffic field recording.
export function createAmbience(){
  let context,music,traffic,master,timer,nextNote=0,beat=0,enabled=true,playing=false;
  let street=false,voice=false,muted=false,trafficSource=null,trafficLoading=null;
  const chords=[[48,55,59,64],[45,52,55,60],[41,48,52,57],[43,50,55,59]];
  const hz=midi=>440*2**((midi-69)/12);
  function note(midi,at,length=.8){
    const oscillator=context.createOscillator(),envelope=context.createGain();
    oscillator.type='sine';oscillator.frequency.value=hz(midi);
    envelope.gain.setValueAtTime(0,at);envelope.gain.linearRampToValueAtTime(.13,at+.018);
    envelope.gain.exponentialRampToValueAtTime(.001,at+length);
    oscillator.connect(envelope);envelope.connect(music);oscillator.start(at);oscillator.stop(at+length+.02);
  }
  function loadTraffic(){
    if(trafficSource)return Promise.resolve();
    if(trafficLoading)return trafficLoading;
    trafficLoading=(async()=>{
      const response=await fetch(`${import.meta.env.BASE_URL}audio/berlin-traffic.mp3`);
      if(!response.ok)throw new Error('Traffic recording could not be loaded.');
      const buffer=await context.decodeAudioData(await response.arrayBuffer());
      const source=context.createBufferSource();source.buffer=buffer;source.loop=true;source.connect(traffic);source.start();trafficSource=source;
    })().finally(()=>{trafficLoading=null;});
    return trafficLoading;
  }
  function mix(){
    if(!context)return;
    const active=enabled&&playing&&!muted;
    master.gain.setTargetAtTime(active ? .65 : 0,context.currentTime,.22);
    music.gain.setTargetAtTime(voice ? .06 : .18,context.currentTime,.4);
    traffic.gain.setTargetAtTime(street ? (voice ? .10 : .65) : 0,context.currentTime,.6);
  }
  async function start(){
    if(!context){
      context=new AudioContext();master=context.createGain();music=context.createGain();traffic=context.createGain();
      master.gain.value=0;music.connect(master);traffic.connect(master);master.connect(context.destination);
      nextNote=context.currentTime+.08;
      timer=setInterval(()=>{
        if(context.state!=='running'||!playing||!enabled||muted){nextNote=context.currentTime+.08;return;}
        while(nextNote<context.currentTime+.25){
          const chord=chords[Math.floor(beat/8)%4];
          note(chord[[0,2,1,3,2,1,3,1][beat%8]]+12,nextNote,1.2);
          if(beat%8===0)note(chord[0]-12,nextNote,2.8);
          nextNote+=.58;beat++;
        }
      },150);
    }
    playing=true;await context.resume();mix();await loadTraffic();
  }
  return {start,stop(){playing=false;mix();},update(options){street=options.street;voice=options.voice;muted=options.muted;mix();},toggle(){enabled=(!playing||context?.state==='suspended')?true:!enabled;if(enabled)start().catch(()=>{});mix();return enabled;},destroy(){clearInterval(timer);context?.close();}};
}
