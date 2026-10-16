export interface DoseBasis {strength_text:string;form:'tablet'|'capsule'|'liquid'|'other'|'unknown';formulation:'standard'|'modified_release'|'enteric'|'unknown';single_ingredient:boolean|null;instructions_text:string;patient_checked:boolean}
export interface DoseDisplay {status:'calculated'|'not_calculated'|'conflict';total_amount:number|null;total_unit:'mg'|null;reason:string}
