export function careCopy(language:string){return (en:string,zh:string)=>language==='zh'?zh:en;}
const labels:Record<string,readonly [string,string]>={
 medication_review:['Medication review','用药复查'],medication_follow_up:['Medication follow-up','用药跟进'],refill:['Refill','补药'],monitoring:['Treatment monitoring','治疗相关监测'],adherence:['Medication support','服药困难跟进'],symptom_follow_up:['Symptom follow-up','症状跟进'],expiry_storage:['Expiry and storage review','有效期与储存核对'],
 open:['Pending','待处理'],contacted:['Contacted','已联系'],deferred:['Rescheduled','已改期'],completed:['Completed','已完成'],cancelled:['Cancelled','已取消'],
 reported_taken:['Patient reported taken','患者自述已服'],reported_not_taken:['Patient reported not taken','患者自述未服'],unsure:['Patient unsure','患者自述不确定'],
};
export function careLabel(value:string,language:string,fallback:(value:string)=>string){const label=labels[value];return label?label[language==='zh'?1:0]:fallback(value);}
