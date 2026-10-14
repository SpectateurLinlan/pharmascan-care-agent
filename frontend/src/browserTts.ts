/** Device capability only: never falls back to a cloud endpoint. */
export function selectVoice(voices: readonly SpeechSynthesisVoice[], language: 'en'|'zh'): SpeechSynthesisVoice | undefined {
  const locale = (voice: SpeechSynthesisVoice) => voice.lang.replaceAll('_','-').toLowerCase();
  const eligible = voices.filter(voice => language === 'en' ? /^en(?:-|$)/.test(locale(voice)) : /^zh-(sg|cn)(?:-|$)/.test(locale(voice)));
  const rank = (voice: SpeechSynthesisVoice) => (voice.localService ? 0 : 10) + (language === 'en' ? locale(voice)==='en-sg' ? 0 : 1 : locale(voice)==='zh-sg' ? 0 : 1);
  return eligible.sort((a,b)=>rank(a)-rank(b))[0];
}

export class BrowserTts {
  private generation = 0;
  private dispose: (()=>void)|null = null;
  constructor(private readonly synthesis: SpeechSynthesis|undefined, private readonly makeUtterance: ((text:string)=>SpeechSynthesisUtterance)|undefined) {}
  stop() { this.generation++; this.dispose?.(); this.dispose=null; this.synthesis?.cancel(); }
  play(text:string, language:'en'|'zh', rate:number, ended:()=>void, failed:()=>void) {
    this.stop();
    const synthesis=this.synthesis, make=this.makeUtterance, version=this.generation;
    if (!synthesis || !make || !text.trim()) { failed(); return; }
    let utterance:SpeechSynthesisUtterance|null=null;
    let timer:ReturnType<typeof setTimeout>;
    const cleanup=()=>{ clearTimeout(timer); synthesis.removeEventListener('voiceschanged',load); if(utterance){utterance.onend=null;utterance.onerror=null;} };
    const finish=(error:boolean)=>{if(version!==this.generation)return;cleanup();this.dispose=null;this.generation++;synthesis.cancel();if(error)failed();else ended();};
    const load=()=>{
      if(utterance || version!==this.generation)return;
      const voice=selectVoice(synthesis.getVoices(),language);
      if(!voice)return; // A delayed voiceschanged can still provide the required language.
      clearTimeout(timer); synthesis.removeEventListener('voiceschanged',load);
      utterance=make(text);utterance.voice=voice;utterance.lang=voice.lang;utterance.rate=Math.min(1.2,Math.max(.7,rate));
      utterance.onend=()=>finish(false);utterance.onerror=()=>finish(true);
      timer=setTimeout(()=>finish(true),120000);
      try{synthesis.speak(utterance);}catch{finish(true);}
    };
    this.dispose=cleanup;
    timer=setTimeout(()=>finish(true),3000);
    synthesis.addEventListener('voiceschanged',load);
    try{load();}catch{finish(true);}
  }
}
