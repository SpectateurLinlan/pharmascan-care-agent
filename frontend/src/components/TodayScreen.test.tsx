// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api, type MedicationSummary, type ReportChallengeResponse } from '../api/client';
import { TodayScreen } from './TodayScreen';

vi.mock('../api/client', () => ({ ApiError: class extends Error {}, api: {
  reminders: vi.fn().mockResolvedValue([]), snoozeReminder: vi.fn(), dueDose: vi.fn(), doseHistory: vi.fn(), requestReportChallenge: vi.fn(), submitReport: vi.fn(),
  requestPrnReportChallenge: vi.fn(), submitPrnReport: vi.fn(),
} }));

afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); vi.mocked(api.reminders).mockResolvedValue([]); });

const medication = {
  medication_id: 'demo-medication', regimen_id: 'demo-regimen', display_name: 'DEMO synthetic medication',
} as MedicationSummary;

const challenge = {
  challenge_id: 'demo-challenge', regimen_id: 'demo-regimen', occurrence_id: 'demo-occurrence',
  summary: { medication_display_name: 'DEMO synthetic medication', dose_amount: 1, dose_unit: 'tablet',
    local_due_time: '2026-10-14 08:00', local_timezone: 'Asia/Singapore',
    intake_status_label: 'You reported taking this dose', safety_notice: 'This does not prove ingestion.' },
  already_recorded: false,
} as ReportChallengeResponse;

describe('dose report consent', () => {
  it('supports as-needed reports without inventing a scheduled occurrence', async () => {
    vi.mocked(api.dueDose).mockResolvedValue({ occurrence_id: null, regimen_id: 'demo-regimen',
      medication_display_name: medication.display_name, dose_description: null, due_at: null,
      is_prn: true, visual_status: 'not_checked', ingestion_proven: false });
    vi.mocked(api.doseHistory).mockResolvedValue({ entries: [], item_count: 0, note: 'demo_only' });
    vi.mocked(api.requestPrnReportChallenge).mockResolvedValue({ ...challenge, occurrence_id: null });
    vi.mocked(api.submitPrnReport).mockResolvedValue({ event_id: 'demo-event', intake_status: 'reported_taken',
      already_recorded: false, visual_status: 'not_checked', ingestion_proven: false, note: 'demo_only' });
    render(<TodayScreen medications={[medication]} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Check what is due now' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Taken' }));
    await screen.findByRole('dialog', { name: 'Confirm your dose report' });
    expect(api.submitPrnReport).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm record' }));
    await waitFor(() => expect(api.submitPrnReport).toHaveBeenCalledOnce());
    expect(api.submitReport).not.toHaveBeenCalled();
  });
  it('shows the summary and requires a separate patient confirmation; cancel never submits', async () => {
    vi.mocked(api.dueDose).mockResolvedValue({ occurrence_id: 'demo-occurrence', regimen_id: 'demo-regimen',
      medication_display_name: medication.display_name, dose_description: null, due_at: '2026-10-14T00:00:00Z',
      is_prn: false, visual_status: 'not_checked', ingestion_proven: false });
    vi.mocked(api.doseHistory).mockResolvedValue({ entries: [], item_count: 0, note: 'demo_only' });
    vi.mocked(api.requestReportChallenge).mockResolvedValue(challenge);
    vi.mocked(api.submitReport).mockResolvedValue({ event_id: 'demo-event', intake_status: 'reported_taken',
      already_recorded: false, visual_status: 'not_checked', ingestion_proven: false, note: 'demo_only' });
    render(<TodayScreen medications={[medication]} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Check what is due now' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Taken' }));
    await screen.findByRole('dialog', { name: 'Confirm your dose report' });
    expect(api.submitReport).not.toHaveBeenCalled();
    expect(screen.getByText('This does not prove ingestion.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(api.submitReport).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }));
    await screen.findByRole('button', { name: 'Confirm record' });
    const sent = vi.mocked(api.requestReportChallenge).mock.calls[1]?.[1];
    if (!sent) throw new Error('Missing synthetic confirmation request');
    expect(sent.idempotency_key).not.toContain(' ');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm record' }));
    await waitFor(() => expect(api.submitReport).toHaveBeenCalledTimes(1));
    expect(api.submitReport).toHaveBeenCalledWith('demo-occurrence', expect.objectContaining({
      challenge_id: 'demo-challenge', intake_status: 'Not now', idempotency_key: sent.idempotency_key,
    }));
  });
});


describe('compact primary medication card', () => {
  it('primary visual action opens the check flow instead of the medicines list',()=>{
    const visual=vi.fn(),medicines=vi.fn();render(<TodayScreen compact medications={[]} onChanged={vi.fn()} onVisualCheck={visual} onMedicines={medicines}/>);
    fireEvent.click(screen.getByRole('button',{name:'Check my medicine'}));expect(visual).toHaveBeenCalledWith(null);expect(medicines).not.toHaveBeenCalled();
  });
  it('refreshes scheduled due and server reminder status while open without any dose write',async()=>{
    vi.useFakeTimers();
    const due={occurrence_id:'demo-occurrence',regimen_id:'demo-regimen',medication_display_name:medication.display_name,dose_description:'1 tablet',due_at:'2026-10-14T00:00:00Z',is_prn:false,visual_status:'not_checked',ingestion_proven:false as const};
    vi.mocked(api.dueDose).mockResolvedValueOnce({...due,occurrence_id:null}).mockResolvedValue(due);
    vi.mocked(api.reminders).mockResolvedValue([{occurrence_id:'demo-occurrence',patient_id:'demo-owner',remind_at:'2026-10-14T00:00:00Z',is_due:true,demo_only:true}]);
    await act(async()=>{render(<TodayScreen compact medications={[medication]} onChanged={vi.fn()}/>);});
    expect(screen.queryByRole('alert')).toBeNull();
    await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});
    expect(screen.getByText(/Your reminder is due/)).toBeTruthy();expect(api.submitReport).not.toHaveBeenCalled();expect(api.requestReportChallenge).not.toHaveBeenCalled();
  });
  it('keeps the empty state and actions inside one primary card', () => {
    const medicines=vi.fn(), history=vi.fn();
    render(<TodayScreen compact medications={[]} onChanged={vi.fn()} onMedicines={medicines} onHistory={history}/>);
    expect(screen.getAllByRole('heading', {level:2})).toHaveLength(1);
    expect(screen.getByText(/No dose due right now/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'My Medicines'})); expect(medicines).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button',{name:'My History'})); expect(history).toHaveBeenCalledOnce();
  });
  it('loads real API status into the primary card without another Today card', async () => {
    vi.mocked(api.dueDose).mockResolvedValue({occurrence_id:'demo-occurrence',regimen_id:'demo-regimen',medication_display_name:medication.display_name,dose_description:'1 tablet',due_at:'2026-10-14T00:00:00Z',is_prn:false,visual_status:'not_checked',ingestion_proven:false});
    render(<TodayScreen compact medications={[medication]} onChanged={vi.fn()}/>);
    await screen.findByText(/1 tablet/); expect(screen.getAllByRole('heading',{level:2})).toHaveLength(1);
    expect(screen.getByRole('button',{name:'Check my medicine'})).toBeTruthy();
  });
});


it('saves an occurrence-bound reminder without notification permission or dose reporting', async () => {
  vi.mocked(api.reminders).mockResolvedValue([]);
  vi.mocked(api.dueDose).mockResolvedValue({occurrence_id:'demo-occurrence',regimen_id:'demo-regimen',medication_display_name:medication.display_name,dose_description:'1 tablet',due_at:'2026-10-14T00:00:00Z',is_prn:false,visual_status:'not_checked',ingestion_proven:false});
  vi.mocked(api.snoozeReminder).mockResolvedValue({occurrence_id:'demo-occurrence',patient_id:'demo-owner',remind_at:'2026-10-14T00:30:00Z',demo_only:true});
  render(<TodayScreen compact medications={[medication]} onChanged={vi.fn()} reminderPort={{kind:'noop',support:()=> 'denied',requestPermission:async()=> 'denied',notify:async()=>false}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Remind me later'})); fireEvent.click(screen.getByRole('button',{name:'15 min later'}));
  await screen.findByText(/Review reminder/); expect(api.snoozeReminder).toHaveBeenCalledWith('demo-occurrence',15);
  expect(api.submitReport).not.toHaveBeenCalled(); expect(api.requestReportChallenge).not.toHaveBeenCalled();
});
