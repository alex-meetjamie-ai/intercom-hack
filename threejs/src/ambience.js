// Original music loop with a locally bundled Berlin traffic field recording.
export function createAmbience(){
  let context,music,traffic,office,master,timer,nextNote=0,beat=0,enabled=true,playing=false;
  let street=false,indoors=false,voice=false,muted=false;
  const loops=new Map(),effects=new Map(),fired=new Set();
  const chords=[[48,55,59,64],[45,52,55,60],[41,48,52,57],[43,50,55,59]];
  const hz=midi=>440*2**((midi-69)/12);
  function note(midi,at,length=.8){
    const oscillator=context.createOscillator(),envelope=context.createGain();
    oscillator.type='sine';oscillator.frequency.value=hz(midi);
    envelope.gain.setValueAtTime(0,at);envelope.gain.linearRampToValueAtTime(.13,at+.018);
    envelope.gain.exponentialRampToValueAtTime(.001,at+length);
    oscillator.connect(envelope);envelope.connect(music);oscillator.start(at);oscillator.stop(at+length+.02);
  }
  function loadLoop(file,destination){
    if(loops.has(file))return loops.get(file);
    const loading=(async()=>{
      const response=await fetch(`${import.meta.env.BASE_URL}audio/${file}`);
      if(!response.ok)throw new Error(`Ambience recording could not be loaded: ${file}`);
      const buffer=await context.decodeAudioData(await response.arrayBuffer());
      const source=context.createBufferSource();source.buffer=buffer;source.loop=true;source.connect(destination);source.start();
    })().catch(error=>{loops.delete(file);throw error;});
    loops.set(file,loading);return loading;
  }
  async function loadEffect(file){
    if(effects.has(file))return;
    const response=await fetch(`${import.meta.env.BASE_URL}audio/${file}`);
    if(!response.ok)throw new Error(`Sound effect could not be loaded: ${file}`);
    effects.set(file,await context.decodeAudioData(await response.arrayBuffer()));
  }
  function effect(file,key){
    if(!context||!enabled||!playing||context.state!=='running'||!effects.has(file)||fired.has(key))return;
    fired.add(key);
    const source=context.createBufferSource();source.buffer=effects.get(file);source.connect(master);source.start();
    source.onended=()=>source.disconnect();
  }
  function mix(){
    if(!context)return;
    const active=enabled&&playing&&!muted;
    master.gain.setTargetAtTime(active ? .65 : 0,context.currentTime,.22);
    music.gain.setTargetAtTime(voice ? .06 : .18,context.currentTime,.4);
    traffic.gain.setTargetAtTime(street ? (voice ? .10 : .65) : 0,context.currentTime,.6);
    office.gain.setTargetAtTime(indoors ? (voice ? .10 : .48) : 0,context.currentTime,.8);
  }
  async function start(){
    if(!context){
      context=new AudioContext();master=context.createGain();music=context.createGain();traffic=context.createGain();office=context.createGain();
      master.gain.value=0;music.connect(master);traffic.connect(master);office.connect(master);master.connect(context.destination);
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
    playing=true;await context.resume();mix();await Promise.all([loadLoop('berlin-traffic.mp3',traffic),loadLoop('office-ambience.mp3',office),loadEffect('intercom-crash.mp3'),loadEffect('raptor-roar.mp3')]);
  }
  return {start,stop(){playing=false;fired.clear();mix();},update(options){street=options.street;indoors=options.office;voice=options.voice;muted=options.muted;if(!options.finale)fired.clear();if(options.finale>=1.55)effect('intercom-crash.mp3','crash');if(options.finale>=4.75)effect('raptor-roar.mp3','roar');mix();},toggle(){enabled=(!playing||context?.state==='suspended')?true:!enabled;if(enabled)start().catch(()=>{});mix();return enabled;},destroy(){clearInterval(timer);context?.close();}};
}
