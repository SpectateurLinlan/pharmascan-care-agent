import {Icon} from './Icon';
import {ConversationSurface} from './ConversationSurface';
import {ConversationHistoryBrowser} from './ConversationHistoryBrowser';
import {MedicationChoices} from './MedicationChoices';
import {AnswerSources} from './AnswerSources';
import { useLanguage } from '../language';
import { useEffect, useRef, useState } from 'react';
import { api, type AgentUsage, type AgentMessageResponse, type ConversationEntry, type ChatPhotoContext, type NavigationContext, type MedicationSelection } from '../api/client';
import {photoEvidence} from '../photoEvidence';
import {answerExplanation,toolTraceLabel} from '../assistantResponsePresentation';
import { ErrorNotice } from './primitives';
import { VoiceInput } from './VoiceInput';
import {BrowserTts} from '../browserTts';
import {ConfirmReportSheet} from './ConfirmReportSheet';
import {CareReviewSheet} from './CareReviewSheet';
import type {CareReview} from '../api/care';
import {useImageConsent} from '../imageConsent';

export function AssistantScreen({ sessionId, onSession, ownerId, compact = false, workspace = false, todayEntry = false, clearRevision = 0, active = true, onChanged,onVisualCheck,onHealthReview,onExpand,onViewTodayMedication,onClose,onSourceReturn,contextSlots={} }: {
  onSourceReturn?:(source:NavigationContext)=>void;onClose?:()=>void;contextSlots?:Record<string,unknown>;
  sessionId: string | null; onSession: (id: string) => void; ownerId?:string; compact?: boolean; workspace?:boolean; todayEntry?:boolean; clearRevision?:number; onExpand?:()=>void; onViewTodayMedication?:()=>void; active?:boolean; onChanged?: () => void;onVisualCheck?:(id:string|null)=>void;onHealthReview?:(description:string)=>void;
}) {
  const {language,t,preferences,ttsProvider,speechRate}=useLanguage();
  const [photoConsent,setPhotoConsent]=useImageConsent(ownerId??'');
  const [usage,setUsage]=useState<AgentUsage|null>(null);
  /** How many AI conversations are left today. Derived once so the dock and the
   *  open conversation can never disagree. */
  const remaining=Math.max(0,(usage?.limit??0)-(usage?.llm_user_turns??0));
  const [careProposal,setCareProposal]=useState<CareReview|null>(null);
  const [text, setText] = useState('');
  const [conversationId,setConversationId]=useState<string|null>(null);
  const [olderCursor,setOlderCursor]=useState<string|null>(null);
  const [viewSlots,setViewSlots]=useState(contextSlots);
  const [source,setSource]=useState<NavigationContext|null>(null);
  const viewKey=useRef(`temporary:${crypto.randomUUID()}`),navigationVersion=useRef(0);
  const [wideWorkspace,setWideWorkspace]=useState(()=>window.matchMedia?.('(min-width: 1024px)').matches??false);
  const [historyOpen,setHistoryOpen]=useState(wideWorkspace),[pendingText,setPendingText]=useState('');
  const [conversationExpanded,setConversationExpanded]=useState(false);
  useEffect(()=>{setConversationExpanded(false);},[active,workspace,todayEntry]);
  useEffect(()=>{const query=window.matchMedia?.('(min-width: 1024px)');if(!query)return;const sync=()=>setWideWorkspace(query.matches);query.addEventListener('change',sync);return()=>query.removeEventListener('change',sync);},[]);
  useEffect(()=>{if(workspace)setHistoryOpen(wideWorkspace);},[workspace,wideWorkspace]);
  const [selectedHistory,setSelectedHistory]=useState<ConversationEntry|null>(null);
  const sending=useRef(false);
  const outgoing=useRef(new Map<string,{id:string;text:string;photo:File|null;context?:ChatPhotoContext;selection?:MedicationSelection}>());
  useEffect(()=>{if(compact){setHistoryOpen(false);setSelectedHistory(null);}},[compact]);
  const [photo,setPhoto]=useState<File|null>(null);
  const [photoType,setPhotoType]=useState<'pharmacy_label'|'prescription'|'package'>('pharmacy_label');
  const [photoPreview,setPhotoPreview]=useState<string|null>(null);
  const [sentPhotoNames,setSentPhotoNames]=useState<string[]>([]);
  const photoInput=useRef<HTMLInputElement>(null),messageInput=useRef<HTMLInputElement>(null),workspaceInput=useRef<HTMLTextAreaElement>(null);
  function focusMessage(){(workspace?workspaceInput.current:messageInput.current)?.focus();}
  useEffect(()=>{const input=workspaceInput.current;if(input){input.style.height='auto';input.style.height=`${Math.min(input.scrollHeight,160)}px`;}},[text,workspace,preferences.text_scale_percent]);
  const [turns, setTurns] = useState<AgentMessageResponse[]>([]);
  const [visibleLiveTurns,setVisibleLiveTurns]=useState(6);
  const timeline=useRef<HTMLDivElement>(null);
  const scrollAnchor=useRef<{height:number;top:number}|null>(null);
  function retainScroll(){if(timeline.current)scrollAnchor.current={height:timeline.current.scrollHeight,top:timeline.current.scrollTop};}
  const [recent,setRecent]=useState<Array<{user:string;assistant:string;photo?:boolean}>>([]);
  const [sentTexts,setSentTexts]=useState<string[]>([]);
  const loadedSession=useRef<string|null>(null);
  const recentLoad=useRef(0);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [speakingIndex, setSpeakingIndex] = useState<number | null>(null);
  const [reportNotice, setReportNotice] = useState('');
  const [historyRevision,setHistoryRevision]=useState(0);
  useEffect(()=>{const element=timeline.current;if(!element||selectedHistory||element.getClientRects().length===0)return;const anchor=scrollAnchor.current;scrollAnchor.current=null;element.scrollTop=anchor?element.scrollHeight-anchor.height+anchor.top:element.scrollHeight;},[turns.length,recent.length,pendingText,conversationId,historyOpen,selectedHistory,visibleLiveTurns]);
  const [reportStates,setReportStates]=useState<Record<number,string>>({});
  const [confirmationIndex,setConfirmationIndex]=useState<number|null>(null);
  type Snapshot={session:string|null;conversation:string|null;text:string;photo:File|null;photoType:typeof photoType;turns:AgentMessageResponse[];recent:typeof recent;sentTexts:string[];sentPhotoNames:string[];slots:Record<string,unknown>;source:NavigationContext|null;cursor:string|null;reportStates:Record<number,string>};
  const views=useRef(new Map<string,Snapshot>());
  const selectionKey=ownerId?`pharmascan.conversation:${ownerId}`:null;
  const selectionLoaded=useRef<string|null>(null);
  const previousOwner=useRef(ownerId),currentOwner=useRef(ownerId);currentOwner.current=ownerId;
  useEffect(()=>{if(previousOwner.current&&previousOwner.current!==ownerId){recentLoad.current+=1;navigationVersion.current+=1;setPendingText('');setSelectedHistory(null);setHistoryOpen(false);setError(null);setUsage(null);setReportStates({});setReportNotice('');setOlderCursor(null);views.current.clear();outgoing.current.clear();setConversationId(null);setRecent([]);setTurns([]);setText('');setPhoto(null);setSentTexts([]);setSentPhotoNames([]);setViewSlots({});setSource(null);setCareProposal(null);setConfirmationIndex(null);sending.current=false;setBusy(false);}previousOwner.current=ownerId;},[ownerId]);
  const suppliedContext=JSON.stringify(contextSlots);
  useEffect(()=>{setViewSlots(JSON.parse(suppliedContext) as Record<string,unknown>);},[suppliedContext]);
  useEffect(()=>{const version=++navigationVersion.current;setSource(null);const page=viewSlots.source_page;
    if(!api.navigationContext||!['medicines','medicine-detail','records'].includes(String(page)))return;
    const input:NavigationContext={page:page as NavigationContext['page'],...(typeof viewSlots.medication_id==='string'?{medication_id:viewSlots.medication_id}:{}),...(typeof viewSlots.regimen_id==='string'?{regimen_id:viewSlots.regimen_id}:{})};
    void api.navigationContext(input).then(row=>{if(version===navigationVersion.current)setSource(row);}).catch(caught=>{if(version===navigationVersion.current)setError(caught);});
    return()=>{navigationVersion.current+=1;};
  },[viewSlots]);
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
  useEffect(()=>{if(!photo){setPhotoPreview(null);return;}if(!URL.createObjectURL)return;const url=URL.createObjectURL(photo);setPhotoPreview(url);return()=>URL.revokeObjectURL(url);},[photo]);
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
  const handledClear=useRef(0);
  useEffect(()=>{if(clearRevision===handledClear.current)return;handledClear.current=clearRevision;recentLoad.current+=1;loadedSession.current=sessionId;setRecent([]);setTurns([]);setSentTexts([]);setSentPhotoNames([]);setReportStates({});setConfirmationIndex(null);setHistoryOpen(false);views.current.clear();outgoing.current.clear();setConversationId(null);if(selectionKey)localStorage.removeItem(selectionKey);setViewSlots({});setSource(null);setCareProposal(null);},[clearRevision,sessionId]);
  useEffect(()=>{if(conversationId||!sessionId||loadedSession.current===sessionId||!api.recentTurns)return;let live=true;const version=++recentLoad.current;void Promise.resolve().then(()=>{if(!live)return;return api.recentTurns(sessionId).then(rows=>{if(live&&version===recentLoad.current&&loadedSession.current!==sessionId){loadedSession.current=sessionId;setRecent(rows);}}).catch(()=>{if(live&&version===recentLoad.current)setError(new Error('Could not restore recent conversation. Your medication records have not changed.'));});});return()=>{live=false;};},[sessionId,clearRevision,conversationId]);

  useEffect(()=>{let live=true; void Promise.resolve().then(()=>{if(!live||!api.agentUsage)return;return api.agentUsage().then(value=>{if(live)setUsage(value);}).catch(()=>{if(live)setUsage(null);});});return()=>{live=false;};},[]);

  async function send(selection?:MedicationSelection,selectionLabel?:string) {
    const failed=outgoing.current.get(viewKey.current);
    if(!selection&&!text.trim()&&!photo&&failed?.selection){selection=failed.selection;selectionLabel=failed.text;}
    const attachment=selection?null:photo;
    if (sending.current||busy||(!selection&&!text.trim()&&!attachment)) return;
    setConversationExpanded(true);
    if(text.trim().length>2000){setError(new Error(t('Keep your message within 2000 characters.')));return;}
    if(attachment&&!photoConsent){setError(new Error(t('Allow photo processing before sending this image.')));return;}
    if(attachment&&attachment.size>8_000_000){setError(new Error(t('Choose an image smaller than 8 MB.')));return;}
    sending.current=true;setPendingText(selectionLabel??(text.trim()||t('Photo attached')));
    setReportNotice('');
    stopPlayback();setSpeaking(false);
    const sentLanguage=language;
    const sentOwner=ownerId;
    const sentView=viewKey.current;
    const question=selectionLabel??text.trim();
    const previousRequest=outgoing.current.get(sentView);
    const request:{id:string;text:string;photo:File|null;context?:ChatPhotoContext;selection?:MedicationSelection}=previousRequest&&previousRequest.text===question&&previousRequest.photo===attachment&&previousRequest.selection?.choice_id===selection?.choice_id?previousRequest:{id:`turn-${crypto.randomUUID()}`,text:question,photo:attachment,...(selection?{selection}:{})};
    outgoing.current.set(sentView,request);
    setBusy(true); setError(null);
    try {
      let photoContext:ChatPhotoContext|undefined=request.context;
      if(attachment&&!photoContext){
        const route=await api.checkInput(attachment);
        photoContext=photoEvidence(route,photoType);
        if(route.suggested_workflow==='pill_evidence'||route.image_type==='loose_pills'){
          photoContext=photoEvidence(route,photoType,undefined,await api.visualCheck(attachment,null));
        }else if(route.suggested_workflow==='source_review'){
          const preview=await api.sourcePreview(attachment,photoType);
          photoContext=photoEvidence(route,photoType,preview);
        }
        request.context=photoContext;
      }
      const reply = await api.sendMessage({ conversation_id:conversationId, ...(source?{navigation_context:{page:source.page,medication_id:source.medication_id??null,regimen_id:source.regimen_id??null}}:{}),text: question, ...(photoContext?{photo_context:photoContext}:{}), language, session_id: sessionId,
        client_turn_id: request.id, slots: viewSlots, ...(request.selection?{medication_selection:request.selection}:{}) });
      if (!mounted.current||currentOwner.current!==sentOwner) return;
      outgoing.current.delete(sentView);
      // Timeline pagination keeps stable indices; model context is bounded separately.
      setHistoryRevision(value=>value+1);if(reply.history_saved===false)setError(new Error('Could not save this conversation. Your answer is still available.'));loadedSession.current=reply.session_id;setSentTexts(previous=>[...previous,question]);
      setSentPhotoNames(previous=>[...previous,attachment?.name??'']);
      if(reply.conversation_id){setConversationId(reply.conversation_id);viewKey.current=reply.conversation_id;if(selectionKey&&reply.history_saved)localStorage.setItem(selectionKey,reply.conversation_id);}
      if(reply.pending_report)setConfirmationIndex(turns.length);
      setUsage(reply.usage??null); window.localStorage.setItem("pharmascan.agent-session",reply.session_id); onSession(reply.session_id); setTurns(previous => [...previous.map(row=>({...row,medication_choice:null})), reply]); if(!selection){setText('');setPhoto(null);}
      if (playbackOptions.current.active && playbackOptions.current.enabled && playbackOptions.current.autoplay && playbackOptions.current.language===sentLanguage) void readAloud(reply.message,turns.length);
    } catch (caught) { if (mounted.current&&currentOwner.current===sentOwner) setError(caught); }
    finally { if(currentOwner.current===sentOwner){sending.current=false;if (mounted.current){setBusy(false);setPendingText('');}} }
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

  function showCurrentConversation(){if(!wideWorkspace)setHistoryOpen(false);setSelectedHistory(null);requestAnimationFrame(()=>focusMessage());}
  function rememberView(){views.current.set(viewKey.current,{session:sessionId,conversation:conversationId,text,photo,photoType,turns,recent,sentTexts,sentPhotoNames,slots:viewSlots,source,cursor:olderCursor,reportStates});}
  function returnTemporary(){const entry=[...views.current.entries()].reverse().find(([key,row])=>key!==viewKey.current&&!row.conversation&&(row.text||row.photo||row.turns.length||row.recent.length));if(!entry)return;rememberView();const [key,row]=entry;viewKey.current=key;setConversationId(null);if(selectionKey)localStorage.removeItem(selectionKey);if(row.session){loadedSession.current=row.session;onSession(row.session);}setText(row.text);setPhoto(row.photo);setPhotoType(row.photoType);setTurns(row.turns);setRecent(row.recent);setSentTexts(row.sentTexts);setSentPhotoNames(row.sentPhotoNames);setViewSlots(row.slots);setSource(row.source);setOlderCursor(row.cursor);setReportStates(row.reportStates);}
  async function selectConversation(id:string){
    if(sending.current||busy||turns.some(row=>Boolean(row.pending_report))||careProposal)return;
    rememberView();const requestOwner=currentOwner.current;sending.current=true;setBusy(true);setError(null);stopPlayback();recentLoad.current+=1;
    try{
      const saved=views.current.get(id);
      const [resumed,page]=await Promise.all([saved?.session?Promise.resolve({session_id:saved.session}):api.resumeConversation(id),api.conversation(id)]);if(!mounted.current||currentOwner.current!==requestOwner)return;
      viewKey.current=id;setConversationId(id);setOlderCursor(page.next_before);
      loadedSession.current=resumed.session_id;onSession(resumed.session_id);localStorage.setItem('pharmascan.agent-session',resumed.session_id);if(selectionKey)localStorage.setItem(selectionKey,id);
      setRecent(saved?.recent??page.entries.map(row=>({user:row.user_text,assistant:row.assistant_text,photo:row.photo_attached})));setTurns(saved?.turns??[]);setSentTexts(saved?.sentTexts??[]);setSentPhotoNames(saved?.sentPhotoNames??[]);setReportStates(saved?.reportStates??{});setConfirmationIndex(null);setSelectedHistory(null);if(!wideWorkspace)setHistoryOpen(false);
      setText(saved?.text??'');setPhoto(saved?.photo??null);setPhotoType(saved?.photoType??'pharmacy_label');setViewSlots(saved?.slots??{});setSource(saved?.source??null);
      requestAnimationFrame(()=>focusMessage());
    }catch(caught){if(mounted.current&&currentOwner.current===requestOwner)setError(caught);}finally{if(currentOwner.current===requestOwner){sending.current=false;if(mounted.current)setBusy(false);}}
  }
  useEffect(()=>{if(!selectionKey||selectionLoaded.current===selectionKey||!api.resumeConversation)return;selectionLoaded.current=selectionKey;const saved=localStorage.getItem(selectionKey);if(saved)void selectConversation(saved);},[selectionKey]);
  async function earlierMessages(){if(!conversationId||!olderCursor||busy)return;const requestOwner=currentOwner.current;setBusy(true);try{const page=await api.conversation(conversationId,olderCursor);if(currentOwner.current!==requestOwner)return;retainScroll();setRecent(previous=>[...page.entries.map(row=>({user:row.user_text,assistant:row.assistant_text,photo:row.photo_attached})),...previous]);setOlderCursor(page.next_before);}catch(caught){if(currentOwner.current===requestOwner)setError(caught);}finally{if(currentOwner.current===requestOwner)setBusy(false);}}
  const workspaceLocked=busy||turns.some(row=>Boolean(row.pending_report))||careProposal!==null;
  async function newConversation(){
    if(workspaceLocked||sending.current)return;
    rememberView();sending.current=true;setBusy(true);setError(null);if(!wideWorkspace)setHistoryOpen(false);
    const requestOwner=currentOwner.current;
    try{const session=await api.newConversation();if(!mounted.current||currentOwner.current!==requestOwner)return;
      stopPlayback();setSpeaking(false);recentLoad.current+=1;loadedSession.current=session.session_id;
      window.localStorage.setItem('pharmascan.agent-session',session.session_id);onSession(session.session_id);
      setConversationId(null);viewKey.current=`temporary:${crypto.randomUUID()}`;if(selectionKey)localStorage.removeItem(selectionKey);setText('');setPhoto(null);setViewSlots({});setSource(null);setOlderCursor(null);
      setTurns([]);setRecent([]);setSentTexts([]);setSentPhotoNames([]);setReportStates({});setConfirmationIndex(null);setReportNotice('');
    }catch(caught){if(mounted.current&&currentOwner.current===requestOwner)setError(caught);}finally{if(currentOwner.current===requestOwner){sending.current=false;if(mounted.current)setBusy(false);}}
  }
  const newButton=<button className="icon-button" aria-label={t('New conversation')} title={t('New conversation')} disabled={workspaceLocked} onClick={()=>void newConversation()}><Icon name="plus"/></button>;
  const historyToggle=<button className="icon-button" aria-label={t('Conversation history')} title={t(historyOpen?'Hide conversation sidebar':'Show conversation sidebar')} aria-expanded={historyOpen} aria-controls="assistant-conversation-history" disabled={workspaceLocked} onClick={()=>setHistoryOpen(value=>!value)}><Icon name="panel"/></button>;
  return <ConversationSurface open={false} workspace={workspace} navigationControl={historyToggle} navigation={workspace&&historyOpen?<ConversationHistoryBrowser revision={historyRevision} onNew={()=>void newConversation()} disabled={workspaceLocked} onSelect={entry=>{setSelectedHistory(entry);if(!wideWorkspace)setHistoryOpen(false);}} onConversationSelect={id=>void selectConversation(id)} conversationId={conversationId} selectedId={selectedHistory?.id??null}/>:undefined} onClose={onClose} locked={confirmationIndex!==null||careProposal!==null||busy} actions={!workspace||!historyOpen?newButton:undefined}><section className={compact ? `companion-composer${todayEntry?' today-assistant card':''}` : 'assistant-view'} aria-label="Medication companion">
    {compact&&todayEntry?<>
      <div className="today-assistant__heading"><Icon name="message"/><h2>MediThread Assistant</h2><button type="button" className="today-assistant__expand" onClick={onExpand}>{t('Open full chat')}<Icon name="chevron-right"/></button></div>
      <p className="card__hint">{t('View your medicines, review your records or prepare for a visit.')}</p>
      <div className="today-assistant__suggestions"><div className="assistant-tasks" role="group" tabIndex={0} aria-label={t('Assistant tasks')}>
        <button type="button" disabled={busy||Boolean(text.trim())||Boolean(photo)} onClick={onViewTodayMedication}>{t('View today’s medication')}</button>
        {([
          ['Understand medicines','What are my current medications used for? Explain general uses separately from my reviewed instructions.'],
          ['Review my records','Summarise my recorded doses and health observations from the past 7 days. Distinguish unrecorded doses from reported not taken.'],
          ['Prepare for a visit','Help me prepare questions for a pharmacist or doctor using my saved medication and health records.'],
        ] as const).map(([label,prompt])=><button type="button" key={label} disabled={busy||Boolean(text.trim())||Boolean(photo)} onClick={()=>{setText(t(prompt));requestAnimationFrame(()=>focusMessage());}}>{t(label)}</button>)}
      </div></div>
    </>:null}
    {source&&!selectedHistory?<details className="assistant-source" aria-label={t('Source context')}><summary>{t('From')}: {t(source.page==='medicine-detail'?'Medication details':source.page==='medicines'?'Medicines':'Records')}{source.display_name?` ? ${t('Viewing')}: ${source.display_name}`:''}</summary><p className="notice">{t('Page context is a record reference. Current medication facts are checked again when needed.')}</p>{onSourceReturn?<button type="button" className="text-button" onClick={()=>onSourceReturn(source)}>{t('Return to source')}</button>:null}</details>:null}
    <div ref={timeline} className="conversation-scroll">
    {workspace&&[...views.current.entries()].some(([key,row])=>key!==viewKey.current&&!row.conversation&&(row.text||row.photo||row.turns.length||row.recent.length))?<button disabled={workspaceLocked} onClick={returnTemporary}>{t('Return to unsent conversation')}</button>:null}
    {olderCursor&&!selectedHistory?<button disabled={busy} onClick={()=>void earlierMessages()}>{t('Load earlier messages')}</button>:null}
    {!preferences.conversation_history_enabled?<p className="notice">{t('Saving is off. New messages stay temporary and cannot be restored across devices.')}</p>:null}
    {workspace&&selectedHistory?<article className="selected-history" data-guide="assistant-conversation"><button type="button" className="text-button" onClick={showCurrentConversation}>{t('Back to current conversation')}</button><p className="user-message">{selectedHistory.user_text}</p><p className="history-message">{patientMessage(selectedHistory.assistant_text)}</p></article>:null}
    {workspace&&!selectedHistory&&!recent.length&&!turns.length&&!pendingText?<p className="notice" data-guide="assistant-conversation">{t('Ask a question about your medicines or records.')}</p>:null}
    {recent.length&&!turns.length?<p className="notice">{t('Saved choices are read-only. Ask again to refresh medicine options.')}</p>:null}
    {!selectedHistory&&(recent.length||turns.length||pendingText)?<details className="recent-chat" open={!todayEntry||!compact||conversationExpanded||busy||confirmationIndex!==null||careProposal!==null||Boolean(pendingText)} onToggle={event=>{if(todayEntry&&compact)setConversationExpanded(event.currentTarget.open);}}><summary data-guide="assistant-conversation">{t('Recent conversation')} · {recent.length+turns.length}</summary>{recent.map((row,index)=><article key={`recent-${index}`}><p className="user-message">{row.user}{row.photo?<small>{t('Photo attached')}</small>:null}</p><p>{patientMessage(row.assistant)}</p></article>)}
    {/* Conversation reads top to bottom with the composer at the bottom, as
        every chat surface does. The input used to sit above the transcript, so
        the newest reply appeared *below* the field you type into. */}
    {!selectedHistory&&turns.length>visibleLiveTurns?<button onClick={()=>{retainScroll();setVisibleLiveTurns(value=>value+6);}}>{t('Load earlier messages')}</button>:null}
    {!selectedHistory&&turns.length ? <ul className="transcript" aria-live="polite" aria-hidden={confirmationIndex!==null}>
      {turns.map((turn, index) => index<turns.length-visibleLiveTurns?null:<li className="turn" key={index} data-guide={index===turns.length-1?'assistant-conversation':undefined}>
        <p className="user-message">{sentPhotoNames[index]?<span className="chat-photo-note">{t('Photo attached')}: {sentPhotoNames[index]}<br/></span>:null}{sentTexts[index]}</p>
        <p>{turn.medication_choice?.prompt||patientMessage(turn.message)}</p>
        {turn.medication_choice?<MedicationChoices choice={turn.medication_choice} disabled={busy||index!==turns.length-1} onChoose={(choice,label)=>void send(choice,label)}/>:null}
        <AnswerSources traces={turn.tool_traces}/>
        {turn.health_note_request?<button onClick={()=>onHealthReview?.(turn.health_note_request?.description??'')}>{t('Review health note')}</button>:null}
        {turn.care_request?<button onClick={()=>setCareProposal(turn.care_request??null)}>{t('Review medication-care record')}</button>:null}
        {turn.visual_check_request ? <button onClick={()=>onVisualCheck?.(turn.visual_check_request?.regimen_id??null)}>{t("Compare a pill photo")}</button> : null}
        {turn.intent === 'reminder' && !turn.tool_traces.some(trace => trace.tool_name === 'create_reminder') ? <div className="actions">{[15,30].map(minutes => <button key={minutes} onClick={() => setText(`Remind me again in ${minutes} minutes.`)}>In {minutes} min</button>)}</div> : null}
        {reportStates[index]?<p role="status">{t(reportStates[index])}</p>:null}
        {turn.pending_report?<button onClick={()=>setConfirmationIndex(index)}>{t('Review dose report')}</button>:null}
        <div className="actions">
          <button className="icon-button speech-toggle" aria-label={t(speaking&&speakingIndex===index?'Stop audio':'Play response')} aria-pressed={speaking&&speakingIndex===index} onClick={()=>{if(speaking&&speakingIndex===index){stopPlayback();setSpeaking(false);}else void readAloud(turn.message,index);}} disabled={!preferences.voice_enabled}><Icon name="speaker"/></button>
        </div>
        <details><summary>{t('How this answer was made')}</summary><p>{t(answerExplanation(turn.mode))}</p>
          <ul>{turn.tool_traces.map((trace, traceIndex) => <li key={traceIndex}>{toolTraceLabel(trace)}: {trace.status}{trace.error_code?` (${trace.error_code})`:''}</li>)}</ul>
        </details>
      </li>)}
    </ul> : null}</details>:null}

    {pendingText?<div className="turn pending-message"><p className="user-message">{pendingText}</p>{busy?<p role="status">{t('Checking your records...')}</p>:null}</div>:null}
    {workspace&&busy&&!pendingText?<p role="status">{t('Starting a new conversation?')}</p>:null}
    {active&&error ? <ErrorNotice error={error} /> : null}
    {workspace&&reportNotice ? <p role="status">{t(reportNotice)}</p> : null}
        {confirmationIndex!==null&&turns[confirmationIndex]?.pending_report ? (()=>{const index=confirmationIndex,turn=turns[index]!;const cancel=()=>{setTurns(previous=>previous.map((row,at)=>at===index?{...row,pending_report:null}:row));setReportStates(previous=>({...previous,[index]:'Report cancelled'}));setConfirmationIndex(null);};return <ConfirmReportSheet title="Just to confirm" summary={turn.pending_report!.summary} busy={busy} onConfirm={()=>void confirmReport(index)} onCancel={cancel}>
        <button onClick={()=>void readAloud(turn.message,index)} disabled={!preferences.voice_enabled}>{t('Play response')}</button>{speaking?<button onClick={()=>{stopPlayback();setSpeaking(false);}}>{t('Stop audio')}</button>:null}</ConfirmReportSheet>;})() : null}
    {careProposal?<CareReviewSheet proposal={careProposal} onCancel={()=>setCareProposal(null)} onSaved={()=>{setCareProposal(null);setReportNotice('Your medication-care record was saved.');onChanged?.();window.dispatchEvent(new Event('pharmascan:reminder-refresh'));}}/>:null}

    </div>
    <div className={workspace?"conversation-interaction":todayEntry?'today-assistant__interaction':undefined} hidden={Boolean(selectedHistory)}>
    {workspace&&!selectedHistory?<nav className="workspace-tasks" aria-label={t('Assistant tasks')}><div className="assistant-tasks" aria-label={t('Assistant tasks')}>
      <button type="button" aria-label={t('View today’s medication')} disabled={busy||Boolean(text.trim())||Boolean(photo)} onClick={onViewTodayMedication}>{t("Today's medication")}</button>{([
      ['Understand medicines','What are my current medications used for? Explain general uses separately from my reviewed instructions.'],
      ['Review my records','Summarise my recorded doses and health observations from the past 7 days. Distinguish unrecorded doses from reported not taken.'],
      ['Prepare medication review','Help me prepare questions for a pharmacist or doctor using my saved medication and health records.'],
    ] as const).map(([label,prompt])=><button key={label} aria-label={t(label)} disabled={busy||Boolean(text.trim())||Boolean(photo)} onClick={()=>{setText(t(prompt));focusMessage();}}>{t(label==='Review my records'?'View records':label)}</button>)}</div></nav>:null}
    {photo?<div hidden={Boolean(selectedHistory)} className="photo-attachment" aria-label={t('Photo attachment')}>
      {photoPreview?<img src={photoPreview} alt={t('Selected photo preview')}/>:null}
      <div className="photo-attachment__details"><strong>{photo.name}</strong>
        <label>{t('Photo type')} <select value={photoType} onChange={event=>setPhotoType(event.target.value as typeof photoType)}>
          <option value="pharmacy_label">{t('Pharmacy label')}</option><option value="prescription">{t('Prescription')}</option><option value="package">{t('Medicine packaging')}</option>
        </select></label>
        <label className="photo-consent"><input type="checkbox" checked={photoConsent} onChange={event=>setPhotoConsent(event.target.checked)}/>{t('Allow photo processing. The image is not saved; extracted details may appear in saved chats.')}</label>
      </div>
      <button type="button" className="icon-button" aria-label={t('Remove photo')} onClick={()=>setPhoto(null)}><Icon name="close"/></button>
    </div>:null}
    <div className="composer-row" data-guide="assistant-composer" hidden={Boolean(selectedHistory)}>
      <input ref={photoInput} className="sr-only" type="file" accept="image/png,image/jpeg" aria-label={t('Choose a photo')} onChange={event=>{const selected=event.currentTarget.files?.[0]??null;setPhoto(selected);event.currentTarget.value='';}}/>
      <button className="photo-button" type="button" aria-label={t('Add a photo to chat')} onClick={()=>photoInput.current?.click()}><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1"/><path d="m4 18 5-5 4 3 4-5 4 6"/></svg></button>
      {workspace?<textarea ref={workspaceInput} rows={1} maxLength={2000} aria-label={t("Review your message before sending")} value={text} disabled={busy}
        onChange={event=>setText(event.target.value)} placeholder={t("Ask about your medication...")}
        onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.nativeEvent.isComposing){event.preventDefault();void send();}}}/>:<input ref={messageInput} maxLength={2000} aria-label={t("Review your message before sending")} value={text} disabled={busy}
        onChange={event=>setText(event.target.value)} placeholder={t("Ask about your medication...")}
        onKeyDown={event=>{if(event.key==='Enter'&&!event.nativeEvent.isComposing)void send();}}/>}
      {usage&&compact?<span className="composer-allowance" role="status" title={`${t('AI conversations left today')}: ${remaining} / ${usage.limit} · ${t('Resets at midnight Singapore time')}`}>
        <span aria-hidden="true">{remaining} / {usage.limit}</span>
        <span className="sr-only">{t('AI conversations left today')}: {remaining} / {usage.limit} · {t('Resets at midnight Singapore time')}</span>
      </span>:null}
      {preferences.voice_enabled ? <VoiceInput key={`${language}:${viewKey.current}`} onTranscript={setText} disabled={busy||!active} /> : null}
      <button className="primary composer-send" aria-label={t(busy?'Sending...':'Send')} title={t(busy?'Sending...':'Send')} onClick={() => void send()} disabled={busy || (!text.trim()&&!photo) || Boolean(photo&&!photoConsent)} aria-busy={busy}>{workspace?<Icon name="send"/>:t('Send')}</button>
    </div>
    {usage&&compact&&todayEntry?<p className="today-assistant__allowance" role="status" title={`${t('AI conversations left today')} · ${t('Resets at midnight Singapore time')}`}>{t('AI conversations left today')}: {remaining} / {usage.limit}</p>:null}
    {usage&&!compact ? <p className="ai-allowance" role="status"><span className="allowance-detail">{t('AI conversations left today')}: {remaining} / {usage.limit} · {t('Resets at midnight Singapore time')}{usage.llm_user_turns>=usage.limit?`. ${t('Your medication records, reports and reminders still work.')}`:''}</span><span className="allowance-compact" aria-hidden="true">AI: {remaining} / {usage.limit}</span></p> : null}
    {workspace&&error&&(text.trim()||photo||outgoing.current.get(viewKey.current)?.selection)?<button className="text-button composer-retry" disabled={busy} onClick={()=>{const failed=outgoing.current.get(viewKey.current);void send(failed?.selection,failed?.selection?failed.text:undefined);}}>{t('Retry sending')}</button>:null}
    </div>
  </section></ConversationSurface>;
}

export function patientMessage(message: string): string {
  return message.replace(/^\[degraded: deterministic rule routing, not a live LLM\]\s*/, '');
}
