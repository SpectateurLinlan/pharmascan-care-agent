/** Shared immutable-shape DTO contract; no transport or UI imports. */
export interface Measurement {
  kind?: 'note' | 'blood_pressure' | 'blood_glucose' | 'weight' | 'sleep' | 'mood';
  value?: number | null;
  secondary_value?: number | null;
  unit?: 'mmHg' | 'mmol/L' | 'mg/dL' | 'kg' | 'hours' | 'score' | null;
}

export interface HealthObservation extends Measurement {
  id: string;
  patient_id: string;
  description: string;
  occurred_at: string;
  severity: 'mild' | 'moderate' | 'severe' | null;
  notes: string | null;
  medication_id: string | null;
  source: 'patient_reported';
  created_at: string;
  updated_at: string;
  demo_only: true;
}

export interface ReviewSummary {
  period: 'week' | 'month' | 'course';
  window_start: string;
  window_end: string;
  generated_at: string;
  timezone: string;
  reported_taken: number;
  reported_not_taken: number;
  unsure: number;
  observations: HealthObservation[];
  questions: string[];
  coverage_note: string;
  medications: Array<{
    medication_id: string;
    regimen_id: string;
    name: string;
    version: number;
    state: string;
    is_prn: boolean;
    dose_amount: number | null;
    dose_unit: string | null;
    food_instruction: string | null;
    course_start: string | null;
    course_end: string | null;
    local_times: string[];
    recorded_occurrences: number;
    without_report: number;
  }>;
}
