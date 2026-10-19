export type LateStatus='reported_taken'|'reported_not_taken'|'unsure';
export type LateReason='forgot_to_record'|'app_unavailable'|'unsure_time'|'correcting_record'|'other';
export interface DoseFollowUp {occurrence_id:string;regimen_id:string;medication_id:string;medication_name:string;strength_text?:string|null;form?:string|null;version_no?:number;can_report?:boolean;unavailable_reason?:'review_required'|null;due_at:string;dose_amount:number|null;dose_unit:string|null;report_id:string|null;intake_status:LateStatus|null;actual_administration_at:string|null;recorded_at:string|null;reason:LateReason|null;notes:string}
export interface LateReportInput {id:string;intake_status:LateStatus;actual_administration_at:string|null;reason:LateReason;notes:string;expected_report_id:string|null}
export interface LateReportRecord extends LateReportInput {patient_id:string;occurrence_id:string;regimen_id:string;recorded_at:string;version:number;idempotency_key:string;ingestion_proven:false;visual_status:'not_checked'}
export interface LateReportChallenge {challenge_id:string;session_id:string;expires_at:string;occurrence:DoseFollowUp;proposed:LateReportInput;timezone:string}
export interface DoseFollowUps {items:DoseFollowUp[];has_more:boolean;as_of:string;timezone:string}

export interface DoseReportAudit {original:{id:string;intake_status:LateStatus;created_at:string}|null;corrections:LateReportRecord[]}
