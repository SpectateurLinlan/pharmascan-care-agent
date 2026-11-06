// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EnrollScreen, courseDuration, courseEndForDuration } from './EnrollScreen';
import { AutoDismissNotice } from '../../components/primitives';
import { api, type RegimenHistoryItem } from '../../api/client';

const savedDraft = {
  medication_id: 'DEMO-med',
  regimen_id: 'DEMO-draft',
  source_id: 'DEMO-source',
  state: 'draft',
  missing_instructions: [],
  reviewable_field_ids: [],
  note: 'DEMO_ONLY',
};

function enterReviewedMedication() {
  fireEvent.change(screen.getByLabelText('Medication name'), { target: { value: 'DEMO course' } });
  fireEvent.change(screen.getByLabelText('Dose amount'), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review and add' }));
  fireEvent.click(
    screen.getByLabelText('I have checked these details against my original instructions.'),
  );
}

it('retries source review on the saved draft instead of creating another course', async () => {
  const create = vi.spyOn(api, 'createDraft').mockResolvedValue(savedDraft);
  vi.spyOn(api, 'resumeDraft').mockResolvedValue(savedDraft);
  const review = vi
    .spyOn(api, 'reviewDraft')
    .mockRejectedValueOnce(new Error('DEMO review unavailable'))
    .mockResolvedValue({ source_id: 'DEMO-source', reviewed_field_count: 2, note: 'DEMO_ONLY' });
  const challenge = vi
    .spyOn(api, 'requestChallenge')
    .mockRejectedValue(new Error('DEMO stop before confirmation'));
  render(<EnrollScreen sessionId="DEMO-session" medications={null} onChanged={vi.fn()} />);
  enterReviewedMedication();
  fireEvent.click(screen.getByRole('button', { name: 'Add this medication' }));
  await waitFor(() => expect(review).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Add this medication' })).toHaveProperty(
      'disabled',
      false,
    ),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Add this medication' }));
  await waitFor(() => expect(challenge).toHaveBeenCalledOnce());
  expect(create).toHaveBeenCalledOnce();
  expect(review).toHaveBeenLastCalledWith('DEMO-source');
});

it('accepts only one concurrent save attempt even before React updates the disabled button', async () => {
  let finish!: (draft: typeof savedDraft) => void;
  const create = vi.spyOn(api, 'createDraft').mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  vi.spyOn(api, 'reviewDraft').mockRejectedValue(new Error('DEMO review unavailable'));
  render(<EnrollScreen sessionId="DEMO-session" medications={null} onChanged={vi.fn()} />);
  enterReviewedMedication();
  const save = screen.getByRole('button', { name: 'Add this medication' });
  act(() => {
    fireEvent.click(save);
    fireEvent.click(save);
  });
  expect(create).toHaveBeenCalledOnce();
  await act(async () => finish(savedDraft));
});

it('does not rewrite reviewed source fields when confirmation preparation is retried', async () => {
  const create = vi.spyOn(api, 'createDraft').mockResolvedValue(savedDraft);
  vi.spyOn(api, 'resumeDraft').mockResolvedValue({ ...savedDraft, source_reviewed: true });
  const review = vi
    .spyOn(api, 'reviewDraft')
    .mockResolvedValue({ source_id: 'DEMO-source', reviewed_field_count: 2, note: 'DEMO_ONLY' });
  const confirmation = vi
    .spyOn(api, 'requestChallenge')
    .mockRejectedValue(new Error('DEMO confirmation unavailable'));
  render(<EnrollScreen sessionId="DEMO-session" medications={null} onChanged={vi.fn()} />);
  enterReviewedMedication();
  fireEvent.click(screen.getByRole('button', { name: 'Add this medication' }));
  await waitFor(() => expect(confirmation).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Add this medication' })).toHaveProperty(
      'disabled',
      false,
    ),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Add this medication' }));
  await waitFor(() => expect(confirmation).toHaveBeenCalledTimes(2));
  expect(create).toHaveBeenCalledOnce();
  expect(review).toHaveBeenCalledOnce();
});

it('completes a saved name-only draft after filling its missing instructions', async () => {
  const incomplete = {
    ...savedDraft,
    state: 'pending_clarification',
    missing_instructions: ['dose_amount'],
    review_inputs: {
      medication_name: 'DEMO course',
      dose_amount: null,
      dose_unit: 'tablet',
      frequency_rule: { kind: 'daily', local_times: ['08:00'], days_of_week: [] },
      is_prn: false,
    },
  };
  const completed = { ...savedDraft, regimen_id: 'DEMO-completed' };
  vi.spyOn(api, 'resumeDraft').mockImplementation(async (id) =>
    id === incomplete.regimen_id ? incomplete : completed,
  );
  const create = vi.spyOn(api, 'createDraft').mockResolvedValue(completed);
  const review = vi.spyOn(api, 'reviewDraft').mockResolvedValue({
    source_id: completed.source_id,
    reviewed_field_count: 2,
    note: 'DEMO_ONLY',
  });
  vi.spyOn(api, 'requestChallenge').mockResolvedValue({
    regimen_id: completed.regimen_id,
    challenge_id: 'DEMO-confirmation',
    session_id: 'DEMO-session',
    session_state: 'awaiting_confirmation',
    session_state_version: 1,
    expires_at: '2099-11-06T10:10:00Z',
    summary: {
      medication_name: 'DEMO course',
      dose_amount: 1,
      dose_unit: 'tablet',
      frequency: { kind: 'daily', local_times: ['08:00'], days_of_week: [] },
      is_prn: false,
      version_no: 2,
      local_timezone: 'Asia/Singapore',
    },
    note: 'DEMO_ONLY',
  });
  const activate = vi.spyOn(api, 'activate').mockResolvedValue({
    regimen_id: completed.regimen_id,
    state: 'active',
    superseded_regimen_ids: [],
  });
  render(
    <EnrollScreen
      sessionId="DEMO-session"
      medications={null}
      resumeRegimenId={incomplete.regimen_id}
      onChanged={vi.fn()}
    />,
  );
  await waitFor(() =>
    expect(screen.getByLabelText('Medication name')).toHaveProperty('value', 'DEMO course'),
  );
  fireEvent.change(screen.getByLabelText('Dose amount'), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review and add' }));
  fireEvent.click(
    screen.getByLabelText('I have checked these details against my original instructions.'),
  );
  const add = screen.getByRole('button', { name: 'Add this medication' });
  expect(add).toHaveProperty('disabled', false);
  fireEvent.click(add);
  await waitFor(() => expect(review).toHaveBeenCalledOnce());
  expect(create).toHaveBeenCalledOnce();
  expect(create.mock.calls[0]?.[0].dose_amount).toBe(1);
  expect(create.mock.calls[0]?.[1]).toBe(incomplete.medication_id);
  const confirm = await screen.findByRole('button', { name: 'Yes, save this medication' });
  expect(activate).not.toHaveBeenCalled();
  fireEvent.click(confirm);
  await waitFor(() => expect(activate).toHaveBeenCalledOnce());
  expect(activate.mock.calls[0]?.[0].regimen_id).toBe(completed.regimen_id);
});

it('blocks a blind second create when the first save response is unknown', async () => {
  const create = vi.spyOn(api, 'createDraft').mockRejectedValue(new Error('DEMO response lost'));
  render(<EnrollScreen sessionId="DEMO-session" medications={null} onChanged={vi.fn()} />);
  enterReviewedMedication();
  const add = screen.getByRole('button', { name: 'Add this medication' });
  fireEvent.click(add);
  await waitFor(() => expect(add).toHaveProperty('disabled', true));
  await screen.findAllByText(
    'The previous save result is unknown. Check saved medication setup before submitting again.',
  );
  fireEvent.click(add);
  expect(create).toHaveBeenCalledOnce();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
it('calculates inclusive calendar days across months/leap days and rejects reversed dates', () => {
  expect(courseEndForDuration('2028-02-28', 3)).toBe('2028-03-01');
  expect(courseDuration('2028-02-28', '2028-03-01')).toBe('3');
  expect(courseDuration('2026-10-18', '2026-10-18')).toBe('1');
  expect(courseDuration('2026-10-19', '2026-10-18')).toBe('');
  expect(courseDuration('2026-02-30', '2026-03-02')).toBe('');
});
it('asks for only days or end date, converts between modes and keeps the original course fields', () => {
  render(<EnrollScreen sessionId={null} medications={null} onChanged={() => undefined} />);
  fireEvent.change(screen.getByLabelText('Course start date'), { target: { value: '2028-02-28' } });
  fireEvent.change(screen.getByLabelText('Number of days'), { target: { value: '3' } });
  expect(screen.queryByLabelText('Last day (inclusive)')).toBeNull();
  expect(screen.getByText('Last day (inclusive): 2028-03-01')).toBeTruthy();
  fireEvent.click(screen.getByRole('radio', { name: 'Enter last day' }));
  expect(screen.getByLabelText('Last day (inclusive)')).toHaveProperty('value', '2028-03-01');
  expect(screen.queryByLabelText('Number of days')).toBeNull();
  fireEvent.change(screen.getByLabelText('Last day (inclusive)'), {
    target: { value: '2028-03-03' },
  });
  expect(screen.getByText('Number of days: 5')).toBeTruthy();
  fireEvent.click(screen.getByRole('radio', { name: 'Enter number of days' }));
  expect(screen.getByLabelText('Number of days')).toHaveProperty('value', '5');
  fireEvent.change(screen.getByLabelText('Course start date'), { target: { value: '2028-03-01' } });
  expect(screen.getByText('Last day (inclusive): 2028-03-05')).toBeTruthy();
});
it('automatically removes a success notice without a close button or focus change', () => {
  vi.useFakeTimers();
  render(
    <>
      <button>Keep focus</button>
      <AutoDismissNotice>DEMO added</AutoDismissNotice>
    </>,
  );
  screen.getByRole('button').focus();
  expect(screen.getByRole('status').textContent).toBe('DEMO added');
  expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
  act(() => vi.advanceTimersByTime(4500));
  expect(screen.queryByRole('status')).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole('button'));
});

it('does not restart a resumed draft when the parent refreshes its plan snapshot', async () => {
  const saved = {
    medication_id: 'DEMO-med',
    regimen_id: 'DEMO-draft',
    state: 'draft',
    source_id: 'DEMO-source',
    missing_instructions: [],
    reviewable_field_ids: [],
    note: 'DEMO only',
  };
  const resume = vi.spyOn(api, 'resumeDraft').mockResolvedValue(saved);
  const row: RegimenHistoryItem = {
    medication_id: 'DEMO-med',
    regimen_id: 'DEMO-draft',
    display_name: 'DEMO resumed',
    version_no: 1,
    state: 'draft',
    effective_from: null,
    effective_to: null,
    course_start_date: null,
    course_end_date: null,
    dose_amount: 1,
    dose_unit: 'tablet',
    food_instruction: null,
    is_prn: false,
    local_times: ['08:00'],
  };
  const props = {
    resumeRegimenId: 'DEMO-draft',
    resumeRow: row,
    sessionId: 'DEMO-session',
    medications: null,
    onChanged: () => undefined,
  };
  const { rerender } = render(<EnrollScreen {...props} />);
  await screen.findByDisplayValue('DEMO resumed');
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Review and add' })).toHaveProperty(
      'disabled',
      false,
    ),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Review and add' }));
  expect(screen.getByRole('button', { name: 'Add this medication' })).toBeTruthy();
  rerender(<EnrollScreen {...props} resumeRow={{ ...row }} />);
  expect(screen.getByRole('button', { name: 'Add this medication' })).toBeTruthy();
  expect(resume).toHaveBeenCalledTimes(1);
});
