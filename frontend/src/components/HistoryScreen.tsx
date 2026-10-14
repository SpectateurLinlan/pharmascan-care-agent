import {useLanguage} from '../language';
import { useEffect, useState } from 'react';
import { api, type DoseHistoryResponse, type RegimenHistoryItem } from '../api/client';
import { Card, ErrorNotice } from './primitives';

export function intakeLabel(value: string | null): string {
  return ({ reported_taken: 'You reported taking this dose', reported_not_taken: 'You reported not taking this dose',
    unsure: 'You were unsure' } as Record<string, string>)[value ?? ''] ?? 'No report — this does not mean a missed dose';
}

export function HistoryScreen() {
  const {t,language}=useLanguage();
  const [regimens, setRegimens] = useState<RegimenHistoryItem[]>([]);
  const [selected, setSelected] = useState('');
  const [history, setHistory] = useState<DoseHistoryResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => { let active = true; void api.regimenHistory().then(rows => {
    if (active) { setRegimens(rows); setSelected(rows[0]?.regimen_id ?? ''); }
  }).catch(caught => { if (active) setError(caught); }); return () => { active = false; }; }, []);
  useEffect(() => { if (!selected) return; let active = true; setLoading(true); setHistory(null);
    void api.doseHistory(selected).then(result => { if (active) { setHistory(result); setError(null); } })
      .catch(caught => { if (active) setError(caught); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; }; }, [selected]);
  return <Card title="My history" hint="Your reports are kept with each medication version. A report is not proof of ingestion.">
    {regimens.length ? <div className="field"><label htmlFor="history-medication">{t('Medication and version')}</label>
      <select id="history-medication" value={selected} onChange={event => setSelected(event.target.value)}>
        {regimens.map(row => <option key={row.regimen_id} value={row.regimen_id}>{row.display_name} · {t('version')} {row.version_no} ·
          {t(row.state === 'active' ? 'current' : row.state === 'ended' || row.state === 'superseded' ? 'previous' : 'awaiting review')}</option>)}
      </select></div> : <p>{t('No medication records yet.')}</p>}
    {loading ? <p role="status">{t('Loading your history…')}</p> : null}
    {error ? <ErrorNotice error={error} /> : null}
    {history ? <ul className="history">{history.entries.map((entry, i) => <li key={i}>
      <span>{entry.due_at || entry.event_time ? new Date(entry.due_at ?? entry.event_time!).toLocaleString(language==='zh'?'zh-CN':'en-SG', { timeZone: 'Asia/Singapore' }) : t('As needed')}</span>
      <span>{t(intakeLabel(entry.intake_status))}</span>
    </li>)}</ul> : null}
  </Card>;
}
