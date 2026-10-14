import { useLanguage } from '../language';
import { useEffect, useRef, useState } from 'react';
import { browserSpeechProvider, recognitionError, type NativeRecognition, type SpeechRecognitionPort, type SpeechState } from '../browserSpeech';

export function VoiceInput({ onTranscript, provider, disabled = false }: {
  onTranscript: (text: string) => void; provider?: SpeechRecognitionPort | null; disabled?: boolean;
}) {
  const {preferences,t}=useLanguage();
  const speech = useRef(provider === undefined ? browserSpeechProvider() : provider);
  const [consent, setConsent] = useState(false);
  const [state, setState] = useState<SpeechState>('idle');
  const [notice, setNotice] = useState('');
  const [showConsent, setShowConsent] = useState(false);
  const current = useRef<NativeRecognition | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; if (timer.current) clearTimeout(timer.current); current.current?.abort(); };
  }, []);
  function cancel() {
    if (timer.current) clearTimeout(timer.current);
    current.current?.abort(); current.current = null; setState('idle'); setNotice('Listening cancelled. You can still type.');
  }
  function start() {
    if (!speech.current || disabled) return;
    if (!consent) { setShowConsent(true); return; }
    setNotice(''); setState('requesting');
    const active = speech.current.create(); current.current = active;
    let transcript = ''; let failed = false;
    active.lang = preferences.speech_locale; active.continuous = false; active.interimResults = true; active.maxAlternatives = 1;
    const live = () => mounted.current && current.current === active;
    active.onstart = () => { if (live()) setState('listening'); };
    active.onaudioend = () => { if (live()) setState('processing'); };
    active.onresult = event => {
      if (!live() || failed) return;
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result?.isFinal) transcript += result[0].transcript;
      }
      if (transcript.trim()) { onTranscript(transcript.trim()); setState('review'); setNotice('Review or edit, then Send.'); }
    };
    active.onerror = event => { if (live()) { failed = true; if (timer.current) clearTimeout(timer.current); current.current = null; active.abort(); setNotice(recognitionError(event.error)); setState('idle'); } };
    active.onend = () => {
      if (!live()) return;
      if (timer.current) clearTimeout(timer.current);
      current.current = null;
      if (!transcript.trim() && !failed) setNotice('No usable words were recognised. Try again or type.');
      setState(transcript.trim() ? 'review' : 'idle');
    };
    timer.current = setTimeout(() => {
      if (!live()) return;
      active.abort(); current.current = null; setState('idle'); setNotice('Listening timed out. Try again or type.');
    }, 30000);
    try { active.start(); } catch { failed = true; cancel(); setNotice('Microphone could not start. Please type instead.'); }
  }
  const listening = state === 'requesting' || state === 'listening' || state === 'processing';
  return <div className="voice-inline">
    <button className={`mic-button ${listening ? 'is-listening' : ''}`} aria-label={t(listening ? 'Stop listening' : 'Speak your message')}
      disabled={disabled || !speech.current} onClick={() => listening ? current.current?.stop() : start()}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>
    </button>
    {showConsent && !consent ? <label className="speech-consent"><input type="checkbox" onChange={event => { setConsent(event.target.checked); setShowConsent(false); }} />
      {t("Allow speech recognition. Your browser may send audio to its speech service.")}</label> : null}
    {listening ? <div className="speech-status" role="status">{t(state === 'requesting' ? 'Allow microphone...' : state === 'processing' ? 'Processing...' : 'Listening...')}
      <button onClick={cancel}>{t("Cancel")}</button></div> : null}
    {!speech.current ? <p className="speech-status" role="status">{t("Voice is unsupported in this browser. You can type.")}</p> : null}
    {notice && state !== 'review' ? <p className="speech-status" role="status">{t(notice)}</p> : null}
  </div>;
}
