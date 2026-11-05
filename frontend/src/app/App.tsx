/** Composition root: wire identity, navigation and feature screens through public interfaces. */
import { BottomSheet } from '../components/BottomSheet';
import { accountDisplayName } from '../features/account/accountPresentation';
import { Icon, type IconName } from '../components/Icon';
import { LanguageMenu } from '../components/LanguageMenu';
import { NotificationInvitation } from '../features/reminders/NotificationInvitation';
import { LanguageProvider, useLanguage } from './LanguageProvider';
import { useCallback, useEffect, useState, useRef, type ComponentProps } from 'react';
import {
  api,
  type EvidenceTask,
  type HealthResponse,
  type RegimenHistoryItem,
  type SourcePreview,
  type MedicationListResponse,
  type PatientPreferences,
} from '../api/client';
import { medicationSetupEntries } from '../features/enrollment/medicationSetup';
import { AssistantScreen } from '../features/assistant/conversation/AssistantScreen';
import { historyName } from '../features/records/historyFilterLabels';
import {
  MedicinesHub,
  MedicationDetail,
  isPastCourse,
  type MedicineDestination,
} from '../features/medications/MedicinesHub';
import type { MeDestination } from '../features/account/PatientHub';
import { CareTasksScreen, CareTaskSummary } from '../features/care/CareTasksScreen';
import { LateDoseFollowUps } from '../features/care/LateDoseFollowUps';
import { RegimenHistoryScreen } from '../features/medications/RegimenHistoryScreen';
import { InventoryPanel } from '../features/care/InventoryPanel';
import { PendingEvidenceTasks } from '../features/media/PendingEvidenceTasks';
import { Card, ErrorNotice } from '../components/primitives';
import { Screen } from '../components/layout';
import { TodayScreen } from '../features/today/TodayScreen';
import { ReminderMonitor } from '../features/reminders/ReminderMonitor';
import { accountAuth, type Account } from '../api/auth';
import { OnboardingGuide } from '../features/onboarding/OnboardingGuide';
import { TodayAttentionOverview } from '../features/today/TodayAttentionOverview';
import { readTour } from '../features/onboarding/onboarding';
import { useCareNavigation } from './useCareNavigation';
import { greetingAt, greetingName } from './greeting';
import { StartupSection } from './StartupSection';
import { canRenderClinicalToday, canClaimNoRegistrations, type StartupState } from './startupState';

import { deferScreen } from './DeferredScreen';

const EnrollScreen = deferScreen<
  NonNullable<ComponentProps<typeof import('../features/enrollment/EnrollScreen').EnrollScreen>>
>(() =>
  import('../features/enrollment/EnrollScreen').then((module) => ({
    default: module.EnrollScreen,
  })),
);
const HistoryScreen = deferScreen<
  NonNullable<ComponentProps<typeof import('../features/records/HistoryScreen').HistoryScreen>>
>(() =>
  import('../features/records/HistoryScreen').then((module) => ({ default: module.HistoryScreen })),
);
const HealthTrackingScreen = deferScreen<
  NonNullable<
    ComponentProps<typeof import('../features/care/HealthTrackingScreen').HealthTrackingScreen>
  >
>(() =>
  import('../features/care/HealthTrackingScreen').then((module) => ({
    default: module.HealthTrackingScreen,
  })),
);
const ReviewSummaryScreen = deferScreen<
  NonNullable<
    ComponentProps<typeof import('../features/records/ReviewSummaryScreen').ReviewSummaryScreen>
  >
>(() =>
  import('../features/records/ReviewSummaryScreen').then((module) => ({
    default: module.ReviewSummaryScreen,
  })),
);
const RecordsOverview = deferScreen<
  NonNullable<ComponentProps<typeof import('../features/records/RecordsOverview').RecordsOverview>>
>(() =>
  import('../features/records/RecordsOverview').then((module) => ({
    default: module.RecordsOverview,
  })),
);
const AdherenceBarriersScreen = deferScreen<
  NonNullable<
    ComponentProps<
      typeof import('../features/care/AdherenceBarriersScreen').AdherenceBarriersScreen
    >
  >
>(() =>
  import('../features/care/AdherenceBarriersScreen').then((module) => ({
    default: module.AdherenceBarriersScreen,
  })),
);
const MedicationReviewScreen = deferScreen<
  NonNullable<
    ComponentProps<typeof import('../features/care/MedicationReviewScreen').MedicationReviewScreen>
  >
>(() =>
  import('../features/care/MedicationReviewScreen').then((module) => ({
    default: module.MedicationReviewScreen,
  })),
);
const EvidenceEnrollmentScreen = deferScreen<
  NonNullable<
    ComponentProps<
      typeof import('../features/enrollment/EvidenceEnrollmentScreen').EvidenceEnrollmentScreen
    >
  >
>(() =>
  import('../features/enrollment/EvidenceEnrollmentScreen').then((module) => ({
    default: module.EvidenceEnrollmentScreen,
  })),
);
const PersonalGalleryScreen = deferScreen<
  NonNullable<
    ComponentProps<typeof import('../features/media/PersonalGalleryScreen').PersonalGalleryScreen>
  >
>(() =>
  import('../features/media/PersonalGalleryScreen').then((module) => ({
    default: module.PersonalGalleryScreen,
  })),
);
const VisualCheckScreen = deferScreen<
  NonNullable<
    ComponentProps<typeof import('../features/media/VisualCheckScreen').VisualCheckScreen>
  >
>(() =>
  import('../features/media/VisualCheckScreen').then((module) => ({
    default: module.VisualCheckScreen,
  })),
);
const MeScreen = deferScreen<
  NonNullable<ComponentProps<typeof import('../features/account/MeScreen').MeScreen>>
>(() => import('../features/account/MeScreen').then((module) => ({ default: module.MeScreen })));
const SettingsScreen = deferScreen<
  NonNullable<ComponentProps<typeof import('../features/account/SettingsScreen').SettingsScreen>>
>(() =>
  import('../features/account/SettingsScreen').then((module) => ({
    default: module.SettingsScreen,
  })),
);
const FeedbackScreen = deferScreen<
  NonNullable<ComponentProps<typeof import('../features/account/FeedbackScreen').FeedbackScreen>>
>(() =>
  import('../features/account/FeedbackScreen').then((module) => ({
    default: module.FeedbackScreen,
  })),
);
const CaregiversScreen = deferScreen<
  NonNullable<
    ComponentProps<typeof import('../features/account/CaregiversScreen').CaregiversScreen>
  >
>(() =>
  import('../features/account/CaregiversScreen').then((module) => ({
    default: module.CaregiversScreen,
  })),
);
const PatientHub = deferScreen<
  NonNullable<ComponentProps<typeof import('../features/account/PatientHub').PatientHub>>
>(() =>
  import('../features/account/PatientHub').then((module) => ({ default: module.PatientHub })),
);
const ProfileScreen = deferScreen<
  NonNullable<ComponentProps<typeof import('../features/account/PatientHub').ProfileScreen>>
>(() =>
  import('../features/account/PatientHub').then((module) => ({ default: module.ProfileScreen })),
);
const InformationScreen = deferScreen<
  NonNullable<ComponentProps<typeof import('../features/account/PatientHub').InformationScreen>>
>(() =>
  import('../features/account/PatientHub').then((module) => ({
    default: module.InformationScreen,
  })),
);

type Tab =
  | 'check-result'
  | 'check'
  | 'today'
  | 'medicines'
  | 'records'
  | 'medication-records'
  | 'assistant'
  | 'me'
  | 'settings'
  | 'health-notes'
  | 'summary-week'
  | 'summary-month'
  | 'summary-course'
  | MedicineDestination
  | MeDestination
  | 'help'
  | 'edit-medication'
  | 'medicine-history';
type GuideOrigin = {
  route: string;
  query: Record<string, string>;
  routeStack: string[];
  scrollY: number;
};
const tabs: { id: Tab; label: string; symbol: IconName }[] = [
  { id: 'today', label: 'Today', symbol: 'house' },
  { id: 'medicines', label: 'Medicines', symbol: 'pill' },
  { id: 'records', label: 'Records', symbol: 'clipboard' },
  { id: 'me', label: 'Me', symbol: 'user' },
  { id: 'assistant', label: 'AI assistant', symbol: 'message' },
];

export function App() {
  const [identityRevision, setIdentityRevision] = useState(0);
  useEffect(
    () =>
      accountAuth.watchIdentity?.(() => {
        window.localStorage.removeItem('pharmascan.agent-session');
        setIdentityRevision((value) => value + 1);
      }),
    [],
  );
  return (
    <LanguageProvider key={identityRevision}>
      <CompanionApp />
    </LanguageProvider>
  );
}

function CompanionApp() {
  const headerRef = useRef<HTMLElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  useEffect(() => {
    /* Written on the document root: the shell that reserves this space is an
       ancestor of the header and the nav, so a variable set on a sibling would
       never be read and the fallbacks would always win. */
    const update = () => {
      const root = document.documentElement;
      root.style.setProperty(
        '--app-header-height',
        `${headerRef.current?.getBoundingClientRect().height ?? 72}px`,
      );
      root.style.setProperty(
        '--bottom-nav-height',
        `${navRef.current?.getBoundingClientRect().height ?? 72}px`,
      );
    };
    const measure = () => {
      update();
      const rect = mainRef.current?.getBoundingClientRect();
      if (rect) {
        document.documentElement.style.setProperty('--patient-content-left', `${rect.left}px`);
        document.documentElement.style.setProperty('--patient-content-width', `${rect.width}px`);
      }
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    if (headerRef.current) observer?.observe(headerRef.current);
    if (navRef.current) observer?.observe(navRef.current);
    if (mainRef.current) observer?.observe(mainRef.current);
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, []);
  const { t, preferences, loadPreferences, preferenceError } = useLanguage();
  const [evidenceTaskId, setEvidenceTaskId] = useState<string | null>(null);
  const [evidenceVisited, setEvidenceVisited] = useState(false);
  const [conversationClearRevision, setConversationClearRevision] = useState(0);
  const [assistantSlots, setAssistantSlots] = useState<Record<string, unknown>>({});
  const [routedPhoto, setRoutedPhoto] = useState<File | null>(null);
  const [healthDescription, setHealthDescription] = useState('');
  const [visualRegimen, setVisualRegimen] = useState<string | null>(null);
  const [sourceSelection] = useState<{ preview: SourcePreview; name: string } | null>(null);
  const [versions, setVersions] = useState<RegimenHistoryItem[]>([]);
  const [editTarget, setEditTarget] = useState<RegimenHistoryItem | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [galleryMedicationId, setGalleryMedicationId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<RegimenHistoryItem[]>([]);
  const [sourceTasks, setSourceTasks] = useState<EvidenceTask[] | null>(null);
  const [setupError, setSetupError] = useState<unknown>(null);
  const setupRequest = useRef(0);
  const loadSourceTasks = useCallback(async () => {
    const version = ++setupRequest.current;
    try {
      const rows = await api.evidenceTasks();
      if (version === setupRequest.current) {
        setSourceTasks(rows);
        setSetupError(null);
      }
    } catch (caught) {
      if (version === setupRequest.current) {
        setSourceTasks(null);
        setSetupError(caught);
      }
    }
  }, []);
  const [manualDirty, setManualDirty] = useState(false);
  const [profileDirty, setProfileDirty] = useState(false);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [medications, setMedications] = useState<MedicationListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [startup, setStartup] = useState<StartupState>({
    identity: { status: 'loading' },
    preferences: { status: 'loading' },
    active: { status: 'loading' },
    regimens: { status: 'loading' },
    session: { status: 'loading' },
    health: { status: 'loading' },
  });
  const [fatal, setFatal] = useState<unknown>(null);
  const [sessionError, setSessionError] = useState<unknown>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideOwner, setGuideOwner] = useState('');
  const [guideReplay, setGuideReplay] = useState(false);
  const {
    tab,
    navigate: setTab,
    restore: restoreTab,
    back: goBack,
    isRoot,
    pending,
    confirmLeave,
    cancelLeave,
  } = useCareNavigation(false, manualDirty || profileDirty);
  const currentTab = useRef(tab);
  currentTab.current = tab;
  useEffect(() => {
    if (tab === 'label') setEvidenceVisited(true);
  }, [tab]);
  const guideOrigin = useRef<GuideOrigin | null>(null);
  const guideFocus = useRef<HTMLElement | null>(null);
  const [member, setMember] = useState(false);
  const [identity, setIdentity] = useState<Account | null>(null);
  const [now, setNow] = useState(() => new Date());
  /* The signed-out state gets its own surface, so the shell needs to know the
     kind of identity and not only whether an email account is linked. */
  const [accountKind, setAccountKind] = useState<
    'member' | 'guest' | 'signed_out' | 'local' | null
  >(null);
  useEffect(() => {
    void accountAuth
      .account()
      .then((value) => {
        setMember(value.kind === 'member');
        setIdentity(value);
        setAccountKind(value.kind);
      })
      .catch(() => {
        setMember(false);
        setAccountKind(null);
      });
    const tick = () => setNow(new Date());
    const timer = window.setInterval(tick, 60000);
    window.addEventListener('focus', tick);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', tick);
    };
  }, []);
  const [focusRegimen, setFocusRegimen] = useState<string | null>(null);
  const restoreGuideRoute = useCallback(() => {
    const origin = guideOrigin.current;
    if (!origin) return;
    restoreTab(origin.route, origin.query, origin.routeStack);
    requestAnimationFrame(() => window.scrollTo(0, origin.scrollY));
  }, [restoreTab]);
  const closeGuide = useCallback(
    (restoreOrigin = true) => {
      const origin = guideOrigin.current;
      if (restoreOrigin) restoreGuideRoute();
      setGuideOpen(false);
      setGuideReplay(false);
      requestAnimationFrame(() => {
        if (guideFocus.current?.isConnected) guideFocus.current.focus();
        else {
          const root =
            origin && ['today', 'medicines', 'records', 'me'].includes(origin.route)
              ? origin.route
              : 'me';
          document.querySelector<HTMLButtonElement>(`[data-guide="${root}"]`)?.focus();
        }
        guideOrigin.current = null;
        guideFocus.current = null;
      });
    },
    [restoreGuideRoute],
  );
  const startGuide = useCallback((replay: boolean) => {
    const currentRoute = currentTab.current;
    const route = currentRoute && currentRoute !== 'help' ? currentRoute : 'today';
    const [, queryText = ''] = window.location.hash.slice(1).split('?');
    const query = route === currentRoute ? Object.fromEntries(new URLSearchParams(queryText)) : {};
    const storedStack = window.history.state?.careRoute;
    const candidate = Array.isArray(storedStack)
      ? storedStack.filter((value: unknown): value is string => typeof value === 'string')
      : [];
    const routeStack = route === currentRoute && candidate.at(-1) === route ? candidate : [route];
    guideOrigin.current = {
      route,
      query,
      routeStack,
      scrollY: route === currentRoute ? window.scrollY : 0,
    };
    const active = document.activeElement;
    guideFocus.current =
      active instanceof HTMLElement && active !== document.body && active.tabIndex >= 0
        ? active
        : null;
    setGuideReplay(replay);
    setGuideOpen(true);
  }, []);
  const applyPreferences = useCallback(
    (value: PatientPreferences) => {
      setGuideOwner(value.patient_id);
      if (currentTab.current === 'help') startGuide(true);
      else if (readTour(value.patient_id).status === 'in_progress') startGuide(false);
      setStartup((previous) => ({
        ...previous,
        identity: { status: 'ready', data: value.patient_id },
        preferences: { status: 'ready', data: value },
      }));
    },
    [startGuide],
  );
  useEffect(() => {
    if (['today', 'medicines', 'records', 'me'].includes(tab)) setEvidenceTaskId(null);
  }, [tab]);
  const openGuide = useCallback(() => startGuide(true), [startGuide]);
  const refreshMedications = useCallback(async () => {
    void api
      .regimenHistory()
      .then((rows) => {
        setVersions(rows);
        setDrafts(
          rows.filter((row) => row.state === 'draft' || row.state === 'pending_clarification'),
        );
        setStartup((previous) => ({ ...previous, regimens: { status: 'ready', data: rows } }));
      })
      .catch((error) => {
        setStartup((previous) => ({ ...previous, regimens: { status: 'error', error } }));
      });
    void loadSourceTasks();
    const core = await Promise.allSettled([
      api
        .listMedications()
        .then((active) => {
          setMedications(active);
          setStartup((previous) => ({ ...previous, active: { status: 'ready', data: active } }));
        })
        .catch((error) => {
          setStartup((previous) => ({ ...previous, active: { status: 'error', error } }));
          throw error;
        }),
      startup.preferences.status === 'ready'
        ? Promise.resolve()
        : loadPreferences()
            .then((value) => {
              if (!value) throw new Error('Patient preferences unavailable');
              applyPreferences(value);
            })
            .catch((error) => {
              setStartup((previous) => ({ ...previous, preferences: { status: 'error', error } }));
              throw error;
            }),
    ]);
    const failure = core.find((result) => result.status === 'rejected');
    setFatal(failure?.status === 'rejected' ? failure.reason : null);
  }, [loadSourceTasks, loadPreferences, startup.preferences.status, applyPreferences]);
  const bootstrap = useRef<Promise<HealthResponse> | null>(null);
  useEffect(() => {
    let live = true;
    if (!bootstrap.current) bootstrap.current = api.health();
    void bootstrap.current
      .then(async (state) => {
        if (!live) return;
        if (state.runtime_contract !== 'patient-ux-reminders-v1')
          throw new Error(
            'The app connection needs a restart. Please restart the development servers.',
          );
        // Each request resolves its own verified identity. Agent setup does not
        // supply credentials to medication reads, so it can run alongside them.
        // Evidence tasks retain their own loading/error state outside this gate.
        void loadSourceTasks();
        setHealth(state);
        setStartup((previous) => ({ ...previous, health: { status: 'ready', data: state } }));
        void api
          .startDemo()
          .then((value) => {
            if (!live) return;
            localStorage.setItem('pharmascan.agent-session', value.session_id);
            setSessionId(value.session_id);
            setSessionError(null);
            setStartup((previous) => ({ ...previous, session: { status: 'ready', data: value } }));
          })
          .catch((error) => {
            if (live) {
              setSessionError(error);
              setStartup((previous) => ({ ...previous, session: { status: 'error', error } }));
            }
          });
        void api
          .regimenHistory()
          .then((rows) => {
            if (!live) return;
            setVersions(rows);
            setDrafts(
              rows.filter((row) => row.state === 'draft' || row.state === 'pending_clarification'),
            );
            setStartup((previous) => ({ ...previous, regimens: { status: 'ready', data: rows } }));
          })
          .catch((error) => {
            if (live)
              setStartup((previous) => ({ ...previous, regimens: { status: 'error', error } }));
          });
        const [active] = await Promise.all([
          api
            .listMedications()
            .then((value) => {
              if (live)
                setStartup((previous) => ({
                  ...previous,
                  active: { status: 'ready', data: value },
                }));
              return value;
            })
            .catch((error) => {
              if (live)
                setStartup((previous) => ({ ...previous, active: { status: 'error', error } }));
              throw error;
            }),
          loadPreferences()
            .then((value) => {
              if (!value) throw new Error('Patient preferences unavailable');
              if (live) applyPreferences(value);
            })
            .catch((error) => {
              if (live)
                setStartup((previous) => ({
                  ...previous,
                  preferences: { status: 'error', error },
                }));
              throw error;
            }),
        ]);
        if (live) {
          setMedications(active);
          setFatal(null);
        }
      })
      .catch((error) => {
        bootstrap.current = null;
        if (live) {
          setFatal(error);
          setStartup((previous) => ({
            ...previous,
            health:
              previous.health.status === 'ready' ? previous.health : { status: 'error', error },
          }));
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [loadPreferences, loadSourceTasks, applyPreferences]);
  const historyReady = startup.regimens.status === 'ready';
  const historyPage =
    [
      'medicines',
      'unfinished',
      'past-medicines',
      'medicine-detail',
      'edit-medication',
      'medicine-history',
      'medication-inventory',
      'care-tasks',
      'adherence-barriers',
      'summary-week',
      'summary-month',
      'summary-course',
    ].includes(tab) ||
    (tab === 'manual' && resumeId !== null);
  const visibleTab = historyPage && !historyReady ? 'loading-history' : tab;
  const setupEntries =
    sourceTasks === null || !historyReady ? null : medicationSetupEntries(sourceTasks, versions);

  const greeting = greetingAt(now, preferences.timezone);
  const name = greetingName(
    member,
    accountDisplayName(identity, preferences.display_name, t('Guest')),
    t('Guest'),
  );
  const accountPage = [
    'me',
    'settings',
    'feedback',
    'profile',
    'account',
    'caregivers',
    'reminder-settings',
    'language-settings',
    'accessibility',
    'privacy',
    'conversations',
    'about',
    'help',
  ].includes(tab);
  /** One Assistant instance keeps message and draft state across route changes. */
  /* A signed-out account page is a standalone sign-in surface: it is a decision
     about identity, so it renders without the tabs, the rail or the composer. */
  const standaloneSignIn = accountKind === 'signed_out' && tab === 'account';
  const assistantVisible = !standaloneSignIn && (tab === 'today' || tab === 'assistant');
  const openMedicine = (page: MedicineDestination, id?: string) => {
    if (page === 'manual') {
      setResumeId(null);
    }
    if (page === 'gallery') setGalleryMedicationId(null);
    if (id) setDetailId(id);
    setTab(page);
  };
  const detail = versions.find((row) => row.regimen_id === detailId);
  const openAssistant = (contextual = true) => {
    setAssistantSlots(
      contextual && ['medicine-detail', 'medicines', 'records'].includes(tab)
        ? {
            source_page: tab,
            ...(tab === 'medicine-detail' && detail
              ? { regimen_id: detail.regimen_id, medication_id: detail.medication_id }
              : {}),
            navigation_nonce: crypto.randomUUID(),
          }
        : {},
    );
    setTab('assistant');
  };
  const navigateGuide = useCallback(
    (route: string) => {
      if (route === 'assistant') {
        setAssistantSlots({});
        setTab('assistant', undefined, { replace: true });
      } else setTab(route as Tab, undefined, { replace: true });
    },
    [setTab],
  );
  const viewTodayMedication = () => {
    setTab('today');
    requestAnimationFrame(() =>
      requestAnimationFrame(() =>
        document
          .getElementById('today-medication')
          ?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      ),
    );
  };
  const calendarDate = new Intl.DateTimeFormat('en-CA', {
    timeZone: preferences.timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
  const currentMedications =
    medications?.medications.filter((row) => !isPastCourse(row, calendarDate)) ?? [];
  const guideVisible = guideOpen && !loading && !fatal && Boolean(medications);
  return (
    <div className={standaloneSignIn ? 'app companion signin-shell' : 'app companion'}>
      <div data-app-content>
        <a className="skip-link" href="#main-content">
          {t('Skip to content')}
        </a>
        {!standaloneSignIn ? (
          <header ref={headerRef} className="companion-header app-header">
            {!isRoot && tab !== 'assistant' ? (
              <button className="back-button" aria-label={t('Back')} onClick={goBack}>
                <Icon name="chevron-left" />
              </button>
            ) : null}
            <div className="brand">
              <img
                className="brand-mark"
                src="/branding/medithread-192.png"
                width="28"
                height="28"
                alt=""
              />
              <span>MediThread</span>
            </div>
            {tab !== 'assistant' ? (
              <button
                type="button"
                className="assistant-header-shortcut"
                aria-label={t('AI assistant')}
                onClick={() => openAssistant()}
              >
                <img src="/branding/assistant-avatar-green.png" width="28" height="28" alt="" />
                <span>{t('AI assistant')}</span>
              </button>
            ) : null}
            <div className="header-quick-actions" data-guide="header-quick-actions">
              <LanguageMenu />
              <button
                className="notification-shortcut"
                aria-label={t('Medication reminders')}
                onClick={() => setTab('reminder-settings')}
              >
                <Icon name="bell" />
              </button>
              <button
                className="settings-shortcut"
                aria-label={t('Settings')}
                onClick={() => setTab('settings')}
              >
                <Icon name="settings" />
              </button>
            </div>
          </header>
        ) : null}
        {preferenceError ? <p role="alert">{preferenceError}</p> : null}
        {pending ? (
          <BottomSheet title={t('Leave without saving?')} onCancel={cancelLeave}>
            <p>
              {t(
                profileDirty && !manualDirty
                  ? 'Leaving will discard your unsaved profile name.'
                  : 'Leaving clears the unsaved details on this page. Saved registrations can be managed in Finish medication setup.',
              )}
            </p>
            <button
              className="danger"
              onClick={() => {
                setManualDirty(false);
                setProfileDirty(false);
                setResumeId(null);
                confirmLeave();
              }}
            >
              {t('Leave and clear')}
            </button>
            <button onClick={cancelLeave}>{t('Keep editing')}</button>
          </BottomSheet>
        ) : null}
        {fatal ? <ErrorNotice error={fatal} /> : null}
        {sessionError ? <ErrorNotice error={sessionError} /> : null}
        <main
          ref={mainRef}
          id="main-content"
          className="app-main"
          data-load-state={
            loading
              ? 'loading'
              : fatal
                ? 'error'
                : canRenderClinicalToday(startup)
                  ? 'ready'
                  : 'unavailable'
          }
        >
          {tab === 'today' ? (
            <section className="welcome">
              <h1 className="greeting">
                {loading || fatal || !canRenderClinicalToday(startup) ? (
                  t('Welcome to MediThread')
                ) : (
                  <>
                    {t(greeting)}
                    {preferences.preferred_language === 'zh' ? '，' : ', '}
                    {name}!
                  </>
                )}
              </h1>
              <p>{t('Your medication and self-care companion')}</p>
            </section>
          ) : null}
          {!guideOpen ? (
            <NotificationInvitation
              ownerId={guideOwner}
              onSettings={() => setTab('reminder-settings')}
            />
          ) : null}
          {(loading || (!canRenderClinicalToday(startup) && !fatal)) && !accountPage ? (
            <Card title="Getting your records ready">
              <p role="status">{t('Starting your private demo session…')}</p>
            </Card>
          ) : !canRenderClinicalToday(startup) && !accountPage ? (
            <Card title="Your records could not be loaded">
              <p>
                {t(
                  'Please retry the connection. An unavailable record is not an empty medication list.',
                )}
              </p>
              <button
                onClick={() => {
                  if (health && sessionId) void refreshMedications();
                  else window.location.reload();
                }}
              >
                {t('Retry loading records')}
              </button>
            </Card>
          ) : (
            <>
              <div hidden={!assistantVisible}>
                {sessionId ? (
                  <AssistantScreen
                    onConversationCleared={() => setConversationClearRevision((value) => value + 1)}
                    onGuide={openGuide}
                    onSupportNavigate={(route, query) => {
                      const id = query.id;
                      if (route === 'gallery') setGalleryMedicationId(id ?? null);
                      if (route === 'check') setVisualRegimen(id ?? null);
                      if (
                        id &&
                        [
                          'medicine-detail',
                          'medicine-history',
                          'edit-medication',
                          'medication-inventory',
                        ].includes(route)
                      ) {
                        const row =
                          route === 'medication-inventory'
                            ? versions.find((item) => item.medication_id === id)
                            : versions.find((item) => item.regimen_id === id);
                        if (!row) return;
                        setDetailId(row.regimen_id);
                        if (route === 'edit-medication') setEditTarget(row);
                      }
                      setTab(route, query, { preserveOrigin: true });
                    }}
                    onSourceReturn={(source) => {
                      if (source.page === 'medicine-detail' && source.regimen_id) {
                        setDetailId(source.regimen_id);
                        setTab('medicine-detail');
                      } else if (source.page !== 'medicine-detail') setTab(source.page);
                    }}
                    workspace={tab === 'assistant'}
                    ownerId={guideOwner}
                    clearRevision={conversationClearRevision}
                    onClose={goBack}
                    contextSlots={assistantSlots}
                    onExpand={openAssistant}
                    onViewTodayMedication={viewTodayMedication}
                    active={tab === 'today' || tab === 'assistant'}
                    onHealthReview={(description) => {
                      setHealthDescription(description);
                      setTab('health-notes');
                    }}
                    onVisualCheck={(id) => {
                      setVisualRegimen(id);
                      setTab('check');
                    }}
                    sessionId={sessionId}
                    onSession={setSessionId}
                    todayEntry={tab === 'today'}
                    compact={tab !== 'assistant'}
                    onChanged={refreshMedications}
                  />
                ) : assistantVisible ? (
                  <p role="status">{t('Starting your private demo session\u2026')}</p>
                ) : null}
              </div>
              {historyPage && !historyReady ? (
                <StartupSection state={startup.regimens} onRetry={refreshMedications} />
              ) : null}
              {visibleTab === 'check' || visibleTab === 'check-result' ? (
                <VisualCheckScreen
                  ownerId={guideOwner}
                  initialFile={routedPhoto}
                  showResult={visibleTab === 'check-result'}
                  onResult={() => setTab('check-result')}
                  showBack={false}
                  regimenId={visualRegimen}
                  onBack={goBack}
                  onAddSource={() => setTab('label')}
                />
              ) : null}
              {visibleTab === 'today' ? (
                <>
                  <div className="today-panels">
                    <div id="today-medication" className="today-medication-anchor">
                      {currentMedications.length ? (
                        <TodayAttentionOverview
                          lateReportsEnabled={health?.late_dose_reports_enabled === true}
                          medications={currentMedications}
                          focusRegimenId={focusRegimen}
                          onHistory={() => setTab('records', undefined, { preserveOrigin: true })}
                        >
                          {(medication, onInteractionChange, todayOccurrenceIds) => (
                            <TodayScreen
                              onInteractionChange={onInteractionChange}
                              hideDoseOccurrenceIds={todayOccurrenceIds}
                              key={medication.regimen_id}
                              showTitle={false}
                              focusRegimenId={focusRegimen}
                              onFeeling={() => {
                                setHealthDescription('');
                                setTab('health-notes');
                              }}
                              onVisualCheck={(id) => {
                                setVisualRegimen(id);
                                setTab('check');
                              }}
                              compact
                              medications={[medication]}
                              onChanged={refreshMedications}
                              onMedicines={() =>
                                setTab('medicines', undefined, { preserveOrigin: true })
                              }
                              onReviewPlan={() => setTab('unfinished')}
                              setupCount={setupEntries?.length ?? 0}
                              hasMedicationRecords={!canClaimNoRegistrations(startup)}
                            />
                          )}
                        </TodayAttentionOverview>
                      ) : (
                        <StartupSection state={startup.regimens} onRetry={refreshMedications}>
                          <TodayScreen
                            compact
                            medications={[]}
                            onChanged={refreshMedications}
                            onMedicines={() =>
                              setTab('medicines', undefined, { preserveOrigin: true })
                            }
                            onReviewPlan={() => setTab('unfinished')}
                            setupCount={setupEntries?.length ?? 0}
                            hasMedicationRecords={!canClaimNoRegistrations(startup)}
                            onVisualCheck={() => {
                              setVisualRegimen(null);
                              setTab('check');
                            }}
                          />
                        </StartupSection>
                      )}
                    </div>
                    {!currentMedications.length ? (
                      <section className="card today-confirmation-card">
                        <LateDoseFollowUps
                          enabled={health?.late_dose_reports_enabled === true}
                          todayOnly
                          onHistory={() => setTab('records', undefined, { preserveOrigin: true })}
                        />
                      </section>
                    ) : null}
                    <StartupSection state={startup.regimens} onRetry={refreshMedications}>
                      <CareTaskSummary
                        medications={medications?.medications ?? []}
                        regimens={versions}
                        extended={health?.care_task_followups_enabled === true}
                        multiple={health?.multiple_care_reminders_enabled === true}
                        onOpen={(taskId) =>
                          setTab('care-tasks', taskId ? { task: taskId } : undefined)
                        }
                      />
                    </StartupSection>
                  </div>
                </>
              ) : null}
              {visibleTab === 'medicines' ? (
                <MedicinesHub
                  medications={medications?.medications ?? []}
                  drafts={drafts}
                  setupCount={setupEntries?.length ?? null}
                  versions={versions}
                  onOpen={openMedicine}
                />
              ) : null}
              {evidenceVisited || tab === 'label' ? (
                <div data-testid="evidence-workspace" hidden={visibleTab !== 'label'}>
                  <EvidenceEnrollmentScreen
                    active={visibleTab === 'label'}
                    ownerId={guideOwner}
                    onPill={(file) => {
                      setRoutedPhoto(file);
                      setVisualRegimen(null);
                      setTab('check');
                    }}
                    onNewRegistration={() => setEvidenceTaskId(null)}
                    onCancel={() => {
                      void refreshMedications();
                      setTab('unfinished');
                    }}
                    initialTaskId={evidenceTaskId}
                    sessionId={sessionId}
                    onChanged={refreshMedications}
                  />
                </div>
              ) : null}
              {visibleTab === 'manual' ? (
                <div>
                  <EnrollScreen
                    onDirtyChange={setManualDirty}
                    resumeRegimenId={resumeId}
                    resumeRow={versions.find((row) => row.regimen_id === resumeId) ?? null}
                    sourceSelection={sourceSelection}
                    sessionId={sessionId}
                    medications={medications}
                    onChanged={refreshMedications}
                  />
                </div>
              ) : null}
              <div data-page="edit-medication" hidden={visibleTab !== 'edit-medication'}>
                {editTarget ? (
                  <EnrollScreen
                    onActivated={(id) => {
                      setDetailId(id);
                      goBack();
                    }}
                    editFrom={editTarget}
                    sessionId={sessionId}
                    medications={medications}
                    onChanged={refreshMedications}
                  />
                ) : visibleTab === 'edit-medication' ? (
                  <Card title="Choose a medication">
                    <button onClick={() => setTab('medicines')}>{t('Medicines')}</button>
                  </Card>
                ) : null}
              </div>
              {visibleTab === 'unfinished' ? (
                <PendingEvidenceTasks
                  entries={setupEntries}
                  error={setupError}
                  onRetry={() => void refreshMedications()}
                  onContinue={(id) => {
                    setEvidenceTaskId(id);
                    setTab('label');
                  }}
                  onResume={(id) => {
                    setResumeId(id);
                    setTab('manual');
                  }}
                />
              ) : null}
              <RegimenHistoryScreen
                regimens={versions}
                active={visibleTab === 'past-medicines'}
                onOpen={(id) => openMedicine('medicine-detail', id)}
              />
              {visibleTab === 'medicine-detail' && !detail ? (
                <Card title="Choose a medication">
                  <button onClick={() => setTab('medicines')}>{t('Medicines')}</button>
                </Card>
              ) : null}
              {visibleTab === 'medicine-detail' && detail ? (
                <MedicationDetail
                  versions={versions}
                  summary={medications?.medications.find(
                    (row) => row.regimen_id === detail.regimen_id,
                  )}
                  onChanged={refreshMedications}
                  onEdit={() => {
                    setEditTarget(detail);
                    setTab('edit-medication');
                  }}
                  row={detail}
                  onManageInventory={() => setTab('medication-inventory')}
                  onHistory={() => setTab('medicine-history')}
                  onGallery={() => {
                    setGalleryMedicationId(detail.medication_id);
                    setTab('gallery');
                  }}
                  onCheck={() => {
                    setVisualRegimen(detail.regimen_id);
                    setTab('check');
                  }}
                />
              ) : null}
              {visibleTab === 'medication-inventory' && detail ? (
                <Screen title="Inventory management" lead={detail.display_name}>
                  <InventoryPanel
                    key={detail.medication_id}
                    medicationId={detail.medication_id}
                    mode="manage"
                  />
                </Screen>
              ) : null}
              {visibleTab === 'medicine-history' && detail ? (
                <Screen title="Medication history" lead={detail.display_name}>
                  <HistoryScreen
                    key={detail.regimen_id}
                    scopedTitle={`${t(detail.display_name)} · ${t('Medication history')}`}
                    initialFilters={{
                      range_kind: '7',
                      medication_id: detail.medication_id,
                      medication_name: historyName(detail.display_name),
                      regimen_id: detail.regimen_id,
                    }}
                  />
                </Screen>
              ) : null}
              {visibleTab === 'gallery' ? (
                <PersonalGalleryScreen
                  initialMedicationId={galleryMedicationId}
                  onMedicationSelected={setGalleryMedicationId}
                  onSources={(id) => {
                    setEvidenceTaskId(id);
                    setTab('label');
                  }}
                  onMedicationDetail={(id) => {
                    const related = versions.filter((row) => row.medication_id === id);
                    const chosen = related.find((row) => row.state === 'active') ?? related[0];
                    if (chosen) openMedicine('medicine-detail', chosen.regimen_id);
                  }}
                />
              ) : null}
              {visibleTab === 'care-tasks' ? (
                <CareTasksScreen
                  multiple={health?.multiple_care_reminders_enabled === true}
                  extended={health?.care_task_followups_enabled === true}
                  regimens={versions}
                />
              ) : null}
              {visibleTab === 'adherence-barriers' ? (
                <AdherenceBarriersScreen regimens={versions} />
              ) : null}
              {visibleTab === 'medication-review' ? <MedicationReviewScreen /> : null}
              {visibleTab === 'health-notes' ? (
                <HealthTrackingScreen
                  initialDescription={healthDescription}
                  medications={medications?.medications ?? []}
                />
              ) : null}
              {visibleTab.startsWith('summary-') ? (
                <ReviewSummaryScreen
                  period={
                    visibleTab === 'summary-week'
                      ? 'week'
                      : visibleTab === 'summary-month'
                        ? 'month'
                        : 'course'
                  }
                  regimens={versions}
                />
              ) : null}
              {visibleTab === 'medication-records' ? (
                <Screen
                  title="My medication records"
                  lead="View saved dose reports and past scheduled doses by medicine and date."
                  className="records-detail"
                >
                  <HistoryScreen />
                </Screen>
              ) : null}
              {visibleTab === 'records' ? (
                <Screen
                  title="Records"
                  lead="Your own reports, and the summaries you can take to a review."
                  className="records-screen"
                >
                  <RecordsOverview
                    lateReportsEnabled={health?.late_dose_reports_enabled === true}
                    onOpenSummary={(period) => setTab(`summary-${period}`)}
                    onOpenMedicationRecords={() => setTab('medication-records')}
                    onOpenArea={(area) => setTab(area)}
                  />
                </Screen>
              ) : null}
              {visibleTab === 'me' ? <PatientHub onOpen={setTab} onGuide={openGuide} /> : null}
              {visibleTab === 'account' ? (
                <MeScreen
                  standalone={standaloneSignIn}
                  onGuest={() => setTab('today')}
                  onHelp={() => setTab('help')}
                  onSettings={() => setTab('settings')}
                  onFeedback={() => setTab('feedback')}
                  onIdentityChanged={() => {
                    window.localStorage.removeItem('pharmascan.agent-session');
                    window.location.reload();
                  }}
                />
              ) : null}
              {visibleTab === 'profile' && accountKind === 'guest' ? (
                <MeScreen onIdentityChanged={() => window.location.reload()} />
              ) : visibleTab === 'profile' ? (
                <Screen title="Personal Profile & Account" className="profile-screen">
                  <ProfileScreen
                    onDirtyChange={setProfileDirty}
                    onIdentityChanged={() => window.location.reload()}
                  />
                </Screen>
              ) : null}
              {visibleTab === 'privacy' ||
              visibleTab === 'conversations' ||
              visibleTab === 'about' ? (
                <InformationScreen
                  ownerId={guideOwner}
                  kind={visibleTab}
                  onConversationCleared={() => setConversationClearRevision((value) => value + 1)}
                  onPrivacy={() => setTab('privacy')}
                  onFeedback={() => setTab('feedback')}
                  onGallery={() => setTab('gallery')}
                />
              ) : null}
              {visibleTab === 'caregivers' ? <CaregiversScreen /> : null}
              {visibleTab === 'settings' ? <SettingsScreen /> : null}
              {visibleTab === 'reminder-settings' ||
              visibleTab === 'language-settings' ||
              visibleTab === 'accessibility' ? (
                <SettingsScreen
                  section={
                    visibleTab === 'reminder-settings'
                      ? 'reminders'
                      : visibleTab === 'language-settings'
                        ? 'language'
                        : 'accessibility'
                  }
                  onOpenCareTask={(taskId) => setTab('care-tasks', { task: taskId })}
                  multipleCareRemindersEnabled={health?.multiple_care_reminders_enabled === true}
                />
              ) : null}
              {visibleTab === 'feedback' ? <FeedbackScreen /> : null}
            </>
          )}
        </main>
        {!standaloneSignIn ? (
          <ReminderMonitor
            enabled={canRenderClinicalToday(startup) && !loading && !fatal && !guideVisible}
            onReview={(id) => {
              setFocusRegimen(id);
              setTab('today');
            }}
          />
        ) : null}
        {!standaloneSignIn ? (
          <nav ref={navRef} className="patient-nav" aria-label="Main navigation">
            {tabs.map((entry) => (
              <button
                key={entry.id}
                data-guide={entry.id}
                className={entry.id === 'assistant' ? 'nav-assistant' : ''}
                aria-current={
                  tab === entry.id ||
                  (entry.id === 'today' && ['check', 'check-result', 'care-tasks'].includes(tab)) ||
                  (entry.id === 'me' && accountPage) ||
                  (entry.id === 'medicines' &&
                    [
                      'past-medicines',
                      'unfinished',
                      'gallery',
                      'medicine-detail',
                      'medicine-history',
                      'medication-inventory',
                      'label',
                      'manual',
                      'edit-medication',
                    ].includes(tab)) ||
                  (entry.id === 'records' &&
                    (tab === 'medication-records' ||
                      tab.startsWith('summary-') ||
                      ['health-notes', 'adherence-barriers', 'medication-review'].includes(tab)))
                    ? 'page'
                    : undefined
                }
                onClick={() => (entry.id === 'assistant' ? openAssistant(false) : setTab(entry.id))}
              >
                {entry.id === 'assistant' ? (
                  <img
                    className="nav-assistant__avatar"
                    src="/branding/assistant-avatar-green.png"
                    width="28"
                    height="28"
                    alt=""
                  />
                ) : (
                  <Icon name={entry.symbol} />
                )}
                <span>{t(entry.label)}</span>
              </button>
            ))}
          </nav>
        ) : null}
      </div>
      {guideVisible ? (
        <OnboardingGuide
          owner={guideOwner}
          replay={guideReplay}
          guest={accountKind === 'guest'}
          activeRoute={tab}
          originRoute={guideOrigin.current?.route ?? 'today'}
          onNavigate={navigateGuide}
          onRestore={restoreGuideRoute}
          onClose={closeGuide}
        />
      ) : null}
    </div>
  );
}
