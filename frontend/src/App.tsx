import { LanguageProvider, useLanguage } from './language';
import { useCallback, useEffect, useState, useRef } from 'react';
import { api, type HealthResponse, type RegimenHistoryItem, type SourcePreview, type MedicationListResponse } from './api/client';
import { AssistantScreen } from './components/AssistantScreen';
import { EnrollScreen } from './components/EnrollScreen';
import { HistoryScreen } from './components/HistoryScreen';
import {MedicinesHub,AddMethodScreen,MedicationDetail,isPastCourse,type MedicineDestination} from './components/MedicinesHub';
import {PatientHub,ProfileScreen,InformationScreen,Entry,type MeDestination} from './components/PatientHub';
import {HealthTrackingScreen} from './components/HealthTrackingScreen';
import {ReviewSummaryScreen} from './components/ReviewSummaryScreen';
import { EvidenceEnrollmentScreen } from './components/EvidenceEnrollmentScreen';
import {PersonalGalleryScreen} from './components/PersonalGalleryScreen';
import {PendingEvidenceTasks} from './components/PendingEvidenceTasks';
import { Card, ErrorNotice } from './components/primitives';
import { VisualCheckScreen } from './components/VisualCheckScreen';
import { TodayScreen } from './components/TodayScreen';
import {MeScreen} from './components/MeScreen';
import {SettingsScreen} from './components/SettingsScreen';
import {FeedbackScreen} from './components/FeedbackScreen';
import {ReminderMonitor} from './components/ReminderMonitor';
import {accountAuth} from './api/auth';
import {HeaderAccountButton} from './components/HeaderAccountButton';
import {OnboardingGuide,guideWasDismissed,rememberGuideDismissal} from './components/OnboardingGuide';
import {TodayMedicationCarousel} from './components/TodayMedicationCarousel';
import {CaregiversScreen} from './components/CaregiversScreen';

type Tab = 'check' | 'today' | 'medicines' | 'history' | 'assistant' | 'me' | 'settings' | 'health-notes' | 'summary-week' | 'summary-month' | 'summary-course' | MedicineDestination | MeDestination;
const tabs: { id: Tab; label: string; symbol: string }[] = [
  { id: 'today', label: 'Today', symbol: '◷' }, { id: 'medicines', label: 'Medicines', symbol: '+' },
  {id:'assistant',label:'Assistant',symbol:'✧'}, { id: 'history', label: 'History', symbol: '≡' }, { id: 'me', label: 'Me', symbol: '○' },
];

export function App() { return <LanguageProvider><CompanionApp /></LanguageProvider>; }

function CompanionApp() {
  const headerRef=useRef<HTMLElement>(null),navRef=useRef<HTMLElement>(null);
  useEffect(()=>{
    const update=()=>{const root=headerRef.current?.parentElement;if(!root)return;root.style.setProperty('--app-header-height',`${headerRef.current?.getBoundingClientRect().height??66}px`);root.style.setProperty('--bottom-nav-height',`${navRef.current?.getBoundingClientRect().height??72}px`);};
    update();const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(update);
    if(headerRef.current)observer?.observe(headerRef.current);if(navRef.current)observer?.observe(navRef.current);
    window.addEventListener('resize',update);return()=>{observer?.disconnect();window.removeEventListener('resize',update);};
  },[]);
  const {t,preferences,loadPreferences,preferenceError}=useLanguage();
  const [evidenceTaskId,setEvidenceTaskId]=useState<string|null>(null);
  const [healthDescription,setHealthDescription]=useState('');
  const [visualRegimen, setVisualRegimen] = useState<string|null>(null);
  const [sourceSelection] = useState<{preview: SourcePreview; name: string} | null>(null);
  const [versions,setVersions]=useState<RegimenHistoryItem[]>([]);
  const [detailId,setDetailId]=useState<string|null>(null);
  const [drafts, setDrafts] = useState<RegimenHistoryItem[]>([]);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [navigation,setNavigation]=useState<Tab[]>(['today']);
  const tab=navigation[navigation.length-1]??'today';
  const [focusRegimen,setFocusRegimen]=useState<string|null>(null);
  const setTab=(next:Tab)=>{if(next===tab)return;const rows=[...navigation,next];window.history.pushState({pharmascanNavigation:rows},'');setNavigation(rows);document.documentElement.scrollTop=0;};
  const goBack=()=>{if(navigation.length>1)window.history.back();else setTab('today');};
  useEffect(()=>{window.history.replaceState({pharmascanNavigation:['today']},'');const back=(event:PopStateEvent)=>setNavigation(event.state?.pharmascanNavigation??['today']);window.addEventListener('popstate',back);return()=>window.removeEventListener('popstate',back);},[]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [medications, setMedications] = useState<MedicationListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [fatal, setFatal] = useState<unknown>(null);
  const [guideOpen, setGuideOpen] = useState(()=>!guideWasDismissed());
  const closeGuide=()=>{rememberGuideDismissal();setGuideOpen(false);};
  const openGuide=()=>{setTab('today');setGuideOpen(true);};
  useEffect(()=>accountAuth.watchIdentity?.(()=>{window.localStorage.removeItem('pharmascan.agent-session');window.location.reload();}),[]);
  const refreshMedications = useCallback(async () => {
    try { const [active, versions] = await Promise.all([api.listMedications(), api.regimenHistory()]); setMedications(active); setVersions(versions); setDrafts(versions.filter(row => row.state === 'draft' || row.state === 'pending_clarification')); setFatal(null); } catch (caught) { setFatal(caught); }
  }, []);
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const state = await api.health();
        if (state.runtime_contract !== "session03-manual-acceptance-v2") throw new Error("The app connection needs a restart. Start the current backend on port 8001. Your records have not been changed.");
        const session = await api.startDemo();
        await loadPreferences();
        if (!active) return;
        window.localStorage.setItem("pharmascan.agent-session",session.session_id); setHealth(state); setSessionId(session.session_id); await refreshMedications();
      } catch (caught) { if (active) setFatal(caught); }
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, [refreshMedications,loadPreferences]);
  const hour = Number(new Intl.DateTimeFormat('en-SG', { hour: 'numeric', hour12: false, timeZone: 'Asia/Singapore' }).format(new Date()));
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const accountPage=['me','settings','feedback','profile','account','caregivers','reminder-settings','language-settings','accessibility','privacy','about'].includes(tab);
  const openMedicine=(page:MedicineDestination,id?:string)=>{if(id)setDetailId(id);setTab(page);};
  const detail=versions.find(row=>row.regimen_id===detailId);
  const calendarDate=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Singapore',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const currentMedications=medications?.medications.filter(row=>!isPastCourse(row,calendarDate)&&(!row.course_start_date||row.course_start_date<=calendarDate))??[];
  const guideVisible=guideOpen&&!loading&&!fatal&&Boolean(medications)&&tab==='today';
  return <div className="app companion">
    <header ref={headerRef} className="companion-header app-header">{navigation.length>1?<button className="back-button" aria-label={t('Back')} onClick={goBack}>‹</button>:null}<div className="brand">PharmaScan Care</div><button className="language-shortcut" aria-label={t('Language and speech')} onClick={()=>setTab('language-settings')}>{preferences.preferred_language==='zh'?'中文':'EN'}</button><button className="settings-button" data-guide="settings" title={t('Settings')} aria-label={t('Settings')} onClick={()=>setTab('settings')}><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m9 3 1-1h4l1 1 .5 2 2 .9 2-.5 2 3.4-1.5 1.6v2.2l1.5 1.6-2 3.4-2-.5-2 .9-.5 2-1 1h-4l-1-1-.5-2-2-.9-2 .5-2-3.4 1.5-1.6v-2.2L2 8.8l2-3.4 2 .5 2-.9Z"/><circle cx="12" cy="11.5" r="3"/></svg></button><HeaderAccountButton ready={!loading} onOpen={()=>setTab('me')}/></header>
    {preferenceError ? <p role="alert">{preferenceError}</p> : null}
    {fatal ? <ErrorNotice error={fatal} /> : null}
    {loading&&!accountPage ? <Card title="Getting your records ready"><p role="status">{t('Starting your private demo session…')}</p></Card> : !medications&&!accountPage ? <Card title="Your records could not be loaded"><p>{t('Please retry the connection. An unavailable record is not an empty medication list.')}</p><button onClick={() => { if (health && sessionId) void refreshMedications(); else window.location.reload(); }}>{t('Retry loading records')}</button></Card> : <>
      {tab === 'check' ? <VisualCheckScreen regimenId={visualRegimen} onBack={()=>setTab('today')} onAddSource={()=>setTab('label')}/> : null}
      {tab === 'today' ? <>
        <section className="welcome"><p className="eyebrow">{t(greeting)}!</p><h1>{t('Your medication companion')}</h1></section>
        {currentMedications.length?<TodayMedicationCarousel medications={currentMedications} focusRegimenId={focusRegimen}>{medication=><TodayScreen key={medication.regimen_id} showTitle={false} focusRegimenId={focusRegimen} onFeeling={()=>{setHealthDescription('');setTab('health-notes');}} onVisualCheck={id=>{setVisualRegimen(id);setTab('check');}} compact medications={[medication]} onChanged={refreshMedications} onMedicines={()=>setTab('medicines')} onHistory={()=>setTab('history')}/>}</TodayMedicationCarousel>:<TodayScreen compact medications={[]} onChanged={refreshMedications} onMedicines={()=>setTab('medicines')} onHistory={()=>setTab('history')} onVisualCheck={()=>{setVisualRegimen(null);setTab('check');}}/>}
      </> : null}
      <div hidden={tab!=='today'&&tab!=='assistant'}><AssistantScreen active={tab==='today'||tab==='assistant'} onHealthReview={description=>{setHealthDescription(description);setTab('health-notes');}} onVisualCheck={id=>{setVisualRegimen(id);setTab('check');}} sessionId={sessionId} onSession={setSessionId} compact={tab!=='assistant'} onChanged={refreshMedications} onPhoto={()=>setTab('label')}/></div>
      {tab==='medicines'?<MedicinesHub medications={medications?.medications??[]} drafts={drafts} versions={versions} onOpen={openMedicine}/>:null}
      {tab==='add-method'?<AddMethodScreen onOpen={setTab}/>:null}
      <div data-testid="evidence-workspace" hidden={tab!=='label'}><EvidenceEnrollmentScreen initialTaskId={evidenceTaskId} sessionId={sessionId} onChanged={refreshMedications}/></div>
      <div hidden={tab!=='manual'}><EnrollScreen resumeRegimenId={resumeId} sourceSelection={sourceSelection} sessionId={sessionId} medications={medications} onChanged={refreshMedications}/></div>
      {tab==='unfinished'?<><PendingEvidenceTasks onContinue={id=>{setEvidenceTaskId(id);setTab('label');}}/><Card title="Finish medication setup">{drafts.length?drafts.map(row=><Entry key={row.regimen_id} title={row.display_name} hint="This medication needs review before its schedule is enabled." onClick={()=>{setResumeId(row.regimen_id);setTab('manual');}}/>):<p>{t('No unfinished medication setup.')}</p>}</Card></>:null}
      {tab==='past-medicines'?<Card title="Past courses">{versions.filter(row=>isPastCourse(row,calendarDate)).map(row=><Entry key={row.regimen_id} title={row.display_name} hint={`${row.course_start_date??t('Not specified')} → ${row.course_end_date??t('Not specified')}`} onClick={()=>openMedicine('medicine-detail',row.regimen_id)}/>)}{!versions.some(row=>isPastCourse(row,calendarDate))?<p>{t('No past courses yet.')}</p>:null}</Card>:null}
      {tab==='medicine-detail'&&detail?<MedicationDetail row={detail} onHistory={()=>setTab('history')} onGallery={()=>setTab('gallery')} onCheck={()=>{setVisualRegimen(detail.regimen_id);setTab('check');}}/>:null}
      {tab==='gallery'?<PersonalGalleryScreen onSources={id=>{setEvidenceTaskId(id);setTab('label');}} onCheck={id=>{setVisualRegimen(id);setTab('check');}}/>:null}
      {tab==='health-notes'?<HealthTrackingScreen initialDescription={healthDescription} medications={medications?.medications??[]}/>:null}
      {tab.startsWith('summary-')?<ReviewSummaryScreen period={tab==='summary-week'?'week':tab==='summary-month'?'month':'course'} regimens={versions}/>:null}
      {tab === 'history' ? <><Card title="Medication and health summary"><div className="period-actions">{(['week','month','course'] as const).map(period=><button key={period} onClick={()=>setTab(`summary-${period}`)}>{t(period==='week'?'This week':period==='month'?'This month':'This course')}</button>)}</div><Entry title="My health notes" onClick={()=>setTab('health-notes')}/></Card><HistoryScreen /></> : null}
      {tab==='me'?<PatientHub onOpen={setTab} onGuide={openGuide}/>:null}
      {tab==='account'?<MeScreen onSettings={()=>setTab('settings')} onFeedback={()=>setTab('feedback')} onIdentityChanged={()=>{window.localStorage.removeItem('pharmascan.agent-session');window.location.reload();}}/>:null}
      {tab==='profile'?<ProfileScreen/>:null}
      {tab==='privacy'||tab==='about'?<InformationScreen kind={tab} onHistory={()=>setTab('history')}/>:null}
      {tab==='caregivers'?<CaregiversScreen/>:null}
      {tab==='settings'?<Card title="Settings"><Entry title="Medication reminders" onClick={()=>setTab('reminder-settings')}/><Entry title="Language and speech" onClick={()=>setTab('language-settings')}/><Entry title="Accessibility" onClick={()=>setTab('accessibility')}/><Entry title="Quick start guide" onClick={openGuide}/></Card>:null}
      {tab==='reminder-settings'||tab==='language-settings'||tab==='accessibility'?<SettingsScreen section={tab==='reminder-settings'?'reminders':tab==='language-settings'?'language':'accessibility'}/>:null}
      {tab==='feedback'?<FeedbackScreen/>:null}
    </>}
    <ReminderMonitor enabled={!loading&&!fatal&&!guideVisible} onReview={id=>{setFocusRegimen(id);setTab('today');}}/>
    <nav ref={navRef} className="patient-nav" aria-label="Main navigation">{tabs.map(entry => <button key={entry.id} data-guide={entry.id}
      aria-current={(tab === entry.id || (entry.id==='me'&&accountPage)||(entry.id==='medicines'&&['add-method','past-medicines','unfinished','gallery','medicine-detail','label','manual'].includes(tab))||(entry.id==='history'&&(tab.startsWith('summary-')||tab==='health-notes'))) ? 'page' : undefined} onClick={() => setTab(entry.id)}>
      <span aria-hidden="true">{entry.symbol}</span>{t(entry.label)}</button>)}</nav>
    {guideVisible?<OnboardingGuide onClose={closeGuide} onSettings={()=>{closeGuide();setTab('language-settings');}}/>:null}
  </div>;
}
