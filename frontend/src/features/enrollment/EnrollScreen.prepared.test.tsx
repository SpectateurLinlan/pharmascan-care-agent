// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, type DraftCreateResponse } from '../../api/client';
import { EnrollScreen } from './EnrollScreen';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it('requires a separate original-name check before reviewing identity for a recovered new version', async () => {
  const saved: DraftCreateResponse = {
    medication_id: 'DEMO-med',
    regimen_id: 'DEMO-regimen',
    state: 'draft',
    source_id: 'DEMO-new-source',
    source_reviewed: true,
    missing_instructions: [],
    reviewable_field_ids: [],
    note: 'DEMO',
    version_no: 2,
    identity_review: { source_id: 'DEMO-original-source', medication_name: 'DEMO original name' },
    review_inputs: {
      medication_name: 'DEMO original name',
      dose_amount: 1,
      dose_unit: 'tablet',
      frequency_rule: { kind: 'daily', local_times: ['08:00'], days_of_week: [] },
      is_prn: false,
    },
  };
  vi.spyOn(api, 'resumeDraft').mockResolvedValue(saved);
  const identity = vi
    .spyOn(api, 'reviewOriginalIdentity')
    .mockResolvedValue({ reviewed_name_count: 1 });
  const confirmation = vi
    .spyOn(api, 'requestChallenge')
    .mockRejectedValue(new Error('DEMO test ends before challenge'));
  render(
    <EnrollScreen
      sessionId="DEMO-session"
      medications={null}
      onChanged={() => undefined}
      preparedReview={{
        regimenId: 'DEMO-regimen',
        version: 2,
        workflow: { task_id: 'DEMO-task', expected_revision: 4 },
      }}
    />,
  );
  await screen.findByRole('checkbox', {
    name: 'I checked the original medication name against its source.',
  });
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: 'I have checked these details against my original instructions.',
    }),
  );
  expect(screen.getByRole('button', { name: 'Add this medication' })).toHaveProperty(
    'disabled',
    true,
  );
  expect(identity).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: 'I checked the original medication name against its source.',
    }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Add this medication' }));
  await waitFor(() =>
    expect(identity).toHaveBeenCalledWith('DEMO-regimen', {
      task_id: 'DEMO-task',
      expected_revision: 4,
    }),
  );
  expect(confirmation).toHaveBeenCalledWith('DEMO-regimen', 'DEMO-session');
});
it('reviews an already prepared draft without creating another clinical aggregate', async () => {
  const saved: DraftCreateResponse = {
    medication_id: 'DEMO-med',
    regimen_id: 'DEMO-regimen',
    state: 'draft',
    source_id: 'DEMO-source',
    missing_instructions: [],
    reviewable_field_ids: [],
    note: 'DEMO',
    version_no: 1,
    review_inputs: {
      medication_name: 'DEMO prepared product',
      dose_amount: 1,
      dose_unit: 'tablet',
      frequency_rule: { kind: 'daily', local_times: ['08:00'], days_of_week: [] },
      dose_basis: {
        strength_text: '200mg',
        form: 'tablet',
        formulation: 'standard',
        single_ingredient: true,
        instructions_text: 'DEMO written instructions',
        patient_checked: false,
      },
      is_prn: false,
    },
  };
  vi.spyOn(api, 'resumeDraft').mockResolvedValue(saved);
  const create = vi.spyOn(api, 'createDraft');
  vi.spyOn(api, 'doseDisplay').mockResolvedValue({
    status: 'not_calculated',
    total_amount: null,
    total_unit: null,
    reason: 'not_checked',
  });
  const review = vi
    .spyOn(api, 'reviewDraft')
    .mockResolvedValue({ reviewed_field_count: 4, source_id: 'DEMO-source', note: 'DEMO' });
  vi.spyOn(api, 'requestChallenge').mockResolvedValue({
    regimen_id: 'DEMO-regimen',
    challenge_id: 'DEMO-confirm',
    session_id: 'DEMO-session',
    session_state: 'awaiting_confirmation',
    session_state_version: 2,
    expires_at: '2026-12-01T00:00:00Z',
    summary: {
      medication_name: 'DEMO prepared product',
      dose_amount: 1,
      dose_unit: 'tablet',
      frequency: { kind: 'daily', local_times: ['08:00'], days_of_week: [] },
      is_prn: false,
      version_no: 1,
      local_timezone: 'Asia/Singapore',
    },
    note: 'DEMO',
  });
  const activate = vi.spyOn(api, 'activate');
  render(
    <EnrollScreen
      sessionId="DEMO-session"
      medications={null}
      onChanged={() => undefined}
      preparedReview={{ regimenId: 'DEMO-regimen', version: 1 }}
    />,
  );
  await screen.findByText('DEMO prepared product');
  await screen.findByText('200mg');
  expect(screen.getByRole('button', { name: 'Add this medication' })).toHaveProperty(
    'disabled',
    true,
  );
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: 'I have checked these details against my original instructions.',
    }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Add this medication' }));
  await screen.findByRole('button', { name: 'Yes, save this medication' });
  await waitFor(() => expect(review).toHaveBeenCalledWith('DEMO-source'));
  expect(create).not.toHaveBeenCalled();
  expect(activate).not.toHaveBeenCalled();
});
