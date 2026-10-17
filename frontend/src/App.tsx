import {accountDisplayName} from './accountPresentation';
import {Icon,type IconName} from './components/Icon';
import {LanguageMenu} from './components/LanguageMenu';
import {NotificationInvitation} from './components/NotificationInvitation';
import { LanguageProvider, useLanguage } from './language';
import { useCallback, useEffect, useState, useRef } from 'react';
import { api, type EvidenceTask, type HealthResponse, type RegimenHistoryItem, type SourcePreview, type MedicationListResponse } from './api/client';
import {medicationSetupEntries} from './medicationSetup';
import { AssistantScreen } from './components/AssistantScreen';
import { EnrollScreen } from './components/EnrollScreen';
import { HistoryScreen } from './components/HistoryScreen';
import {MedicinesHub,AddMethodScreen,MedicationDetail,isPastCourse,type MedicineDestination} from './components/MedicinesHub';
import {PatientHub,ProfileScreen,InformationScreen,Entry,type MeDestination} from './components/PatientHub';
import {HealthTrackingScreen} from './components/HealthTrackingScreen';
import {ReviewSummaryScreen} from './components/ReviewSummaryScreen';
import {CareTasksScreen,CareTaskSummary} from './components/CareTasksScreen';
import {AdherenceBarriersScreen} from './components/AdherenceBarriersScreen';
import {MedicationReviewScreen} from './components/MedicationReviewScreen';
import { EvidenceEnrollmentScreen } from './components/EvidenceEnrollmentScreen';
import {PersonalGalleryScreen} from './components/PersonalGalleryScreen';
import {PendingEvidenceTasks} from './components/PendingEvidenceTasks';
import { Card, ErrorNotice } from './components/primitives';
import { Row, RowGroup, Screen } from './ui/primitives';
import { VisualCheckScreen } from './components/VisualCheckScreen';
import { TodayScreen } from './components/TodayScreen';
import {MeScreen} from './components/MeScreen';
import {SettingsScreen} from './components/SettingsScreen';
import {FeedbackScreen} from './components/FeedbackScreen';
import {ReminderMonitor} from './components/ReminderMonitor';
import {accountAuth,type Account} from './api/auth';
import {OnboardingGuide} from './components/OnboardingGuide';
import {TodayMedicationCarousel} from './components/TodayMedicationCarousel';
import {readTour} from './onboarding';
import {useCareNavigation} from './navigation';
import {greetingAt,greetingName} from './greeting';
import {CaregiversScreen} from './components/CaregiversScreen';

type Tab = 'check-result' | 'check' | 'today' | 'medicines' | 'records' | 'assistant' | 'me' | 'settings' | 'health-notes' | 'summary-week' | 'summary-month' | 'summary-course' | MedicineDestination | MeDestination | 'help' | 'edit-medication';
const tabs: { id: Tab; label: string; symbol: IconName }[] = [
  { id: 'today', label: 'Today', symbol: 'house' }, { id: 'medicines', label: 'Medicines', symbol: 'pill' },
  { id: 'records', label: 'Records', symbol: 'clipboard' }, { id: 'me', label: 'Me', symbol: 'user' },
  { id: 'assistant', label: 'AI assistant', symbol: 'message' },
];

export function App() { return <LanguageProvider><CompanionApp /></LanguageProvider>; }

function CompanionApp() {
  const headerRef=useRef<HTMLElement>(null),navRef=useRef<HTMLElement>(null),mainRef=useRef<HTMLElement>(null);
  useEffect(()=>{
    /* Written on the document root: the shell that reserves this space is an
       ancestor of the header and the nav, so a variable set on a sibling would
       never be read and the fallbacks would always win. */
    const update=()=>{const root=document.documentElement;root.style.setProperty('--app-header-height',`${headerRef.current?.getBoundingClientRect().height??72}px`);root.style.setProperty('--bottom-nav-height',`${navRef.current?.getBoundingClientRect().height??72}px`);};
    const measure=()=>{update();const rect=mainRef.current?.getBoundingClientRect();if(rect){document.documentElement.style.setProperty('--patient-content-left',`${rect.left}px`);document.documentElement.style.setProperty('--patient-content-width',`${rect.width}px`);}};
    measure();const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(measure);
    if(headerRef.current)observer?.observe(headerRef.current);if(navRef.current)observer?.observe(navRef.current);
    if(mainRef.current)observer?.observe(mainRef.current);
    window.addEventListener('resize',measure);return()=>{observer?.disconnect();window.removeEventListener('resize',measure);};
  },[]);
  const {t,preferences,loadPreferences,preferenceError}=useLanguage();
  const [evidenceTaskId,setEvidenceTaskId]=useState<string|null>(null);
  const [conversationClearRevision,setConversationClearRevision]=useState(0);
  const [assistantSlots,setAssistantSlots]=useState<Record<string,unknown>>({});
  const [routedPhoto,setRoutedPhoto]=useState<File|null>(null);
  const [healthDescription,setHealthDescription]=useState('');
  const [visualRegimen, setVisualRegimen] = useState<string|null>(null);
  const [sourceSelection] = useState<{preview: SourcePreview; name: string} | null>(null);
  const [versions,setVersions]=useState<RegimenHistoryItem[]>([]);
  const [editTarget,setEditTarget]=useState<RegimenHistoryItem|null>(null);
  const [detailId,setDetailId]=useState<string|null>(null);
  const [drafts, setDrafts] = useState<RegimenHistoryItem[]>([]);
  const [sourceTasks,setSourceTasks]=useState<EvidenceTask[]|null>(null),[setupError,setSetupError]=useState<unknown>(null);
  const setupRequest=useRef(0);
  const loadSourceTasks=useCallback(async()=>{const version=++setupRequest.current;try{const rows=await api.evidenceTasks();if(version===setupRequest.current){setSourceTasks(rows);setSetupError(null);}}catch(caught){if(version===setupRequest.current){setSourceTasks(null);setSetupError(caught);}}},[]);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [medications, setMedications] = useState<MedicationListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [fatal, setFatal] = useState<unknown>(null);
  const [guideOpen,setGuideOpen]=useState(false),[guideOwner,setGuideOwner]=useState(''),[guideReplay,setGuideReplay]=useState(false);
  const {tab,navigate:setTab,back:goBack,isRoot}=useCareNavigation(guideOpen&&!loading&&!fatal&&Boolean(medications));
  const [member,setMember]=useState(false),[identity,setIdentity]=useState<Account|null>(null),[now,setNow]=useState(()=>new Date());
  /* The signed-out state gets its own surface, so the shell needs to know the
     kind of identity and not only whether an email account is linked. */
  const [accountKind,setAccountKind]=useState<'member'|'guest'|'signed_out'|'local'|null>(null);
  useEffect(()=>{void accountAuth.account().then(value=>{setMember(value.kind==='member');setIdentity(value);setAccountKind(value.kind);}).catch(()=>{setMember(false);setAccountKind(null);});const tick=()=>setNow(new Date());const timer=window.setInterval(tick,60000);window.addEventListener('focus',tick);return()=>{clearInterval(timer);window.removeEventListener('focus',tick);};},[]);
  const [focusRegimen,setFocusRegimen]=useState<string|null>(null);
  const closeGuide=()=>{setGuideOpen(false);requestAnimationFrame(()=>document.querySelector<HTMLButtonElement>('[data-guide="today"]')?.focus());};
  useEffect(()=>{if(['today','medicines','records','me'].includes(tab))setEvidenceTaskId(null);},[tab]);
  const openGuide=()=>{setTab('today');setGuideReplay(true);setGuideOpen(true);};
  useEffect(()=>accountAuth.watchIdentity?.(()=>{window.localStorage.removeItem('pharmascan.agent-session');window.location.reload();}),[]);
  const refreshMedications = useCallback(async () => {
    try { const [active, versions] = await Promise.all([api.listMedications(), api.regimenHistory(),loadSourceTasks()]); setMedications(active); setVersions(versions); setDrafts(versions.filter(row => row.state === 'draft' || row.state === 'pending_clarification')); setFatal(null); } catch (caught) { setFatal(caught); }
  }, [loadSourceTasks]);
  const bootstrap=useRef<Promise<{state:HealthResponse;session:Awaited<ReturnType<typeof api.startDemo>>;active:MedicationListResponse;versions:RegimenHistoryItem[]}>|null>(null);
  useEffect(()=>{
    let live=true;
    if(!bootstrap.current)bootstrap.current=(async()=>{
      const state=await api.health();
      if(state.runtime_contract!=="patient-ux-reminders-v1")throw new Error("The app connection needs a restart. Please restart the development servers.");
      const session=await api.startDemo();
      const [active,versions]=await Promise.all([api.listMedications(),api.regimenHistory(),loadPreferences(),loadSourceTasks()]);
      return {state,session,active,versions};
    })();
    void bootstrap.current.then(({state,session,active,versions})=>{
      if(!live)return;
      localStorage.setItem("pharmascan.agent-session",session.session_id);setHealth(state);setSessionId(session.session_id);setGuideOwner(session.patient_id);
      if(readTour(session.patient_id).status==='in_progress'){setTab('today');setGuideOpen(true);}
      setMedications(active);setVersions(versions);setDrafts(versions.filter(row=>row.state==='draft'||row.state==='pending_clarification'));setFatal(null);
    }).catch(caught=>{bootstrap.current=null;if(live)setFatal(caught);}).finally(()=>{if(live)setLoading(false);});
    return()=>{live=false;};
  },[loadPreferences,setTab,loadSourceTasks]);
  const setupEntries=sourceTasks===null?null:medicationSetupEntries(sourceTasks,versions);

  const greeting=greetingAt(now,preferences.timezone);
  const name=greetingName(member,accountDisplayName(identity,preferences.display_name,t('Guest')),t('Guest'));
  const accountPage=['me','settings','feedback','profile','account','caregivers','reminder-settings','language-settings','accessibility','privacy','conversations','about','help'].includes(tab);
  /** One Assistant instance keeps message and draft state across route changes. */
  const assistantSurface=['today','medicines','records','me','assistant'].includes(tab);
  /* A signed-out account page is a standalone sign-in surface: it is a decision
     about identity, so it renders without the tabs, the rail or the composer. */
  const standaloneSignIn=accountKind==='signed_out'&&tab==='account';
  const assistantVisible=!standaloneSignIn&&(tab==='today'||tab==='assistant');
  const openMedicine=(page:MedicineDestination,id?:string)=>{if(id)setDetailId(id);setTab(page);};
  const detail=versions.find(row=>row.regimen_id===detailId);
  const openAssistant=()=>{setAssistantSlots(tab==='medicine-detail'&&detail?{regimen_id:detail.regimen_id,medication_id:detail.medication_id}:{});setTab('assistant');};
  const calendarDate=new Intl.DateTimeFormat('en-CA',{timeZone:preferences.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const currentMedications=medications?.medications.filter(row=>!isPastCourse(row,calendarDate)&&(!row.course_start_date||row.course_start_date<=calendarDate))??[];
  const guideVisible=guideOpen&&!loading&&!fatal&&Boolean(medications)&&tab==='today';
  return <div className={standaloneSignIn?'app companion signin-shell':'app companion'} data-root-surface={assistantSurface?'true':undefined}><div data-app-content>
    <a className="skip-link" href="#main-content">{t('Skip to content')}</a>
    {!standaloneSignIn?<header ref={headerRef} className="companion-header app-header">{!isRoot&&tab!=='assistant'?<button className="back-button" aria-label={t('Back')} onClick={goBack}><Icon name="chevron-left"/></button>:null}<div className="brand"><img className="brand-mark" src="/branding/medithread-192.png" width="28" height="28" alt=""/><span>MediThread</span></div><LanguageMenu/>{tab!=='assistant'?<button type="button" className="assistant-header-shortcut" aria-label={t('AI assistant')} onClick={openAssistant}><img src="/branding/assistant-avatar-green.png" width="28" height="28" alt=""/><span>{t('AI assistant')}</span></button>:null}<button className="notification-shortcut" aria-label={t('Medication reminders')} onClick={()=>setTab('reminder-settings')}><Icon name="bell"/></button><button className="settings-shortcut" aria-label={t('Settings')} onClick={()=>setTab('settings')}><Icon name="settings"/></button></header>:null}
    {preferenceError ? <p role="alert">{preferenceError}</p> : null}
    {fatal ? <ErrorNotice error={fatal} /> : null}
    <main ref={mainRef} id="main-content" className="app-main">
    {!guideOpen?<NotificationInvitation ownerId={guideOwner} onSettings={()=>setTab('reminder-settings')}/>:null}
    {loading&&!accountPage ? <Card title="Getting your records ready"><p role="status">{t('Starting your private demo session…')}</p></Card> : !medications&&!accountPage ? <Card title="Your records could not be loaded"><p>{t('Please retry the connection. An unavailable record is not an empty medication list.')}</p><button onClick={() => { if (health && sessionId) void refreshMedications(); else window.location.reload(); }}>{t('Retry loading records')}</button></Card> : <>
      {tab==='today'?<section className="welcome"><h1 className="greeting">{t(greeting)}{preferences.preferred_language==='zh'?'，':', '}{name}!</h1><p>{t('Your medication and self-care companion')}</p></section>:null}
      <div hidden={!assistantVisible}><AssistantScreen workspace={tab==='assistant'} ownerId={guideOwner} clearRevision={conversationClearRevision} onClose={goBack} contextSlots={assistantSlots} onExpand={openAssistant} active={tab==='today'||tab==='assistant'} onHealthReview={description=>{setHealthDescription(description);setTab('health-notes');}} onVisualCheck={id=>{setVisualRegimen(id);setTab('check');}} sessionId={sessionId} onSession={setSessionId} todayEntry={tab==='today'} compact={tab!=='assistant'} onChanged={refreshMedications}/></div>
      {tab === 'check'||tab==='check-result' ? <VisualCheckScreen ownerId={guideOwner} initialFile={routedPhoto} showResult={tab==='check-result'} onResult={()=>setTab('check-result')} showBack={false} regimenId={visualRegimen} onBack={goBack} onAddSource={()=>setTab('label')}/> : null}
      {tab === 'today' ? <>

        <div className="today-panels">{currentMedications.length?<TodayMedicationCarousel medications={currentMedications} focusRegimenId={focusRegimen}>{medication=><TodayScreen key={medication.regimen_id} showTitle={false} focusRegimenId={focusRegimen} onFeeling={()=>{setHealthDescription('');setTab('health-notes');}} onVisualCheck={id=>{setVisualRegimen(id);setTab('check');}} compact medications={[medication]} onChanged={refreshMedications} onMedicines={()=>setTab('medicines')} onHistory={()=>setTab('records')}/>}</TodayMedicationCarousel>:<TodayScreen compact medications={[]} onChanged={refreshMedications} onMedicines={()=>setTab('medicines')} onHistory={()=>setTab('records')} onVisualCheck={()=>{setVisualRegimen(null);setTab('check');}}/>}
        <CareTaskSummary medications={medications?.medications??[]} onOpen={()=>setTab('care-tasks')}/></div>
      </> : null}
      {tab==='medicines'?<MedicinesHub medications={medications?.medications??[]} drafts={drafts} setupCount={setupEntries?.length??null} versions={versions} onOpen={openMedicine}/>:null}
      {tab==='add-method'?<AddMethodScreen onOpen={setTab}/>:null}
      <div data-testid="evidence-workspace" hidden={tab!=='label'}><EvidenceEnrollmentScreen active={tab==='label'} ownerId={guideOwner} onPill={file=>{setRoutedPhoto(file);setVisualRegimen(null);setTab('check');}} onNewRegistration={()=>setEvidenceTaskId(null)} onCancel={()=>{void refreshMedications();setTab('unfinished');}} initialTaskId={evidenceTaskId} sessionId={sessionId} onChanged={refreshMedications}/></div>
      <div hidden={tab!=='manual'}><EnrollScreen resumeRegimenId={resumeId} resumeRow={versions.find(row=>row.regimen_id===resumeId)??null} sourceSelection={sourceSelection} sessionId={sessionId} medications={medications} onChanged={refreshMedications}/></div>
      <div data-page="edit-medication" hidden={tab!=='edit-medication'}>{editTarget?<EnrollScreen onActivated={id=>{setDetailId(id);goBack();}} editFrom={editTarget} sessionId={sessionId} medications={medications} onChanged={refreshMedications}/>:tab==='edit-medication'?<Card title="Choose a medication"><button onClick={()=>setTab('medicines')}>{t('Medicines')}</button></Card>:null}</div>
      {tab==='unfinished'?<PendingEvidenceTasks entries={setupEntries} error={setupError} onRetry={()=>void refreshMedications()} onContinue={id=>{setEvidenceTaskId(id);setTab('label');}} onResume={id=>{setResumeId(id);setTab('manual');}}/>:null}
      {tab==='past-medicines'?<Card title="Past courses">{versions.filter(row=>isPastCourse(row,calendarDate)).map(row=><Entry key={row.regimen_id} title={row.display_name} hint={`${row.course_start_date??t('Not specified')} → ${row.course_end_date??t('Not specified')}`} onClick={()=>openMedicine('medicine-detail',row.regimen_id)}/>)}{!versions.some(row=>isPastCourse(row,calendarDate))?<p>{t('No past courses yet.')}</p>:null}</Card>:null}
      {tab==='medicine-detail'&&!detail?<Card title="Choose a medication"><button onClick={()=>setTab('medicines')}>{t('Medicines')}</button></Card>:null}
      {tab==='medicine-detail'&&detail?<MedicationDetail versions={versions} summary={medications?.medications.find(row=>row.regimen_id===detail.regimen_id)} onAssistant={openAssistant} onChanged={refreshMedications} onEdit={()=>{setEditTarget(detail);setTab('edit-medication');}} row={detail} onHistory={()=>setTab('records')} onGallery={()=>setTab('gallery')} onCheck={()=>{setVisualRegimen(detail.regimen_id);setTab('check');}}/>:null}
      {tab==='gallery'?<PersonalGalleryScreen onSources={id=>{setEvidenceTaskId(id);setTab('label');}} onCheck={id=>{setVisualRegimen(id);setTab('check');}}/>:null}
      {tab==='care-tasks'?<CareTasksScreen regimens={versions}/>:null}
      {tab==='adherence-barriers'?<AdherenceBarriersScreen regimens={versions}/>:null}
      {tab==='medication-review'?<MedicationReviewScreen/>:null}
      {tab==='health-notes'?<HealthTrackingScreen initialDescription={healthDescription} medications={medications?.medications??[]}/>:null}
      {tab.startsWith('summary-')?<ReviewSummaryScreen period={tab==='summary-week'?'week':tab==='summary-month'?'month':'course'} regimens={versions}/>:null}
      {tab === 'records' ? <Screen title="Records" lead="Your own reports, and the summaries you can take to a review.">
        <RowGroup title="Medication and health summary" className="records-summary">
          <div className="period-actions records-summary-actions">{(['week','month','course'] as const).map(period=><button key={period} onClick={()=>setTab(`summary-${period}`)}>{t(period==='week'?'This week':period==='month'?'This month':'By medication plan')}</button>)}</div>
        </RowGroup>
        <RowGroup title="Health records and ongoing care" hint="Choose an area to review or update." className="records-navigation-group" spread>
          <Row icon="heart" title="My health notes" hint="How you have been feeling" onClick={()=>setTab('health-notes')}/>
          <Row icon="alert" title="Medication difficulties" hint="Challenges managing medicines" onClick={()=>setTab('adherence-barriers')}/>
          <Row icon="calendar" title="Medication follow-ups" hint="Your care follow-ups" onClick={()=>setTab('care-tasks')}/>
          <Row icon="clipboard" title="Medication review preparation" hint="Information for your next review" onClick={()=>setTab('medication-review')}/>
        </RowGroup>
        <div className="screen-full"><HistoryScreen /></div>
      </Screen> : null}
      {tab==='me'?<PatientHub onOpen={setTab} onGuide={openGuide}/>:null}
      {tab==='help'?<OnboardingGuide owner={guideOwner} replay onClose={()=>setTab('me')}/>:null}
      {tab==='account'?<MeScreen standalone={standaloneSignIn} onGuest={()=>setTab('today')} onHelp={()=>setTab('help')} onSettings={()=>setTab('settings')} onFeedback={()=>setTab('feedback')} onIdentityChanged={()=>{window.localStorage.removeItem('pharmascan.agent-session');window.location.reload();}}/>:null}
      {tab==='profile'?<><ProfileScreen/><MeScreen onIdentityChanged={()=>window.location.reload()}/></>:null}
      {tab==='privacy'||tab==='conversations'||tab==='about'?<InformationScreen ownerId={guideOwner} kind={tab} onConversationCleared={()=>setConversationClearRevision(value=>value+1)} onHistory={()=>setTab('records')}/>:null}
      {tab==='caregivers'?<CaregiversScreen/>:null}
      {tab==='settings'?<SettingsScreen/>:null}
      {tab==='reminder-settings'||tab==='language-settings'||tab==='accessibility'?<SettingsScreen section={tab==='reminder-settings'?'reminders':tab==='language-settings'?'language':'accessibility'}/>:null}
      {tab==='feedback'?<FeedbackScreen/>:null}

    </>}
    </main>
    {!standaloneSignIn?<ReminderMonitor enabled={!loading&&!fatal&&!guideVisible} onReview={id=>{setFocusRegimen(id);setTab('today');}}/>:null}
    {!standaloneSignIn?<nav ref={navRef} className="patient-nav" aria-label="Main navigation">{tabs.map(entry => <button key={entry.id} data-guide={entry.id} className={entry.id==='assistant'?'nav-assistant':''}
      aria-current={(tab === entry.id || (entry.id==='today'&&['check','check-result','care-tasks'].includes(tab)) || (entry.id==='me'&&accountPage)||(entry.id==='medicines'&&['add-method','past-medicines','unfinished','gallery','medicine-detail','label','manual','edit-medication'].includes(tab))||(entry.id==='records'&&(tab.startsWith('summary-')||['health-notes','adherence-barriers','medication-review'].includes(tab)))) ? 'page' : undefined} onClick={() => entry.id==='assistant'?openAssistant():setTab(entry.id)}>
      {entry.id==='assistant'?<img className="nav-assistant__avatar" src="/branding/assistant-avatar-green.png" width="28" height="28" alt=""/>:<Icon name={entry.symbol}/>}<span>{t(entry.label)}</span></button>)}</nav>:null}
    </div>{guideVisible?<OnboardingGuide owner={guideOwner} replay={guideReplay} onClose={closeGuide}/>:null}
  </div>;
}
