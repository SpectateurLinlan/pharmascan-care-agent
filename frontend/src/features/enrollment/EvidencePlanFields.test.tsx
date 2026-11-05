// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { EvidencePlanFields, type SourcePlanValues } from './EvidencePlanFields';
import type { EvidenceTask } from '../../api/client';

afterEach(cleanup);
const task: EvidenceTask = {
  id: 'DEMO-source',
  medication_id: 'DEMO-med',
  version: 2,
  status: 'ready_for_review',
  product: {
    name: 'DEMO medicine',
    strength: '200mg',
    dose_form: null,
    formulation: null,
    brand: null,
    manufacturer: null,
    ingredients: [],
    external_identifiers: {},
    category: 'unknown',
    verification: 'source_supplied',
  },
  source_ids: [],
  missing: [],
  conflicts: [],
  possible_duplicate_ids: [],
  draft_regimen_id: null,
  suggested_regimen: null,
};
const values: SourcePlanValues = {
  amount: '1',
  unit: 'tablet',
  times: '08:00',
  food: '',
  start: '',
  end: '',
  prn: false,
  category: 'unknown',
  patientEdited: false,
  reviewed: false,
};
it('requires the separate source acknowledgement before submitting through the parent', () => {
  const changed = vi.fn();
  const prepare = vi.fn();
  const props = { task, value: values, onChange: changed, onPrepare: prepare };
  const view = render(<EvidencePlanFields {...props} />);
  expect(screen.getByRole('button', { name: 'Prepare activation confirmation' })).toHaveProperty(
    'disabled',
    true,
  );
  fireEvent.click(
    screen.getByLabelText('I reviewed these details against my medication instructions.'),
  );
  expect(changed).toHaveBeenCalledWith({ reviewed: true });
  view.rerender(<EvidencePlanFields {...props} value={{ ...values, reviewed: true }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Prepare activation confirmation' }));
  expect(prepare).toHaveBeenCalledOnce();
});
it('preserves interval first-date requirements and explicit default-time disclosure', () => {
  const interval = {
    ...task,
    suggested_regimen: {
      medication_name: task.product.name,
      dose_amount: 1,
      dose_unit: 'tablet',
      is_prn: false,
      food_instruction: null,
      frequency_rule: { kind: 'interval', every_hours: 6, local_times: [], days_of_week: [] },
    },
  };
  const props = {
    task: interval,
    value: { ...values, times: '', reviewed: true },
    onChange: vi.fn(),
    onPrepare: vi.fn(),
  };
  const view = render(<EvidencePlanFields {...props} />);
  expect(screen.getByText(/08:00 is used by default/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Prepare activation confirmation' })).toHaveProperty(
    'disabled',
    true,
  );
  view.rerender(<EvidencePlanFields {...props} value={{ ...props.value, start: '2026-11-01' }} />);
  expect(screen.getByRole('button', { name: 'Prepare activation confirmation' })).toHaveProperty(
    'disabled',
    false,
  );
});
it('keeps source conflicts and duplicate warnings visible and cannot submit a conflict', () => {
  render(
    <EvidencePlanFields
      task={{
        ...task,
        conflicts: ['strength: conflicting source'],
        possible_duplicate_ids: ['DEMO-other'],
      }}
      value={{ ...values, reviewed: true }}
      onChange={vi.fn()}
      onPrepare={vi.fn()}
    />,
  );
  expect(screen.getByText(/A similar medicine is already saved/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Prepare activation confirmation' })).toHaveProperty(
    'disabled',
    true,
  );
});
