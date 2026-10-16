export type CountUnit='tablet'|'capsule';
export type StockKind='count'|'refill'|'adjustment'|'lost'|'discarded'|'damaged';
export interface StockInput {id:string;kind:StockKind;quantity:number;unit:CountUnit;low_threshold:number;note:string;confirmed:boolean}
export interface StockTransaction extends Omit<StockInput,'confirmed'> {patient_id:string;medication_id:string;stock_after:number;recorded_at:string;source:'patient_confirmed';demo_only:true}
export interface StockStatus {label_quantities?:Array<{source_document_id:string;amount:number|null;unit:string|null;printed_line:string;review_status:string}>;medication_id:string;unit:CountUnit|null;last_confirmed_stock:number|null;last_confirmed_at:string|null;estimated_remaining:number|null;daily_requirement:number|null;estimated_days:number|null;low_stock:boolean;estimate_note:string;transactions:StockTransaction[]}
export type TaskCategory='medication_review'|'medication_follow_up'|'refill'|'monitoring'|'adherence'|'symptom_follow_up'|'expiry_storage';
export type TaskStatus='open'|'contacted'|'deferred'|'completed'|'cancelled';
export interface CareTaskInput {id:string;category:TaskCategory;title:string;due_at:string;medication_id:string|null;regimen_id:string|null;notes:string;confirmed:boolean}
export interface TaskUpdate {id:string;expected_version:number;status:TaskStatus;due_at:string|null;notes:string;confirmed:boolean}
export interface CareTask extends Omit<CareTaskInput,'confirmed'> {patient_id:string;status:TaskStatus;source:'patient_reported'|'stock_estimate';version:number;history:Array<{id:string;status:TaskStatus;due_at:string;notes:string;recorded_at:string}>;created_at:string;updated_at:string;demo_only:true}
export type BarrierKind='forgetfulness'|'running_out'|'side_effect_concern'|'scheduling'|'unclear_instructions'|'complexity'|'unsure_taken'|'other'|'prefer_not_to_say';
export interface BarrierInput {id:string;category:BarrierKind;occurred_at:string;regimen_id:string|null;description:string;chosen_action:string;follow_up_task_id:string|null;confirmed:boolean}
export interface Barrier extends Omit<BarrierInput,'confirmed'> {patient_id:string;recorded_at:string;source:'patient_reported';demo_only:true}
export interface CareReview {action:'stock'|'barrier'|'task'|'task_update';medication_id?:string|null;task_id?:string|null;stock?:StockInput|null;barrier?:BarrierInput|null;task?:CareTaskInput|null;task_update?:TaskUpdate|null}
export interface ObservationTrend {kind:string;unit:string;count:number;start:string;end:string;change:number|null;points:Array<{at:string;value:number;secondary_value:number|null}>;note:string}
export interface MedicationCareReview {source_records:Array<{name:string;regimen_id:string;version:number;state:string;source_document_id:string|null;source_type:string|null;review_status:string|null;patient_review_is_professional_verification:false}>;generated_at:string;timezone:string;observation_window_days:7|30;summary:import('./client').ReviewSummary;trends:ObservationTrend[];barriers:Barrier[];inventory:Array<Omit<StockStatus,'transactions'>>;follow_ups:CareTask[];questions:string[];adherence_denominator:string;source_note:string}
