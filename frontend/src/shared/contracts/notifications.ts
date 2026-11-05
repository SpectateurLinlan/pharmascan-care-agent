/** Shared immutable-shape DTO contract; no transport or UI imports. */
export interface WorkflowPatientBinding {
  task_id: string;
  expected_revision: number;
}

export interface PushSubscriptionInput {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export interface PushSubscriptionRecord {
  id: string;
  enabled: boolean;
}
