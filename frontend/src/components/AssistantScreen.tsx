import {ConversationSurface} from './ConversationSurface';
import {ConversationHistory} from './ConversationHistory';
import { useLanguage } from '../language';
import { useEffect, useRef, useState } from 'react';
import { api, type AgentUsage, type AgentMessageResponse } from '../api/client';
import { ErrorNotice } from './primitives';
import { VoiceInput } from './VoiceInput';
import {BrowserTts} from '../browserTts';
import {ConfirmReportSheet} from './ConfirmReportSheet';
import {CareReviewSheet} from './CareReviewSheet';
import type {CareReview} from '../api/care';

export function AssistantScreen({ sessionId, onSession, compact = false, active = true, onPhoto, onChanged,onVisualCheck,onHealthReview,onExpand,onClose,contextSlots={} }: {
  onClose?:()=>void;contextSlots?:Record<string,unknown>;
  sessionId: string | null; onSession: (id: string) => void; compact?: boolean; onExpand?:()=>void; active?:boolean; onPhoto?: () => void; onChanged?: () => void;onVisualCheck?:(id:string|null)=>void;onHealthReview?:(description:string)=>void;
}) {
  const {language,t,preferences,ttsProvider,speechRate}=useLanguage();
  const [usage,setUsage]=useState<AgentUsage|null>(null);
  /** How many AI conversations are left today. Derived once so the dock and the
   *  open conversation can never disagree. */
  const remaining=Math.max(0,(usage?.limit??0)-(usage?.llm_user_turns??0));
  const [careProposal,setCareProposal]=useState<CareReview|null>(null);
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
  const [historyRevision,setHistoryRevision]=useState(0);
  const [reportStates,setReportStates]=useState<Record<number,string>>({});
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
  useEffect(()=>{
    setConfirmationIndex(null);
    if(!active)return;
    const expire=()=>setTurns(previous=>previous.map(turn=>turn.pending_report&&Date.parse(turn.pending_report.expires_at)<=Date.now()?{...turn,pending_report:null}:turn));
    expire();const timer=window.setInterval(expire,30000);window.addEventListener('focus',expire);
    return()=>{clearInterval(timer);window.removeEventListener('focus',expire);};
  },[active]);
  useEffect(()=>{
    // Expiry removes the challenge from its turn; it must also release the
    // presentation lock, without confirming or recreating that challenge.
    if(confirmationIndex!==null&&!turns[confirmationIndex]?.pending_report){
      setReportStates(previous=>({...previous,[confirmationIndex]:'Confirmation expired'}));
      setConfirmationIndex(null);
    }
  },[turns,confirmationIndex]);
  useEffect(()=>{if(!sessionId||loadedSession.current===sessionId||!api.recentTurns)return;let live=true;void api.recentTurns(sessionId).then(rows=>{if(live&&loadedSession.current!==sessionId){loadedSession.current=sessionId;setRecent(rows);}}).catch(()=>{if(live)setError(new Error('Could not restore recent conversation. Your medication records have not changed.'));});return()=>{live=false;};},[sessionId]);

  useEffect(()=>{let live=true; if(api.agentUsage) void api.agentUsage().then(value=>{if(live)setUsage(value);}).catch(()=>{if(live)setUsage(null);});return()=>{live=false;};},[]);

  async function send() {
    if (!text.trim()) return;
    onExpand?.();
    setReportNotice('');
    stopPlayback();setSpeaking(false);
    const sentLanguage=language;
    setBusy(true); setError(null);
    try {
      const reply = await api.sendMessage({ text: text.trim(), language, session_id: sessionId,
        client_turn_id: `turn-${crypto.randomUUID()}`, slots: contextSlots });
      if (!mounted.current) return;
      // Display statuses move with their bounded turn; index0 may be evicted.
      if(turns.length===6)setReportStates(previous=>Object.fromEntries(Object.entries(previous).filter(([key])=>Number(key)>0).map(([key,value])=>[Number(key)-1,value])));
      setHistoryRevision(value=>value+1);if(reply.history_saved===false)setError(new Error('Could not save this conversation. Your answer is still available.'));loadedSession.current=reply.session_id;setSentTexts(previous=>[...previous,text.trim()].slice(-6));
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
    if(!Number.isFinite(Date.parse(pending.expires_at))||Date.parse(pending.expires_at)<=Date.now()){
      setTurns(previous=>previous.map((turn,at)=>at===index?{...turn,pending_report:null}:turn));setConfirmationIndex(null);
      setError(new Error('This confirmation expired. Please request a new summary.'));return;
    }
    setBusy(true); setError(null);
    try {
      const payload = { regimen_id: pending.regimen_id,
        intake_status: pending.summary.intake_status, idempotency_key: pending.idempotency_key,
        challenge_id: pending.challenge_id };
      if (pending.occurrence_id) await api.submitReport(pending.occurrence_id, payload);
      else await api.submitPrnReport(payload);
      setTurns(previous => previous.map((turn, at) => at === index ? { ...turn, pending_report: null } : turn));
      setConfirmationIndex(null);
      setReportStates(previous=>({...previous,[index]:'Report saved'}));setReportNotice('Your report was saved.'); onChanged?.();
    } catch (caught) { setError(caught); } finally { setBusy(false); }
  }

  return <ConversationSurface open={!compact&&Boolean(onClose)} onClose={onClose} locked={confirmationIndex!==null||careProposal!==null||busy}><section className={compact ? 'companion-composer' : 'assistant-view'} aria-label="Medication companion">
    {!compact ? <h1>{t('Your companion')}</h1> : null}
    {!compact&&recent.length?<details className="recent-chat" open={!compact}><summary>{t('Recent conversation')} · {recent.length} / 6</summary>{recent.map((row,index)=><article key={index}><p className="user-message">{row.user}</p><p>{patientMessage(row.assistant)}</p></article>)}</details>:null}
    {/* Conversation reads top to bottom with the composer at the bottom, as
        every chat surface does. The input used to sit above the transcript, so
        the newest reply appeared *below* the field you type into. */}
    {!compact&&turns.length ? <ul className="transcript" aria-live="polite" aria-hidden={confirmationIndex!==null}>
      {turns.map((turn, index) => <li className="turn" key={index}>
        <p className="user-message">{sentTexts[index]}</p>
        <p>{patientMessage(turn.message)}</p>
        {turn.health_note_request?<button onClick={()=>onHealthReview?.(turn.health_note_request?.description??'')}>{t('Review health note')}</button>:null}
        {turn.care_request?<button onClick={()=>setCareProposal(turn.care_request??null)}>{t('Review medication-care record')}</button>:null}
        {turn.visual_check_request ? <button onClick={()=>onVisualCheck?.(turn.visual_check_request?.regimen_id??null)}>{t("Compare a pill photo")}</button> : null}
        {turn.intent === 'reminder' && !turn.tool_traces.some(trace => trace.tool_name === 'create_reminder') ? <div className="actions">{[15,30].map(minutes => <button key={minutes} onClick={() => setText(`Remind me again in ${minutes} minutes.`)}>In {minutes} min</button>)}</div> : null}
        {reportStates[index]?<p role="status">{t(reportStates[index])}</p>:null}
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
    <div className="composer-row">
      <button className="photo-button" aria-label="Read a medication label photo" onClick={onPhoto} disabled={!onPhoto}><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1"/><path d="m4 18 5-5 4 3 4-5 4 6"/></svg></button>
      <input aria-label={t("Review your message before sending")} value={text} disabled={busy} onFocus={()=>{if(compact)onExpand?.();}}
        onChange={event => setText(event.target.value)} placeholder={t("Ask about your medication...")}
        onKeyDown={event => { if (event.key === 'Enter') void send(); }} />
      {usage&&compact?<span className="composer-allowance" role="status" title={`${t('AI conversations left today')}: ${remaining} / ${usage.limit} · ${t('Resets at midnight Singapore time')}`}>
        <span aria-hidden="true">{remaining} / {usage.limit}</span>
        <span className="sr-only">{t('AI conversations left today')}: {remaining} / {usage.limit} · {t('Resets at midnight Singapore time')}</span>
      </span>:null}
      {preferences.voice_enabled ? <VoiceInput key={language} onTranscript={setText} disabled={busy} /> : null}
      <button className="primary composer-send" onClick={() => void send()} disabled={busy || !text.trim()} aria-busy={busy}>{t('Send')}</button>
    </div>
    {/* Shown beside the open conversation, where someone is actually speaking,
        instead of in a second blocking dialog at the microphone. */}
    {!compact&&preferences.voice_enabled ? <p className="voice-privacy">{t('Voice uses your browser’s speech service. Audio is not saved.')}</p> : null}
    {/* The daily allowance is the one line a patient needs *before* deciding to
        send a message, so it is shown in the open conversation too — it used to be
        rendered above the page title on all four screens, which was noise, but
        hiding it from the dock removed information the patient needed. */}
    {usage&&!compact ? <p className="ai-allowance" role="status">{t('AI conversations left today')}: {remaining} / {usage.limit} · {t('Resets at midnight Singapore time')}{usage.llm_user_turns>=usage.limit?`. ${t('Your medication records, reports and reminders still work.')}`:''}</p> : null}
    {/* The busy line and the saved-report notice belong to the open
        conversation, where the patient is actually talking to the assistant;
        repeated on four screens they are noise above the page title. */}
    {!compact&&busy ? <p role="status">{t('Checking your records...')}</p> : null}
    {error ? <ErrorNotice error={error} /> : null}
    {!compact&&reportNotice ? <p role="status">{t(reportNotice)}</p> : null}
        {confirmationIndex!==null&&turns[confirmationIndex]?.pending_report ? (()=>{const index=confirmationIndex,turn=turns[index]!;const cancel=()=>{setTurns(previous=>previous.map((row,at)=>at===index?{...row,pending_report:null}:row));setReportStates(previous=>({...previous,[index]:'Report cancelled'}));setConfirmationIndex(null);};return <ConfirmReportSheet title="Just to confirm" summary={turn.pending_report!.summary} busy={busy} onConfirm={()=>void confirmReport(index)} onCancel={cancel}>
        <button onClick={()=>void readAloud(turn.message,index)} disabled={!preferences.voice_enabled}>{t('Play response')}</button>{speaking?<button onClick={()=>{stopPlayback();setSpeaking(false);}}>{t('Stop audio')}</button>:null}</ConfirmReportSheet>;})() : null}
    {careProposal?<CareReviewSheet proposal={careProposal} onCancel={()=>setCareProposal(null)} onSaved={()=>{setCareProposal(null);setReportNotice('Your medication-care record was saved.');onChanged?.();window.dispatchEvent(new Event('pharmascan:reminder-refresh'));}}/>:null}
    {!compact?<ConversationHistory revision={historyRevision} blocked={busy||turns.some(row=>Boolean(row.pending_report))||careProposal!==null} onCleared={()=>{loadedSession.current=sessionId;setRecent([]);setTurns([]);setSentTexts([]);setReportStates({});}}/>:null}
  </section></ConversationSurface>;
}

export function patientMessage(message: string): string {
  return message.replace(/^\[degraded: deterministic rule routing, not a live LLM\]\s*/, '');
}
