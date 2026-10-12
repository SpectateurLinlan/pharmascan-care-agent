/**
 * PharmaScan Care — single-patient demo UI.
 *
 * Scope note (Gate 4): this is the minimum UI. It connects to the real
 * FastAPI backend and shows real responses or real refusals — it never
 * fabricates a success. Screens that are not finished are explicitly labelled.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  api,
  type HealthResponse,
  type MedicationListResponse,
} from './api/client';
import { AssistantScreen } from './components/AssistantScreen';
import { EnrollScreen } from './components/EnrollScreen';
import { MedicationList } from './components/MedicationList';
import { Card, ErrorNotice, SimulatedNotice, Tag } from './components/primitives';
import { TodayScreen } from './components/TodayScreen';
import { NotBuiltYetScreen } from './components/NotBuiltYetScreen';

type Tab = 'today' | 'medications' | 'assistant' | 'settings';

const TABS: { id: Tab; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'medications', label: 'Medications' },
  { id: 'assistant', label: 'Assistant' },
  { id: 'settings', label: 'Settings' },
];

export function App() {
  const [tab, setTab] = useState<Tab>('today');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [patientId, setPatientId] = useState<string | null>(null);
  const [medications, setMedications] = useState<MedicationListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [fatal, setFatal] = useState<unknown>(null);

  const refreshMedications = useCallback(async () => {
    try {
      setMedications(await api.listMedications());
      setFatal(null);
    } catch (caught) {
      setFatal(caught);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [healthResponse, demo] = await Promise.all([api.health(), api.startDemo()]);
        if (cancelled) return;
        setHealth(healthResponse);
        setSessionId(demo.session_id);
        setPatientId(demo.patient_id);
        await refreshMedications();
      } catch (caught) {
        if (!cancelled) setFatal(caught);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshMedications]);

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">PharmaScan Care</h1>
        <p className="app__subtitle">
          Medication record and dose check — single patient demo
        </p>
      </header>

      <SimulatedNotice>
        <p style={{ margin: '0.2rem 0 0' }}>
          Data is stored in memory and disappears when the backend restarts.{' '}
          <Tag>storage: {health?.database ?? 'unknown'}</Tag>{' '}
          <Tag>vision: {health?.stage2_vision ?? 'unknown'}</Tag>{' '}
          <Tag>assistant: {health?.llm ?? 'unknown'}</Tag>
        </p>
        <p style={{ margin: '0.35rem 0 0' }}>
          This is not a medical device and gives no medical advice. It does not
          diagnose, and it never claims that a photo proves which pill you took.
        </p>
      </SimulatedNotice>

      {fatal ? <ErrorNotice error={fatal} /> : null}

      {loading ? (
        <Card title="Starting demo session">
          <p className="notice">Contacting the backend…</p>
        </Card>
      ) : (
        <>
          <nav className="actions" aria-label="Sections">
            {TABS.map((entry) => (
              <button
                key={entry.id}
                className={entry.id === tab ? 'choice primary' : 'choice'}
                aria-pressed={entry.id === tab}
                onClick={() => setTab(entry.id)}
              >
                {entry.label}
              </button>
            ))}
          </nav>

          {tab === 'today' ? (
            <TodayScreen
              medications={medications?.medications ?? []}
              onChanged={refreshMedications}
            />
          ) : null}

          {tab === 'medications' ? (
            <>
              <MedicationList medications={medications} loading={loading} />
              <EnrollScreen
                sessionId={sessionId}
                medications={medications}
                onChanged={refreshMedications}
              />
            </>
          ) : null}

          {tab === 'assistant' ? (
            <AssistantScreen sessionId={sessionId} onSession={setSessionId} />
          ) : null}

          {tab === 'settings' ? <NotBuiltYetScreen /> : null}
        </>
      )}

      <footer className="app__header">
        <p className="notice">
          Demo patient id: <code>{patientId ?? 'not started'}</code>
        </p>
      </footer>
    </div>
  );
}
