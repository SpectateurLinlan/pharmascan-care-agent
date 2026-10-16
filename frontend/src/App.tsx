import {Icon,type IconName} from './components/Icon';
import {LanguageMenu} from './components/LanguageMenu';
import {NotificationInvitation} from './components/NotificationInvitation';
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
import {accountAuth} from './api/auth';
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
];

export function App() { return <LanguageProvider><CompanionApp /></LanguageProvider>; }

function CompanionApp() {
  const headerRef=useRef<HTMLElement>(null),navRef=useRef<HTMLElement>(null);
  useEffect(()=>{
    /* Written on the document root: the shell that reserves this space is an
       ancestor of the header and the nav, so a variable set on a sibling would
       never be read and the fallbacks would always win. */
    const update=()=>{const root=document.documentElement;root.style.setProperty('--app-header-height',`${headerRef.current?.getBoundingClientRect().height??72}px`);root.style.setProperty('--bottom-nav-height',`${navRef.current?.getBoundingClientRect().height??72}px`);};
    update();const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(update);
    if(headerRef.current)observer?.observe(headerRef.current);if(navRef.current)observer?.observe(navRef.current);
    window.addEventListener('resize',update);return()=>{observer?.disconnect();window.removeEventListener('resize',update);};
  },[]);
  const {t,preferences,loadPreferences,preferenceError}=useLanguage();
  const [evidenceTaskId,setEvidenceTaskId]=useState<string|null>(null);
  const [assistantOpen,setAssistantOpen]=useState(false);
  const [assistantSlots,setAssistantSlots]=useState<Record<string,unknown>>({});
  const [routedPhoto,setRoutedPhoto]=useState<File|null>(null);
  const [healthDescription,setHealthDescription]=useState('');
  const [visualRegimen, setVisualRegimen] = useState<string|null>(null);
  const [sourceSelection] = useState<{preview: SourcePreview; name: string} | null>(null);
  const [versions,setVersions]=useState<RegimenHistoryItem[]>([]);
  const [editTarget,setEditTarget]=useState<RegimenHistoryItem|null>(null);
  const [detailId,setDetailId]=useState<string|null>(null);
  const [drafts, setDrafts] = useState<RegimenHistoryItem[]>([]);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [medications, setMedications] = useState<MedicationListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [fatal, setFatal] = useState<unknown>(null);
  const [guideOpen,setGuideOpen]=useState(false),[guideOwner,setGuideOwner]=useState(''),[guideReplay,setGuideReplay]=useState(false);
  const {tab,navigate:setTab,back:goBack,isRoot}=useCareNavigation(guideOpen&&!loading&&!fatal&&Boolean(medications));
  const contentRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(contentRef.current)contentRef.current.inert=guideOpen&&!loading&&!fatal&&Boolean(medications);},[guideOpen,loading,fatal,medications]);
  const [member,setMember]=useState(false),[now,setNow]=useState(()=>new Date());
  /* The signed-out state gets its own surface, so the shell needs to know the
     kind of identity and not only whether an email account is linked. */
  const [accountKind,setAccountKind]=useState<'member'|'guest'|'signed_out'|'local'|null>(null);
  useEffect(()=>{void accountAuth.account().then(value=>{setMember(value.kind==='member');setAccountKind(value.kind);}).catch(()=>{setMember(false);setAccountKind(null);});const tick=()=>setNow(new Date());const timer=window.setInterval(tick,60000);window.addEventListener('focus',tick);return()=>{clearInterval(timer);window.removeEventListener('focus',tick);};},[]);
  const [focusRegimen,setFocusRegimen]=useState<string|null>(null);
  const closeGuide=()=>{setGuideOpen(false);requestAnimationFrame(()=>document.querySelector<HTMLButtonElement>('[data-guide="today"]')?.focus());};
  const openGuide=()=>{setTab('today');setGuideReplay(true);setGuideOpen(true);};
  useEffect(()=>accountAuth.watchIdentity?.(()=>{window.localStorage.removeItem('pharmascan.agent-session');window.location.reload();}),[]);
  const refreshMedications = useCallback(async () => {
    try { const [active, versions] = await Promise.all([api.listMedications(), api.regimenHistory()]); setMedications(active); setVersions(versions); setDrafts(versions.filter(row => row.state === 'draft' || row.state === 'pending_clarification')); setFatal(null); } catch (caught) { setFatal(caught); }
  }, []);
  const bootstrap=useRef<Promise<{state:HealthResponse;session:Awaited<ReturnType<typeof api.startDemo>>;active:MedicationListResponse;versions:RegimenHistoryItem[]}>|null>(null);
  useEffect(()=>{
    let live=true;
    if(!bootstrap.current)bootstrap.current=(async()=>{
      const state=await api.health();
      if(state.runtime_contract!=="patient-ux-reminders-v1")throw new Error("The app connection needs a restart. Please restart the development servers.");
      const session=await api.startDemo();
      const [active,versions]=await Promise.all([api.listMedications(),api.regimenHistory(),loadPreferences()]);
      return {state,session,active,versions};
    })();
    void bootstrap.current.then(({state,session,active,versions})=>{
      if(!live)return;
      localStorage.setItem("pharmascan.agent-session",session.session_id);setHealth(state);setSessionId(session.session_id);setGuideOwner(session.patient_id);
      if(readTour(session.patient_id).status==='in_progress'){setTab('today');setGuideOpen(true);}
      setMedications(active);setVersions(versions);setDrafts(versions.filter(row=>row.state==='draft'||row.state==='pending_clarification'));setFatal(null);
    }).catch(caught=>{bootstrap.current=null;if(live)setFatal(caught);}).finally(()=>{if(live)setLoading(false);});
    return()=>{live=false;};
  },[loadPreferences,setTab]);

  const greeting=greetingAt(now,preferences.timezone);
  const name=greetingName(member,preferences.display_name,t('Guest'));
  const accountPage=['me','settings','feedback','profile','account','caregivers','reminder-settings','language-settings','accessibility','privacy','about','help'].includes(tab);
  /**
   * The assistant has exactly two presentations and one rule for each:
   *  - a docked composer on the four main screens, so help is always one tap
   *    away in the same place;
   *  - the full conversation surface when the patient opens it.
   * It is deliberately absent from forms and detail screens, where a floating
   * composer would compete with the action that screen exists for.
   */
  const assistantSurface=tab==='today'||tab==='medicines'||tab==='records'||tab==='me';
  /* A signed-out account page is a standalone sign-in surface: it is a decision
     about identity, so it renders without the tabs, the rail or the composer. */
  const standaloneSignIn=accountKind==='signed_out'&&tab==='account';
  const assistantVisible=!standaloneSignIn&&(assistantOpen||tab==='assistant'||assistantSurface);
  const dockVisible=!assistantOpen&&assistantSurface&&!standaloneSignIn;
  const openMedicine=(page:MedicineDestination,id?:string)=>{if(id)setDetailId(id);setTab(page);};
  const detail=versions.find(row=>row.regimen_id===detailId);
  const openAssistant=()=>{setAssistantSlots(tab==='medicine-detail'&&detail?{regimen_id:detail.regimen_id,medication_id:detail.medication_id}:{});setAssistantOpen(true);};
  const calendarDate=new Intl.DateTimeFormat('en-CA',{timeZone:preferences.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const currentMedications=medications?.medications.filter(row=>!isPastCourse(row,calendarDate)&&(!row.course_start_date||row.course_start_date<=calendarDate))??[];
  const guideVisible=guideOpen&&!loading&&!fatal&&Boolean(medications)&&tab==='today';
  return <div className={dockVisible?'app companion has-dock':standaloneSignIn?'app companion signin-shell':'app companion'}><div ref={contentRef} data-app-content>
    <a className="skip-link" href="#main-content">{t('Skip to content')}</a>
    {!standaloneSignIn?<header ref={headerRef} className="companion-header app-header">{!isRoot?<button className="back-button" aria-label={t('Back')} onClick={goBack}><Icon name="chevron-left"/></button>:null}<div className="brand">MediThread</div><LanguageMenu/><button className="notification-shortcut" aria-label={t('Medication reminders')} onClick={()=>setTab('reminder-settings')}><Icon name="bell"/></button><button className="settings-shortcut" aria-label={t('Settings')} onClick={()=>setTab('settings')}><Icon name="settings"/></button></header>:null}
    {preferenceError ? <p role="alert">{preferenceError}</p> : null}
    {fatal ? <ErrorNotice error={fatal} /> : null}
    <main id="main-content" className="app-main">
    {!guideOpen?<NotificationInvitation ownerId={guideOwner} onSettings={()=>setTab('reminder-settings')}/>:null}
    {loading&&!accountPage ? <Card title="Getting your records ready"><p role="status">{t('Starting your private demo session…')}</p></Card> : !medications&&!accountPage ? <Card title="Your records could not be loaded"><p>{t('Please retry the connection. An unavailable record is not an empty medication list.')}</p><button onClick={() => { if (health && sessionId) void refreshMedications(); else window.location.reload(); }}>{t('Retry loading records')}</button></Card> : <>
      {tab === 'check'||tab==='check-result' ? <VisualCheckScreen initialFile={routedPhoto} showResult={tab==='check-result'} onResult={()=>setTab('check-result')} showBack={false} regimenId={visualRegimen} onBack={goBack} onAddSource={()=>setTab('label')}/> : null}
      {tab === 'today' ? <>
        <section className="welcome"><h1 className="greeting">{t(greeting)}{preferences.preferred_language==='zh'?'，':', '}{name}!</h1><p>{t('Your medication and self-care companion')}</p></section>
        {currentMedications.length?<TodayMedicationCarousel medications={currentMedications} focusRegimenId={focusRegimen}>{medication=><TodayScreen key={medication.regimen_id} showTitle={false} focusRegimenId={focusRegimen} onFeeling={()=>{setHealthDescription('');setTab('health-notes');}} onVisualCheck={id=>{setVisualRegimen(id);setTab('check');}} compact medications={[medication]} onChanged={refreshMedications} onMedicines={()=>setTab('medicines')} onHistory={()=>setTab('records')}/>}</TodayMedicationCarousel>:<TodayScreen compact medications={[]} onChanged={refreshMedications} onMedicines={()=>setTab('medicines')} onHistory={()=>setTab('records')} onVisualCheck={()=>{setVisualRegimen(null);setTab('check');}}/>}
      </> : null}
      {tab==='medicines'?<MedicinesHub medications={medications?.medications??[]} drafts={drafts} versions={versions} onOpen={openMedicine}/>:null}
      {tab==='add-method'?<AddMethodScreen onOpen={setTab}/>:null}
      <div data-testid="evidence-workspace" hidden={tab!=='label'}><EvidenceEnrollmentScreen active={tab==='label'} ownerId={guideOwner} onPill={file=>{setRoutedPhoto(file);setVisualRegimen(null);setTab('check');}} onNewRegistration={()=>setEvidenceTaskId(null)} initialTaskId={evidenceTaskId} sessionId={sessionId} onChanged={refreshMedications}/></div>
      <div hidden={tab!=='manual'}><EnrollScreen resumeRegimenId={resumeId} resumeRow={versions.find(row=>row.regimen_id===resumeId)??null} sourceSelection={sourceSelection} sessionId={sessionId} medications={medications} onChanged={refreshMedications}/></div>
      <div data-page="edit-medication" hidden={tab!=='edit-medication'}>{editTarget?<EnrollScreen onActivated={id=>{setDetailId(id);goBack();}} editFrom={editTarget} sessionId={sessionId} medications={medications} onChanged={refreshMedications}/>:tab==='edit-medication'?<Card title="Choose a medication"><button onClick={()=>setTab('medicines')}>{t('Medicines')}</button></Card>:null}</div>
      {tab==='unfinished'?<><PendingEvidenceTasks onContinue={id=>{setEvidenceTaskId(id);setTab('label');}}/><Card title="Finish medication setup">{drafts.length?drafts.map(row=><Entry key={row.regimen_id} title={row.display_name} hint="This medication needs review before its schedule is enabled." onClick={()=>{setResumeId(row.regimen_id);setTab('manual');}}/>):<p>{t('No unfinished medication setup.')}</p>}</Card></>:null}
      {tab==='past-medicines'?<Card title="Past courses">{versions.filter(row=>isPastCourse(row,calendarDate)).map(row=><Entry key={row.regimen_id} title={row.display_name} hint={`${row.course_start_date??t('Not specified')} → ${row.course_end_date??t('Not specified')}`} onClick={()=>openMedicine('medicine-detail',row.regimen_id)}/>)}{!versions.some(row=>isPastCourse(row,calendarDate))?<p>{t('No past courses yet.')}</p>:null}</Card>:null}
      {tab==='medicine-detail'&&!detail?<Card title="Choose a medication"><button onClick={()=>setTab('medicines')}>{t('Medicines')}</button></Card>:null}
      {tab==='medicine-detail'&&detail?<MedicationDetail versions={versions} summary={medications?.medications.find(row=>row.regimen_id===detail.regimen_id)} onAssistant={openAssistant} onChanged={refreshMedications} onEdit={()=>{setEditTarget(detail);setTab('edit-medication');}} row={detail} onHistory={()=>setTab('records')} onGallery={()=>setTab('gallery')} onCheck={()=>{setVisualRegimen(detail.regimen_id);setTab('check');}}/>:null}
      {tab==='gallery'?<PersonalGalleryScreen onSources={id=>{setEvidenceTaskId(id);setTab('label');}} onCheck={id=>{setVisualRegimen(id);setTab('check');}}/>:null}
      {tab==='today'?<CareTaskSummary medications={medications?.medications??[]} onOpen={()=>setTab('care-tasks')}/>:null}
      {tab==='care-tasks'?<CareTasksScreen regimens={versions}/>:null}
      {tab==='adherence-barriers'?<AdherenceBarriersScreen regimens={versions}/>:null}
      {tab==='medication-review'?<MedicationReviewScreen/>:null}
      {tab==='health-notes'?<HealthTrackingScreen initialDescription={healthDescription} medications={medications?.medications??[]}/>:null}
      {tab.startsWith('summary-')?<ReviewSummaryScreen period={tab==='summary-week'?'week':tab==='summary-month'?'month':'course'} regimens={versions}/>:null}
      {tab === 'records' ? <Screen title="Records" lead="Your own reports, and the summaries you can take to a review.">
        <RowGroup title="Medication and health summary">
          <div className="period-actions">{(['week','month','course'] as const).map(period=><button key={period} onClick={()=>setTab(`summary-${period}`)}>{t(period==='week'?'This week':period==='month'?'This month':'This course')}</button>)}</div>
          <Row icon="heart" title="My health notes" hint="How you have been feeling" onClick={()=>setTab('health-notes')}/>
        </RowGroup>
        <RowGroup title="Long-term medication care" hint="For preparing a professional review">
          <Row icon="alert" title="Medication difficulties" onClick={()=>setTab('adherence-barriers')}/>
          <Row icon="calendar" title="Medication follow-ups" onClick={()=>setTab('care-tasks')}/>
          <Row icon="clipboard" title="Medication review preparation" onClick={()=>setTab('medication-review')}/>
        </RowGroup>
        <HistoryScreen />
      </Screen> : null}
      {tab==='me'?<PatientHub onOpen={setTab} onGuide={()=>setTab('help')}/>:null}
      {tab==='help'?<Screen title="Help / User Guide" lead="Learn the buttons and voice settings"><RowGroup><Row icon="info" title="Quick start guide" hint="Seven short steps through the main screens" onClick={openGuide}/></RowGroup></Screen>:null}
      {tab==='account'?<MeScreen standalone={standaloneSignIn} onGuest={()=>setTab('today')} onHelp={()=>setTab('help')} onSettings={()=>setTab('settings')} onFeedback={()=>setTab('feedback')} onIdentityChanged={()=>{window.localStorage.removeItem('pharmascan.agent-session');window.location.reload();}}/>:null}
      {tab==='profile'?<ProfileScreen/>:null}
      {tab==='privacy'||tab==='about'?<InformationScreen kind={tab} onPrivacy={()=>setTab('privacy')} onHistory={()=>setTab('records')}/>:null}
      {tab==='caregivers'?<CaregiversScreen/>:null}
      {tab==='settings'?<Screen title="Settings" lead="Everything you can change about how the app works for you.">
        <RowGroup>
          <Row icon="bell" title="Medication reminders" hint="When the app prompts you, and how it reaches you" onClick={()=>setTab('reminder-settings')}/>
          <Row icon="languages" title="Language and speech" hint="English / 中文, voice and reading aloud" onClick={()=>setTab('language-settings')}/>
          <Row icon="settings" title="Accessibility" hint="Text size and touch targets" onClick={()=>setTab('accessibility')}/>
          <Row icon="info" title="Quick start guide" hint="Seven short steps through the main screens" onClick={openGuide}/>
        </RowGroup>
      </Screen>:null}
      {tab==='reminder-settings'||tab==='language-settings'||tab==='accessibility'?<SettingsScreen section={tab==='reminder-settings'?'reminders':tab==='language-settings'?'language':'accessibility'}/>:null}
      {tab==='feedback'?<FeedbackScreen/>:null}
      <div hidden={!assistantVisible}><AssistantScreen onClose={()=>{setAssistantOpen(false);if(tab==='assistant')goBack();}} contextSlots={assistantSlots} onExpand={openAssistant} active={assistantOpen||tab==='today'||tab==='assistant'} onHealthReview={description=>{setAssistantOpen(false);setHealthDescription(description);setTab('health-notes');}} onVisualCheck={id=>{setAssistantOpen(false);setVisualRegimen(id);setTab('check');}} sessionId={sessionId} onSession={setSessionId} compact={!assistantOpen&&tab!=='assistant'} onChanged={refreshMedications} onPhoto={()=>{setAssistantOpen(false);setTab('label');}}/></div>
    </>}
    </main>
    {!standaloneSignIn?<ReminderMonitor enabled={!loading&&!fatal&&!guideVisible} onReview={id=>{setFocusRegimen(id);setTab('today');}}/>:null}
    {!standaloneSignIn?<nav ref={navRef} className="patient-nav" aria-label="Main navigation">{tabs.map(entry => <button key={entry.id} data-guide={entry.id}
      aria-current={(tab === entry.id || (entry.id==='today'&&['assistant','check','check-result','care-tasks'].includes(tab)) || (entry.id==='me'&&accountPage)||(entry.id==='medicines'&&['add-method','past-medicines','unfinished','gallery','medicine-detail','label','manual','edit-medication'].includes(tab))||(entry.id==='records'&&(tab.startsWith('summary-')||['health-notes','adherence-barriers','medication-review'].includes(tab)))) ? 'page' : undefined} onClick={() => setTab(entry.id)}>
      <Icon name={entry.symbol}/>{t(entry.label)}</button>)}</nav>:null}
    </div>{guideVisible?<OnboardingGuide owner={guideOwner} replay={guideReplay} onClose={closeGuide}/>:null}
  </div>;
}
