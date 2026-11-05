/** Typed local dispatch; tool output cannot choose code, URLs or confirmations. */
import type { UIAction, WorkflowEvent, WorkflowView } from '../../../api/assistantWorkflows';

export function workflowChoice(
  view: WorkflowView,
  action: Extract<UIAction, { kind: 'choice' }>,
  value: string,
): WorkflowEvent {
  if (
    view.capability_id === 'reminder.list' &&
    action.action_id === 'reminder.days' &&
    action.options.some((option) => option.value === value) &&
    ['1', '3', '7'].includes(value)
  )
    return {
      event_id: crypto.randomUUID(),
      expected_revision: view.revision,
      kind: 'provide_fields',
      values: { days: Number(value), page: 0 },
    };
  if (
    view.capability_id === 'source.preview' &&
    action.action_id === 'preview.source_kind' &&
    action.options.some((option) => option.value === value) &&
    ['pharmacy_label', 'package', 'prescription'].includes(value)
  )
    return {
      event_id: crypto.randomUUID(),
      expected_revision: view.revision,
      kind: 'provide_fields',
      values: { source_kind: value },
    };
  if (
    view.capability_id === 'image.compare' &&
    action.options.some((option) => option.value === value)
  ) {
    if (action.action_id === 'compare.intent' && ['personal', 'identify'].includes(value))
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { intent: value, regimen_id: null, page: 0 },
      };
    if (
      action.action_id === 'compare.regimen' &&
      (value === 'all' || /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value))
    )
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { regimen_id: value === 'all' ? null : value, page: 0 },
      };
  }
  if (
    view.capability_id === 'library.pdf.add' &&
    action.action_id === 'pdf.medication' &&
    action.options.some((option) => option.value === value) &&
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
  )
    return {
      event_id: crypto.randomUUID(),
      expected_revision: view.revision,
      kind: 'provide_fields',
      values: { medication_id: value, page: 0 },
    };
  if (
    view.capability_id === 'gallery.photo.add' &&
    action.action_id === 'photo.medication' &&
    action.options.some((option) => option.value === value) &&
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
  )
    return {
      event_id: crypto.randomUUID(),
      expected_revision: view.revision,
      kind: 'provide_fields',
      values: { medication_id: value, page: 0 },
    };
  if (
    [
      'gallery.photo.edit',
      'gallery.photo.remove',
      'gallery.photo.delete',
      'gallery.photo.retire',
      'library.pdf.edit',
      'library.pdf.delete',
    ].includes(view.capability_id) &&
    action.options.some((option) => option.value === value)
  ) {
    const match = /^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):([1-9]\d{0,8})$/i.exec(value);
    const field =
      action.action_id === 'media.photo_target' && view.capability_id.startsWith('gallery.')
        ? 'image_id'
        : action.action_id === 'media.pdf_target' && view.capability_id.startsWith('library.')
          ? 'file_id'
          : null;
    if (field && match)
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { [field]: match[1]!, expected_version: Number(match[2]), page: 0 },
      };
    if (
      action.action_id === 'media.medication' &&
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
    )
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { medication_id: value, page: 0 },
      };
  }
  if (
    ['gallery.photo.view', 'library.list', 'library.pdf.view', 'library.pdf.download'].includes(
      view.capability_id,
    ) &&
    action.options.some((option) => option.value === value) &&
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
  ) {
    const field =
      action.action_id === 'media.medication'
        ? 'medication_id'
        : action.action_id === 'media.image' && view.capability_id === 'gallery.photo.view'
          ? 'image_id'
          : action.action_id === 'media.file' && view.capability_id.startsWith('library.pdf.')
            ? 'file_id'
            : null;
    if (field)
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { [field]: value, page: 0 },
      };
  }
  if (
    action.action_id.startsWith('care.') &&
    action.options.some((option) => option.value === value)
  ) {
    if (action.action_id === 'care.task') {
      const match = /^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):([1-9]\d{0,8})$/i.exec(value);
      if (match)
        return {
          event_id: crypto.randomUUID(),
          expected_revision: view.revision,
          kind: 'provide_fields',
          values: { task_id: match[1]!, expected_version: Number(match[2]), page: 0 },
        };
    }
    if (
      ['care.medication', 'care.observation'].includes(action.action_id) &&
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
    )
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: {
          [action.action_id === 'care.medication' ? 'medication_id' : 'observation_id']: value,
        },
      };
  }
  if (
    ['dose.late.review', 'dose.correction.review'].includes(view.capability_id) &&
    action.options.some((option) => option.value === value)
  ) {
    if (action.action_id === 'late.target') {
      const match =
        /^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):([1-9]\d{0,2}):(none|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/i.exec(
          value,
        );
      if (match)
        return {
          event_id: crypto.randomUUID(),
          expected_revision: view.revision,
          kind: 'provide_fields',
          values: {
            occurrence_id: match[1]!,
            expected_version: Number(match[2]),
            expected_report_id: match[3] === 'none' ? null : match[3]!,
            page: 0,
          },
        };
    }
    if (action.action_id === 'late.page' && /^page:\d{1,6}$/.test(value))
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { page: Number(value.slice(5)) },
      };
  }
  if (
    (view.capability_id === 'dose.report' || view.capability_id === 'dose.prn.report') &&
    action.options.some((option) => option.value === value)
  ) {
    if (action.action_id === 'report.target') {
      const match = /^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):([1-9]\d{0,8})$/i.exec(value);
      if (match)
        return {
          event_id: crypto.randomUUID(),
          expected_revision: view.revision,
          kind: 'provide_fields',
          values: { regimen_id: match[1]!, expected_version: Number(match[2]), page: 0 },
        };
    }
    if (action.action_id === 'report.page' && /^page:\d{1,6}$/.test(value))
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { page: Number(value.slice(5)) },
      };
  }
  if (
    [
      'medication.today',
      'medication.due',
      'medication.status',
      'medication.history',
      'medication.source.view',
      'medication.instructions',
      'record.catalogue',
      'record.history',
      'record.summary',
      'record.visit.prepare',
    ].includes(view.capability_id) &&
    action.options.some((option) => option.value === value)
  ) {
    if (
      action.action_id === 'record.medication' &&
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
    )
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { medication_id: value, page: 0 },
      };
    if (
      action.action_id === 'record.course' &&
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
    )
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { regimen_id: value, page: 0 },
      };
    if (action.action_id === 'record.page' && /^page:\d{1,6}$/.test(value))
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { page: Number(value.slice(5)) },
      };
  }
  if (
    view.capability_id === 'medication.plan.change' &&
    action.options.some((option) => option.value === value)
  ) {
    if (action.action_id === 'medication.change_target') {
      const match =
        /^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):([1-9]\d{0,8}):(active|ended|superseded)$/i.exec(
          value,
        );
      if (match)
        return {
          event_id: crypto.randomUUID(),
          expected_revision: view.revision,
          kind: 'provide_fields',
          values: {
            regimen_id: match[1]!,
            expected_version: Number(match[2]),
            expected_state: match[3]!.toLowerCase(),
            page: 0,
            details: null,
          },
        };
    }
    if (action.action_id === 'medication.page' && /^page:\d{1,6}$/.test(value))
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { page: Number(value.slice(5)) },
      };
  }
  if (
    view.capability_id === 'medication.source.review' &&
    action.options.some((option) => option.value === value)
  ) {
    if (action.action_id === 'source.target') {
      const match = /^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):([1-9]\d{0,8})$/i.exec(value);
      if (match)
        return {
          event_id: crypto.randomUUID(),
          expected_revision: view.revision,
          kind: 'provide_fields',
          values: { source_task_id: match[1]!, expected_version: Number(match[2]), page: 0 },
        };
    }
    if (action.action_id === 'source.page' && /^page:\d{1,6}$/.test(value))
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { page: Number(value.slice(5)) },
      };
  }
  if (
    view.capability_id === 'medication.draft.resume' &&
    action.options.some((option) => option.value === value)
  ) {
    if (action.action_id === 'medication.resume_target') {
      const match = /^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):([1-9]\d{0,8})$/i.exec(value);
      if (match)
        return {
          event_id: crypto.randomUUID(),
          expected_revision: view.revision,
          kind: 'provide_fields',
          values: {
            regimen_id: match[1]!,
            expected_version: Number(match[2]),
            page: 0,
            details: null,
          },
        };
    }
    if (action.action_id === 'medication.page' && /^page:\d{1,6}$/.test(value))
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { page: Number(value.slice(5)) },
      };
  }
  if (
    view.capability_id === 'medication.draft.delete' &&
    action.action_id === 'medication.delete_target' &&
    action.options.some((option) => option.value === value)
  ) {
    const match =
      /^(draft|source):([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):([1-9]\d{0,8})$/i.exec(value);
    if (match)
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { kind: match[1]!, target_id: match[2]!, expected_version: Number(match[3]) },
      };
  }
  if (
    view.capability_id === 'medication.plan.end' &&
    action.action_id === 'medication.end_target' &&
    action.options.some((option) => option.value === value)
  ) {
    const match = /^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):([1-9]\d{0,8})$/i.exec(value);
    if (match)
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { regimen_id: match[1]!, expected_version: Number(match[2]) },
      };
  }
  if (
    (view.capability_id === 'medication.plan.view' ||
      view.capability_id === 'medication.setup.list') &&
    action.options.some((option) => option.value === value)
  ) {
    if (
      action.action_id === 'medication.target' &&
      view.capability_id === 'medication.plan.view' &&
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
    )
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { medication_id: value, page: 0 },
      };
    if (action.action_id === 'medication.page' && /^page:\d{1,6}$/.test(value))
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { page: Number(value.slice(5)) },
      };
  }
  if (
    view.capability_id === 'medication.enroll' &&
    action.action_id === 'enrollment.source_product' &&
    action.options.some((option) => option.value === value)
  ) {
    const match = /^([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}):(\d|1\d)$/i.exec(value);
    if (match)
      return {
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'select_candidate',
        values: { source_attachment_id: match[1]!, source_candidate_index: Number(match[2]) },
      };
  }
  if (
    view.capability_id === 'medication.enroll' &&
    action.action_id === 'enrollment.duplicate' &&
    action.options.some((option) => option.value === value) &&
    (value === 'different_product' ||
      value === 'distinct_product' ||
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value))
  ) {
    return {
      event_id: crypto.randomUUID(),
      expected_revision: view.revision,
      kind: 'select_candidate',
      values:
        value === 'different_product' || value === 'distinct_product'
          ? { choice: value }
          : { existing_medication_id: value },
    };
  }
  if (
    view.capability_id === 'medication.enroll' &&
    action.action_id === 'enrollment.method' &&
    (value === 'manual' || value === 'photo') &&
    action.options.some((option) => option.value === value)
  ) {
    return {
      event_id: crypto.randomUUID(),
      expected_revision: view.revision,
      kind: 'choose_method',
      values: { method: value },
    };
  }
  throw new Error('This choice is unavailable. Refresh the current step.');
}
