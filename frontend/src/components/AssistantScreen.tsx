import { useLanguage } from '../language';
import { useEffect, useRef, useState } from 'react';
import { api, type AgentUsage, type AgentMessageResponse } from '../api/client';
import { ErrorNotice } from './primitives';
import { VoiceInput } from './VoiceInput';
import {BrowserTts} from '../browserTts';
import {BottomSheet} from './BottomSheet';

export function AssistantScreen({ sessionId, onSession, compact = false, active = true, onPhoto, onChanged,onVisualCheck,onHealthReview }: {
  sessionId: string | null; onSession: (id: string) => void; compact?: boolean; active?:boolean; onPhoto?: () => void; onChanged?: () => void;onVisualCheck?:(id:string|null)=>void;onHealthReview?:(description:string)=>void;
}) {
  const {language,t,preferences,ttsProvider,speechRate}=useLanguage();
  const [usage,setUsage]=useState<AgentUsage|null>(null);
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<AgentMessageResponse[]>([]);
  const [recent,setRecent]=useState<Array<{user:string;assistant:string}>>([]);
  const [sentTexts,setSentTexts]=useState<string[]>([]);
  const loadedSession=useRef<string|null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [speakingIndex, setSpeakingIndex] = useState<number | null>(null);
  const [reportNotice, setReportNotice] = useState('');
  const [confirmationIndex,setConfirmationIndex]=useState<number|null>(null);
  const browserTts=useRef<BrowserTts|null>(null);
  if(!browserTts.current)browserTts.current=new BrowserTts(window.speechSynthesis,typeof SpeechSynthesisUtterance==='undefined'?undefined:text=>new SpeechSynthesisUtterance(text));
  const playbackOptions=useRef({language,ttsProvider,speechRate,active,enabled:preferences.voice_enabled,autoplay:preferences.tts_autoplay});
  playbackOptions.current={language,ttsProvider,speechRate,active,enabled:preferences.voice_enabled,autoplay:preferences.tts_autoplay};
  const playbackVersion = useRef(0);
  const audio = useRef<HTMLAudioElement | null>(null);
  const objectUrl = useRef<string | null>(null);
  const mounted = useRef(false);

  function stopPlayback() {
    playbackVersion.current += 1;
    browserTts.current?.stop();
    audio.current?.pause(); audio.current = null;
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null;
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; stopPlayback(); }; }, []);
  useEffect(()=>{stopPlayback();setSpeaking(false);},[active,language,ttsProvider,speechRate,preferences.voice_enabled,preferences.tts_autoplay]);
  useEffect(()=>{if(!sessionId||loadedSession.current===sessionId||!api.recentTurns)return;let live=true;void api.recentTurns(sessionId).then(rows=>{if(live&&loadedSession.current!==sessionId){loadedSession.current=sessionId;setRecent(rows);}}).catch(()=>{if(live)setError(new Error('Could not restore recent conversation. Your medication records have not changed.'));});return()=>{live=false;};},[sessionId]);

  useEffect(()=>{let live=true; if(api.agentUsage) void api.agentUsage().then(value=>{if(live)setUsage(value);}).catch(()=>{if(live)setUsage(null);});return()=>{live=false;};},[]);

  async function send() {
    if (!text.trim()) return;
    stopPlayback();setSpeaking(false);
    const sentLanguage=language;
    setBusy(true); setError(null);
    try {
      const reply = await api.sendMessage({ text: text.trim(), language, session_id: sessionId,
        client_turn_id: `turn-${crypto.randomUUID()}`, slots: {} });
      if (!mounted.current) return;
      loadedSession.current=reply.session_id;setSentTexts(previous=>[...previous,text.trim()].slice(-6));
      setRecent(previous=>{const remaining=Math.max(0,5-turns.length);return remaining?previous.slice(-remaining):[];});
      if(reply.pending_report)setConfirmationIndex(Math.min(turns.length,5));
      setUsage(reply.usage??null); window.localStorage.setItem("pharmascan.agent-session",reply.session_id); onSession(reply.session_id); setTurns(previous => [...previous, reply].slice(-6)); setText('');
      if (playbackOptions.current.active && playbackOptions.current.enabled && playbackOptions.current.autoplay && playbackOptions.current.language===sentLanguage) void readAloud(reply.message,Math.min(turns.length,5));
    } catch (caught) { if (mounted.current) setError(caught); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function readAloud(message: string, index: number) {
    const {language,ttsProvider,speechRate,active,enabled}=playbackOptions.current;
    if(!active||!enabled)return;
    stopPlayback(); const version = playbackVersion.current; setSpeaking(true); setError(null);
    setSpeakingIndex(index);
    try {
      const concise = patientMessage(message).slice(0, ttsProvider==='browser'?2000:140);
      if(ttsProvider==='browser'){
        browserTts.current?.play(concise,language,speechRate,()=>{if(mounted.current&&version===playbackVersion.current)setSpeaking(false);},()=>{if(mounted.current&&version===playbackVersion.current){setSpeaking(false);setError(new Error('Spoken playback is unavailable. Please read the visible response.'));}});
        return;
      }
      const blob = await api.synthesize(concise,language);
      if (!mounted.current || version !== playbackVersion.current) return;
      objectUrl.current = URL.createObjectURL(blob);
      const player = new Audio(objectUrl.current);player.playbackRate=speechRate; audio.current = player;
      player.onended = () => { if(version!==playbackVersion.current)return;stopPlayback(); if (mounted.current) setSpeaking(false); };
      player.onerror = () => { if(version!==playbackVersion.current)return;stopPlayback(); if (mounted.current) { setSpeaking(false); setError(new Error('Audio playback failed. The response is still visible.')); } };
      await player.play();
    } catch { if (version !== playbackVersion.current) return; stopPlayback(); if (mounted.current) { setSpeaking(false); setError(new Error('Spoken playback is unavailable. Please read the visible response.')); } }
  }

  async function confirmReport(index: number) {
    const pending = turns[index]?.pending_report;
    if (!pending) return;
    setBusy(true); setError(null);
    try {
      const payload = { regimen_id: pending.regimen_id,
        intake_status: pending.summary.intake_status, idempotency_key: pending.idempotency_key,
        challenge_id: pending.challenge_id };
      if (pending.occurrence_id) await api.submitReport(pending.occurrence_id, payload);
      else await api.submitPrnReport(payload);
      setTurns(previous => previous.map((turn, at) => at === index ? { ...turn, pending_report: null } : turn));
      setConfirmationIndex(null);
      setReportNotice('Your report was saved. This does not prove ingestion.'); onChanged?.();
    } catch (caught) { setError(caught); } finally { setBusy(false); }
  }

  return <section className={compact ? 'companion-composer' : 'assistant-view'} aria-label="Medication companion">
    {!compact ? <h1>{t('Your companion')}</h1> : null}
    {recent.length?<details className="recent-chat" open={!compact}><summary>{t('Recent conversation')} · {recent.length} / 6</summary>{recent.map((row,index)=><article key={index}><p className="user-message">{row.user}</p><p>{patientMessage(row.assistant)}</p></article>)}<p className="notice">{t('Only six recent turns are kept. Earlier confirmation buttons are not replayed.')}</p></details>:null}
    <div className="composer-row">
      <button className="photo-button" aria-label="Read a medication label photo" onClick={onPhoto} disabled={!onPhoto}><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1"/><path d="m4 18 5-5 4 3 4-5 4 6"/></svg></button>
      <input aria-label={t("Review your message before sending")} value={text} disabled={busy}
        onChange={event => setText(event.target.value)} placeholder={t("Ask about your medication...")}
        onKeyDown={event => { if (event.key === 'Enter') void send(); }} />
      {preferences.voice_enabled ? <VoiceInput key={language} onTranscript={setText} disabled={busy} /> : null}
      <button className="primary composer-send" onClick={() => void send()} disabled={busy || !text.trim()} aria-busy={busy}>{t('Send')}</button>
    </div>
    {usage ? <p className="ai-allowance" role="status">{t('AI demo')}: {usage.llm_user_turns} / {usage.limit} · {t('Resets at midnight Singapore time')} ({new Date(usage.next_reset_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:'Asia/Singapore'})})</p> : null}
    {busy ? <p role="status">{t('Checking your records...')}</p> : null}
    {error ? <ErrorNotice error={error} /> : null}
    {reportNotice ? <p role="status">{t(reportNotice)}</p> : null}
    {turns.length ? <ul className="transcript" aria-live="polite" aria-hidden={confirmationIndex!==null}>
      {turns.map((turn, index) => <li className="turn" key={index}>
        <p className="user-message">{sentTexts[index]}</p>
        <p>{patientMessage(turn.message)}</p>
        {turn.health_note_request?<button onClick={()=>onHealthReview?.(turn.health_note_request?.description??'')}>{t('Review health note')}</button>:null}
        {turn.visual_check_request ? <button onClick={()=>onVisualCheck?.(turn.visual_check_request?.regimen_id??null)}>{t("Compare a pill photo")}</button> : null}
        {turn.intent === 'reminder' && !turn.tool_traces.some(trace => trace.tool_name === 'create_reminder') ? <div className="actions">{[15,30].map(minutes => <button key={minutes} onClick={() => setText(`Remind me again in ${minutes} minutes.`)}>In {minutes} min</button>)}</div> : null}
        {turn.pending_report?<button onClick={()=>setConfirmationIndex(index)}>{t('Review dose report')}</button>:null}
        <div className="actions">
          <button onClick={() => void readAloud(turn.message, index)} disabled={!preferences.voice_enabled}>{t('Play response')}</button>
          {speaking && speakingIndex === index ? <button onClick={() => { stopPlayback(); setSpeaking(false); }}>{t('Stop audio')}</button> : null}
        </div>
        <details><summary>{t('How this answer was made')}</summary><p>{t(turn.mode==="gemini" ? "AI-assisted answer using verified application tools." : "Limited demo rules were used for this answer.")}</p>
          <ul>{turn.tool_traces.map((trace, traceIndex) => <li key={traceIndex}>{trace.tool_name}: {trace.status}</li>)}</ul>
        </details>
      </li>)}
    </ul> : null}
        {confirmationIndex!==null&&turns[confirmationIndex]?.pending_report ? (()=>{const index=confirmationIndex,turn=turns[index]!;return <BottomSheet title={t('Just to confirm')} busy={busy} onCancel={()=>setConfirmationIndex(null)}>
          <p>{turn.pending_report!.summary.medication_display_name}: {' '}
            {turn.pending_report!.summary.dose_amount} {turn.pending_report!.summary.dose_unit}</p>
          <p>{turn.pending_report!.summary.local_due_time} ({turn.pending_report!.summary.local_timezone})</p>
          <p>{language === 'zh' ? t(turn.pending_report!.summary.intake_status === 'reported_taken' ? 'Patient reported taken' : turn.pending_report!.summary.intake_status === 'reported_not_taken' ? 'Patient reported not taken' : 'Patient is unsure') : turn.pending_report!.summary.intake_status_label}</p><p>{language === 'zh' ? t('A self-report does not prove ingestion.') : turn.pending_report!.summary.safety_notice}</p>
          <div className="actions"><button className="primary" onClick={() => void confirmReport(index)} disabled={busy}>{t('Confirm record')}</button>
            <button onClick={() => setConfirmationIndex(null)} disabled={busy}>{t('Cancel')}</button></div>
        <button onClick={()=>void readAloud(turn.message,index)} disabled={!preferences.voice_enabled}>{t('Play response')}</button>{speaking?<button onClick={()=>{stopPlayback();setSpeaking(false);}}>{t('Stop audio')}</button>:null}</BottomSheet>;})() : null}
    <details className="speech-disclosure"><summary>{t('About voice & demo')}</summary><p>{t('Browser voices depend on your device and may use an online service. Cloud voice requires explicit selection and server permission. Selection resets to browser on reload.')}</p><p>{t('Recognition may use an online service. Review your transcript before sending. No medical advice.')}</p></details>
  </section>;
}

export function patientMessage(message: string): string {
  return message.replace(/^\[degraded: deterministic rule routing, not a live LLM\]\s*/, '');
}
