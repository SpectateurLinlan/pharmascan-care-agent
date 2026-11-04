import type {SupportClientActions} from './AssistantSupportActions';
import type {WorkflowEvent,WorkflowView,WorkflowEventHandler} from '../api/assistantWorkflows';
import {lazy,Suspense,useEffect,useState} from 'react';
import {AssistantEnrollmentFields} from './AssistantEnrollmentFields';
import {AssistantMedicationActions} from './AssistantMedicationActions';
import {workflowChoice} from '../assistantWorkflowActions';
import {useLanguage} from '../language';
import {intakeStatusWords} from './ConfirmReportSheet';
const EnrollScreen=lazy(()=>import('./EnrollScreen').then(module=>({default:module.EnrollScreen})));
const AssistantSourceActions=lazy(()=>import('./AssistantSourceActions').then(module=>({default:module.AssistantSourceActions})));
const AssistantRecordActions=lazy(()=>import('./AssistantRecordActions').then(module=>({default:module.AssistantRecordActions})));
const AssistantDoseReportActions=lazy(()=>import('./AssistantDoseReportActions').then(module=>({default:module.AssistantDoseReportActions})));
const AssistantLateReportActions=lazy(()=>import('./AssistantLateReportActions').then(module=>({default:module.AssistantLateReportActions})));
const AssistantKnowledgeActions=lazy(()=>import('./AssistantKnowledgeActions').then(module=>({default:module.AssistantKnowledgeActions})));
const AssistantCareActions=lazy(()=>import('./AssistantCareActions').then(module=>({default:module.AssistantCareActions})));
const AssistantMediaActions=lazy(()=>import('./AssistantMediaActions').then(module=>({default:module.AssistantMediaActions})));
const AssistantPhotoUpload=lazy(()=>import('./AssistantPhotoUpload').then(module=>({default:module.AssistantPhotoUpload})));
const AssistantPdfUpload=lazy(()=>import('./AssistantPdfUpload').then(module=>({default:module.AssistantPdfUpload})));
const AssistantImageCompare=lazy(()=>import('./AssistantImageCompare').then(module=>({default:module.AssistantImageCompare})));
const AssistantSourcePreview=lazy(()=>import('./AssistantSourcePreview').then(module=>({default:module.AssistantSourcePreview})));
const AssistantReminderActions=lazy(()=>import('./AssistantReminderActions').then(module=>({default:module.AssistantReminderActions})));
const AssistantReminderChanges=lazy(()=>import('./AssistantReminderChanges').then(module=>({default:module.AssistantReminderChanges})));
const reminderChanges=new Set(['reminder.snooze','reminder.settings']);
const AssistantNotificationActions=lazy(()=>import('./AssistantNotificationActions').then(module=>({default:module.AssistantNotificationActions})));
const notificationDevices=new Set(['notification.subscribe','notification.unsubscribe','notification.test']);
const AssistantSettingsActions=lazy(()=>import('./AssistantSettingsActions').then(module=>({default:module.AssistantSettingsActions})));
const AssistantAccountActions=lazy(()=>import('./AssistantAccountActions').then(module=>({default:module.AssistantAccountActions})));
const AssistantSupportActions=lazy(()=>import('./AssistantSupportActions').then(module=>({default:module.AssistantSupportActions})));
const AssistantFeedbackActions=lazy(()=>import('./AssistantFeedbackActions').then(module=>({default:module.AssistantFeedbackActions})));
const supportCapabilities=new Set(['conversation.list','conversation.view','conversation.resume','conversation.new','conversation.clear','assistant.usage','speech.input','speech.playback','help.open','guide.start','navigation.open']);
const settingsCapabilities=new Set(['preference.language','preference.text','preference.voice','preference.reminder','preference.privacy','preference.timezone','profile.edit','profile.view','caregiver.list','caregiver.add','caregiver.edit','caregiver.delete']);
const accountCapabilities=new Set(['account.status','account.login','account.link','account.password','account.signout']);
const reminderReads=new Set(['reminder.list','reminder.calendar.export','notification.status']);
const mediaCapabilities=new Set(['gallery.list','gallery.photo.view','library.list','library.pdf.view','library.pdf.download']);
const AssistantMediaLifecycle=lazy(()=>import('./AssistantMediaLifecycle').then(module=>({default:module.AssistantMediaLifecycle})));
const mediaChanges=new Set(['gallery.photo.edit','gallery.photo.remove','gallery.photo.delete','gallery.photo.retire','library.pdf.edit','library.pdf.delete']);
const careCapabilities=new Set(['observation.list','observation.add','observation.edit','observation.delete','inventory.view','inventory.count','barrier.list','barrier.add','followup.list','followup.add','followup.edit','followup.contacted','followup.complete','followup.defer','followup.cancel']);
const recordCapabilities=new Set(['medication.today','medication.due','medication.status','medication.history','medication.source.view','medication.instructions','record.catalogue','record.history','record.summary','record.visit.prepare']);

const labels:Record<string,[string,string]>={
 'assistant.care.historical':['The earlier care operation succeeded. Its current record has changed or is unavailable.','此前关怀操作已成功，当前记录已变更或不可用。'],
 'assistant.conversation.read':['Your saved conversation text is shown below.','以下显示已保存的会话文字。'],
 'assistant.conversation.select':['Select conversation','选择会话'],
 'assistant.conversation.patient_action':['Review the conversation action separately. Saved workflow drafts remain.','请单独核对会话操作，已保存办理草稿会保留。'],
 'assistant.support.destination':['Choose an existing app page.','请选择现有应用页面。'],
 'assistant.support.patient_action':['Start this device action or open the page explicitly.','请手动开始设备操作或打开页面。'],
 'assistant.feedback.collect':['Enter feedback details below.','请在下方填写反馈资料。'],
 'assistant.feedback.patient_review':['Review feedback and confirm separately.','请核对反馈并单独确认。'],
 'assistant.feedback.saved':['The feedback was saved. This does not mean it was emailed or reviewed.','反馈已保存，这不表示已发送邮件或已获审阅。'],
 'assistant.feedback.changed':['Check the uncertain feedback result before continuing.','请先核查尚未确认的反馈结果，再继续。'],
 'assistant.feedback.check_result':['Check whether the feedback was saved.','请核查反馈是否已保存。'],
 'assistant.reminder.read':['These are projected reminders from your recorded plans.','以下提醒根据已登记计划预计。'],
 'assistant.reminder.calendar':['Choose calendar options before exporting a file.','导出文件前，请选择日历选项。'],
 'assistant.reminder.device':['Explicitly check the current device status.','请手动核查当前设备状态。'],
 'assistant.source_preview.collect':['Choose a source type and save the original before previewing.','请选择来源类型，预览前先保存原图。'],
 'assistant.source_preview.ready':['Explicitly allow reading the current source. Previewing does not save reviewed instructions.','请明确同意后读取当前来源，预览不会保存已核对用药说明。'],
 'assistant.compare.collect':['Choose a photo check and save its original before processing.','请选择照片比对方式，处理前先保存原图。'],
 'assistant.compare.ready':['Explicitly allow processing and start the current photo check.','请明确同意处理，再发起本次照片比对。'],
 'assistant.pdf.medication':['Choose the medication to receive this PDF.','请选择要关联 PDF 的药物。'],
 'assistant.pdf.collect':['Choose a PDF and complete its details.','请选择 PDF 并填写资料。'],
 'assistant.pdf.ready':['The original PDF is saved. Prepare a separate review to add it to the library.','原始 PDF 已保存，请准备独立核对后再加入资料库。'],
 'assistant.pdf.review':['Review the medication and PDF, then confirm separately.','请核对药物和 PDF，再单独确认。'],
 'assistant.pdf.check_result':['Check whether the PDF was saved to the library.','请核查 PDF 是否已保存到资料库。'],
 'assistant.pdf.completed':['The actual PDF library result was checked.','已核查实际 PDF 资料库保存结果。'],
 'assistant.pdf.changed':['The PDF changed or is unavailable. Check its current library record.','PDF 已变化或不可用，请核查当前资料库记录。'],
 'assistant.photo.medication':['Choose the medication to receive this photo.','请选择要关联照片的药物。'],
 'assistant.photo.collect':['Choose a photo and complete its description.','请选择照片并补充说明。'],
 'assistant.photo.ready':['The original is saved. Prepare a separate patient review to add it to the gallery.','原图已保存，请准备独立核对后再添加到图库。'],
 'assistant.photo.review':['Review the medication and photo, then confirm separately.','请核对药物和照片，再单独确认。'],
 'assistant.photo.check_result':['Check whether the gallery photo was saved.','请核查图库照片的保存结果。'],
 'assistant.photo.completed':['The actual gallery result was checked.','已核查实际图库保存结果。'],
 'assistant.photo.changed':['The photo changed or is unavailable. Check the current gallery record.','照片已变化或不可用，请核查当前图库记录。'],
 'assistant.settings.collect':['Enter the settings or consented contact details below.','请在下方填写设置或已获同意的联系人资料。'],
 'assistant.settings.read':['Your current saved information is shown below.','以下显示您当前保存的资料。'],
 'assistant.settings.patient_review':['Review the exact change and confirm separately.','请核对具体变更并单独确认。'],
 'assistant.settings.saved':['The earlier change was saved. Current values may have changed since.','此前变更已保存，当前资料可能后来发生变化。'],
 'assistant.settings.changed':['The current information changed or the result is uncertain. Check before continuing.','当前资料已变化或结果尚未确认，请先核查再继续。'],
 'assistant.settings.check_result':['Check whether the settings change was saved.','请核查设置变更是否已保存。'],
 'assistant.account.secure':['Continue in the native secure account form.','请在原有安全账户表单中继续。'],
 'assistant.notification.device':['Open the secure device controls, check the current state, then confirm the action separately.','请打开安全设备操作，核查当前状态后再单独确认。'],
 'assistant.reminder.collect':['Choose the reminder and enter the changes.','请选择提醒并填写变更。'],
 'assistant.reminder.ready':['Check these details before preparing a separate reminder review.','请核对资料，再准备独立的提醒核对。'],
 'assistant.reminder.patient_review':['Review the exact reminder change and confirm separately.','请核对具体提醒变更并单独确认。'],
 'assistant.reminder.check_result':['Check whether the reminder change was saved.','请核查提醒变更是否已保存。'],
 'assistant.reminder.changed':['The reminder state changed or its result is uncertain. Check the current state before continuing.','提醒状态已变化或结果尚未确认，请先核查当前状态。'],
 'assistant.reminder.saved':['The earlier reminder change was saved. Current state may have changed since.','此前的提醒变更已保存，当前状态可能后来发生变化。'],
 'assistant.media.collect':['Enter the file details below.','请在下方填写文件资料。'],
 'assistant.media.ready':['Check these details before preparing the independent patient review.','请核对资料，再准备独立的患者确认。'],
 'assistant.media.patient_review':['Review the exact file action and confirm separately.','请核对具体的文件操作并单独确认。'],
 'assistant.media.changed':['The file changed or the result is unknown. Check its current state before continuing.','文件已发生变化或结果未确认，请先核查当前状态。'],
 'assistant.media.check_result':['Check the actual file action result.','请核查实际文件操作结果。'],
 'assistant.media.completed':['The file action result was verified.','已核查文件操作结果。'],
 'assistant.media.historical':['This earlier action was recorded. The file has changed since; check its current record.','此前的操作已记录，文件后来发生了变化，请查看当前文件记录。'],
 'assistant.media.read':['Your recorded photos and documents are shown below.','以下是已保存的照片和文件。'],
 'assistant.media.choose_medication_id':['Choose the medication whose files you want to view.','请选择要查看文件的药物。'],
 'assistant.media.choose_image_id':['Choose the recorded photo to view.','请选择要查看的照片。'],
 'assistant.media.choose_file_id':['Choose the PDF document.','请选择 PDF 文件。'],
 'assistant.care.collect':['Choose the record and enter the missing care details.','请选择记录并填写所缺的关怀资料。'],
 'assistant.care.select':['Select record','选择记录'],
 'assistant.care.ready':['Check these details before preparing a separate patient review.','请核对资料，再准备单独的患者核对。'],
 'assistant.care.patient_review':['Open the patient review and confirm separately to save.','请打开患者核对，单独确认后保存。'],
 'assistant.care.completed':['Your care record was saved and its actual result checked.','关怀记录已保存，并已核查实际结果。'],
 'assistant.care.read':['These results come from your recorded care information.','以下结果来自您已记录的关怀资料。'],
 'assistant.care.changed':['The record changed. Start a new review of its current details.','记录已发生变化，请根据当前资料重新核对。'],
 'assistant.knowledge.name':['Enter the medicine name to prepare a general knowledge query.','请填写药名，准备查询一般药物知识。'],
 'assistant.knowledge.ready':['The name is ready. Search public sources when you choose.','药名已准备好，请点击查询公开来源。'],
 'assistant.knowledge.confirm_name':['Confirm a suggested medicine name before querying.','请先确认建议的药名，再查询资料。'],
 'assistant.late.choose':['Choose an existing dose from the past seven days.','请选择过去七天内已有的登记剂次。'],
 'assistant.late.select':['Select occurrence','选择剂次'],
 'assistant.late.empty':['No eligible existing occurrences were found for this review.','没有找到适用于本次核对的既有剂次。'],
 'assistant.late.ready':['Check this existing dose before opening the patient form.','打开患者表单前，请核对这项既有剂次。'],
 'assistant.late.patient_review':['Open the patient form, review the report and confirm separately.','请打开患者表单、核对自述，再单独确认。'],
 'assistant.late.changed':['The report changed. Start a new review from its current history.','自述记录发生变化，请从当前历史重新发起核对。'],
 'assistant.late.completed':['Your historical patient report was saved. Original reports are retained.','历史患者自述已保存，原有记录已保留。'],
 'assistant.report.choose':['Choose the recorded plan for your patient report.','请选择要自述的登记计划。'],
 'assistant.report.empty':['No eligible current plans were found for this report.','没有找到适用于本次自述的当前计划。'],
 'assistant.report.ready':['Review this report action before choosing your patient response.','请先核对自述对象，再选择您的自述情况。'],
 'assistant.report.patient_review':['Choose your response, review the summary, then confirm separately.','请选择自述情况、核对摘要，再单独确认。'],
 'assistant.report.changed':['The plan or report review changed. Reopen the current report action.','计划或核对内容发生变化，请重新打开当前自述操作。'],
 'assistant.report.completed':['Your patient report was saved. It records what you said about this dose.','患者自述已保存，记录的是您对本次服药的陈述。'],
 'assistant.records.choose':['Choose the recorded medicine to query.','请选择要查询的已登记药物。'],
 'assistant.records.empty':['No recorded medicines are available for this query.','本次查询没有可用的已登记药物。'],
 'assistant.records.course':['Choose the recorded course to summarize.','请选择要统计的已登记疗程。'],
 'assistant.records.read':['The results below come from your recorded plans and patient reports.','以下结果来自您的登记计划与患者自述记录。'],
 'assistant.plan_change.choose':['Choose the recorded plan whose instructions changed.','请选择用药说明发生变化的已登记计划。'],
 'assistant.plan_change.empty':['No recorded plans are available to change.','没有可修改的已登记计划。'],
 'assistant.plan_change.edit':['Enter the changed instructions from your original label or clinician.','请根据原标签或医护人员的说明填写变更。'],
 'assistant.plan_change.review':['Check the changed instructions, then prepare a separate review.','请核对变更后的说明，再准备单独核对。'],
 'assistant.source.choose':['Choose the saved source registration to review.','请选择要核对的来源登记。'],
 'assistant.source.select':['Choose source','选择来源'],
 'assistant.source.ready':['Review the original medication source before saving.','保存前请核对药物原始来源。'],
 'assistant.source.patient_review':['Check the source and instructions. Activation requires a separate confirmation.','请核对来源与说明，启用用药计划仍需单独确认。'],
 'assistant.source.changed':['The source changed or its result needs checking. Check task status before continuing.','来源已发生变化或保存结果待核查，请先核查办理状态。'],
 'assistant.source.resume_original':['Continue the original source task to retain its photos and review progress.','请返回原来源任务，保留其原图与核对进度。'],
 'assistant.medication.choose_resume':['Choose the unfinished plan to continue.','请选择要继续的未完成计划。'],
 'assistant.medication.resume_original':['Continue the original saved enrollment to retain its photos and review progress.','请回到原登记任务继续办理，保留其原图与核对进度。'],
 'assistant.medication.original_unavailable':['The original enrollment cannot currently be resumed. Its saving permission may have changed.','当前无法恢复原登记任务，其保存许可可能已发生变化。'],
 'assistant.medication.resume_source':['This draft needs its original source registration reviewed. This review is currently unavailable in Assistant.','这份草稿需要先核对原来源登记，Assistant 暂无法办理这类来源核对。'],
 'assistant.medication.choose_delete':['Choose the unfinished registration to delete.','请选择要删除的未完成登记。'],
 'assistant.medication.no_drafts':['No unfinished medication drafts were found.','没有找到未完成的药物草稿。'],
 'assistant.medication.select_draft':['Choose draft','选择草稿'],
 'assistant.medication.review_delete':['Review this draft and its deletion consequences before confirming separately.','请核对这份草稿及删除后果，再单独确认。'],
 'assistant.medication.deleted':['The draft was deleted. Confirmed history is retained.','草稿已删除，已确认的历史记录已保留。'],
 'assistant.medication.delete_cleanup':['The draft was deleted. Photo cleanup still needs a retry.','草稿已删除，照片清理仍需重试。'],
 'assistant.medication.deletion_changed':['The records changed. Recheck the draft before deleting it.','记录已发生变化，请重新核对草稿后再删除。'],
 'assistant.medication.deletion_unknown':['The deletion result is unknown. A missing record does not confirm deletion. Check task status.','删除结果尚未确认，记录暂时不可见不代表已删除，请核查办理状态。'],
 'assistant.medication.read':['Your recorded plans and setup progress are shown below.','以下是已记录的计划与登记进度。'],
 'assistant.medication.choose_stop':['Choose the active recorded plan to stop tracking.','请选择要停止追踪的已启用计划。'],
 'assistant.medication.no_active':['There are no active recorded plans to stop tracking.','当前没有可停止追踪的已启用计划。'],
 'assistant.medication.page_changed':['The records changed. Showing the first available page.','记录发生变化，已显示当前可用的第一页。'],
 'assistant.medication.review_stop':['Review the current recorded plan. Stopping tracking keeps past records and still needs your separate confirmation.','请核对当前计划。停止追踪会保留历史记录，仍需您单独确认。'],
 'assistant.medication.ended':['This recorded plan has ended. Past records are retained.','这项记录中的计划已结束，历史记录已保留。'],
 'assistant.medication.select_plan':['Choose plan','选择计划'],
 'assistant.medication.choose':['Choose the medication record to view.','请选择要查看的药物记录。'],
 'assistant.medication.select':['View record','查看记录'],
 'assistant.medication.previous':['Previous page','上一页'],
 'assistant.medication.next':['Next page','下一页'],
 'assistant.enrollment.too_many_products':['The original is saved, but it contains more than 20 products. Switch to manual entry for this medication.','原图已保存，但一张图识别出超过20个产品，无法完整列出。请改为手动录入这项药物。'],
 'assistant.enrollment.manual':['Enter manually','手动录入'],
 'assistant.enrollment.check_preparation':['The draft result needs checking. Inspect it before trying again.','需要核查草稿的创建结果，请先核查后再继续。'],
 'assistant.enrollment.source_product':['Select this product','选择此产品'],
 'assistant.enrollment.choose_source_product':['Choose the product and original photo to use. No products will be merged automatically.','请选择这次使用的产品和原图，系统不会自动合并产品。'],
 'assistant.enrollment.patient_review':['The draft is saved. Check the original instructions, then confirm separately.','药物草稿已保存，请核对原始说明后单独确认。'],
 'assistant.enrollment.completed':['The medication plan is active.','药物计划已启用。'],
 'assistant.enrollment.result_changed':['The prepared plan changed or is unavailable. Check its current record before continuing.','已准备的计划发生变化或暂不可用，请核查当前记录后继续。'],
 'assistant.enrollment.photo':['Use a photo','拍照识别'],
 'assistant.enrollment.reuse_existing':['Use existing record','使用已有记录'],
 'assistant.enrollment.different_product':['Enter a different product name or strength','填写另一种产品名称或规格'],
 'assistant.enrollment.distinct_product':['Register a separate product with this different recorded strength','按这份不同规格的原始记录另行登记'],
 'assistant.enrollment.duplicate':['A matching name is already recorded. Choose its record or enter a different product.','已有同名药物，请选择已有记录或填写另一种产品。'],
 'assistant.enrollment.interval_default':['The first dose time was not supplied. The app will use its existing 08:00 default; review it before confirming.','未填写首次时间，应用将使用原有的08:00默认值，请在确认前核对。'],
 'assistant.enrollment.choose_method':['Choose how to add the medication.','请选择添加药物的方式。'],
 'assistant.enrollment.upload_source':['Upload the original medication label or prescription.','请上传药物标签或处方原图。'],
 'assistant.enrollment.provide_fields':['Continue with the remaining details.','请继续补充缺少的资料。'],
 'assistant.enrollment.review_inputs':['Check these details against your original instructions.','请对照原始用药说明核对这些资料。'],
 'assistant.enrollment.extraction_failed':['The original photo is saved, but its medication details could not be read.','原图已保存，但暂时无法识别药物资料。'],
 'assistant.enrollment.ephemeral_photo':['The original photo is not saved. Refreshing loses the page copy.','原图尚未保存，刷新后会丢失当前页面的原图。'],
 'assistant.enrollment.processing_consent':['The original photo is saved. Allow photo processing if you want recognition.','原图已保存，如需识别请允许图片处理。'],
 'assistant.workflow.ephemeral_lost':['Page details are unavailable. Please enter them again.','当前页面资料已丢失，请重新输入。'],
 'assistant.workflow.interrupted':['The previous request was interrupted. Check its result before retrying.','上次请求已中断，请先核查结果再重试。'],
 'assistant.workflow.save_failed':['Saving did not finish. Review the input and retry.','尚未保存，请核对输入后重试。'],
};
export function AssistantWorkflow({view,busy,canRevoke=false,onEvent,onUpload,onDirtyChange,onRefresh,sessionId=null,onClinicalChanged,onAccountIdentityChanged,onResumeDraft,onView,onOriginalUploadState,clientActions}:{view:WorkflowView;busy:boolean;canRevoke?:boolean;onEvent:WorkflowEventHandler;onUpload?:()=>void;onDirtyChange?:(dirty:boolean)=>void;onRefresh?:()=>void;sessionId?:string|null;onClinicalChanged?:(()=>void)|undefined;onAccountIdentityChanged?:(()=>void)|undefined;onResumeDraft?:()=>void|Promise<void>;onView?:(view:WorkflowView)=>void;onOriginalUploadState?:(task:string,active:boolean)=>void;clientActions?:SupportClientActions}){
 const {language,t}=useLanguage();
 const [editing,setEditing]=useState(false),[expanded,setExpanded]=useState(false);
 const [reviewHidden,setReviewHidden]=useState(false);
 useEffect(()=>{setReviewHidden(false);},[view.result_ref?.id,view.result_ref?.version]);
 useEffect(()=>{onDirtyChange?.(editing);},[editing,onDirtyChange]);
 useEffect(()=>()=>onDirtyChange?.(false),[onDirtyChange]);
 const say=(en:string,zh:string)=>language==='zh'?zh:en;
 const label=(key:string)=>labels[key]?.[language==='zh'?1:0]??say('Continue reviewing this step.','请继续核对这一步。');
 const event=(kind:WorkflowEvent['kind'])=>onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind,values:{}});
 const terminal=view.state==='cancelled'||view.state==='completed';
 const medicationRead=view.capability_id==='medication.plan.view'||view.capability_id==='medication.setup.list';
 const care=careCapabilities.has(view.capability_id);
 const support=supportCapabilities.has(view.capability_id),feedback=view.capability_id==='feedback.submit';
 const settings=settingsCapabilities.has(view.capability_id),account=accountCapabilities.has(view.capability_id);
 const settingsRead=['profile.view','caregiver.list'].includes(view.capability_id);
 const notificationDevice=notificationDevices.has(view.capability_id);
 const reminderChange=reminderChanges.has(view.capability_id);
 const media=mediaCapabilities.has(view.capability_id)||reminderReads.has(view.capability_id);
 const recordRead=recordCapabilities.has(view.capability_id);
 const historicalReport=view.capability_id==='dose.late.review'||view.capability_id==='dose.correction.review';
 const patientReport=view.capability_id==='dose.report'||view.capability_id==='dose.prn.report';
 const planChange=view.capability_id==='medication.plan.change';
 const recovery=view.capability_id==='medication.draft.resume';
 const enrollment=view.capability_id==='medication.enroll'||recovery||planChange;
 const source=view.capability_id==='medication.source.add'||view.capability_id==='medication.source.review';
 const original=view.visible_fields.original_plan;
 const originalPlan=planChange&&original&&typeof original==='object'&&!Array.isArray(original)?original:null;
 const originalRule=originalPlan?.frequency_rule;
 const originalTimes=originalRule&&typeof originalRule==='object'&&!Array.isArray(originalRule)&&Array.isArray(originalRule.local_times)?originalRule.local_times.filter((time):time is string=>typeof time==='string').join(', '):'';
 const collectEvent:WorkflowEventHandler=event=>{
  if(planChange&&event.kind==='provide_fields'){
   const current=view.visible_fields.change_inputs;
   if(!current||typeof current!=='object'||Array.isArray(current))throw new Error('Reopen the recorded plan before editing.');
   return onEvent({...event,values:{details:{...current,...event.values}}});
  }
  if(!recovery||event.kind!=='provide_fields')return onEvent(event);
  const current=view.visible_fields.recovery_inputs;
  if(!current||typeof current!=='object'||Array.isArray(current))throw new Error('Reopen the current draft before editing its details.');
  return onEvent({...event,values:{details:{...current,...event.values}}});
 };
 const fieldAction=view.actions.find(action=>action.kind==='fields'&&action.schema_id==='medication.enroll:v1');
 const formFields=planChange?['dose_amount','dose_unit','frequency_rule','course_start_date','course_end_date']:fieldAction?.kind==='fields'?fieldAction.field_names:['medication_name','dose_amount','dose_unit','frequency_rule','course_start_date','course_end_date'];
 return <section className="assistant-workflow" aria-label={say('Current task','当前办理任务')}>
  <p role="status">{view.storage_state==='ephemeral'?say('Details stay on this page. Refreshing loses them.','资料仅保留在当前页面，刷新后将丢失。'):view.storage_state==='saved'?say('Task progress saved.','已保存办理进度。'):view.storage_state==='cleanup_pending'?say('Removal is still in progress.','仍在清理待删除资料。'):say('Task progress has not been saved.','办理进度尚未保存。')}</p>
  {view.cleanup_pending&&view.storage_state!=='cleanup_pending'?<p role="status">{say('Some originals are still waiting for cleanup.','部分原图仍待清理。')}</p>:null}
  {view.protected_originals?<p>{say('Referenced originals were retained.','存在记录引用的原图已保留。')}</p>:null}
  <p>{label(view.state==='outcome_unknown'&&view.prompt_key!=='assistant.medication.deletion_unknown'?'assistant.workflow.interrupted':view.prompt_key)}</p>
  {medicationRead||view.capability_id==='medication.plan.end'||view.capability_id==='medication.draft.delete'?<AssistantMedicationActions key={view.task_id} view={view} busy={busy} onEvent={onEvent} onClinicalChanged={onClinicalChanged} onRefresh={onRefresh}/>:null}
  {!terminal&&view.state!=='suspended'&&view.capability_id==='medication.knowledge'?<Suspense fallback={<p role="status">{say('Loading query...','\u6b63\u5728\u52a0\u8f7d\u67e5\u8be2...')}</p>}><AssistantKnowledgeActions key={view.task_id} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing}/></Suspense>:null}
  {care?<Suspense fallback={<p role="status">{say('Loading care records...','\u6b63\u5728\u52a0\u8f7d\u5173\u6000\u8bb0\u5f55...')}</p>}><AssistantCareActions key={view.task_id} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing} onClinicalChanged={onClinicalChanged}/></Suspense>:null}
  {mediaCapabilities.has(view.capability_id)&&!terminal&&view.state!=='suspended'?<Suspense fallback={<p role="status">{say('Loading files...','正在加载文件...')}</p>}><AssistantMediaActions key={`${view.task_id}:${view.revision}`} view={view} busy={busy} onEvent={onEvent}/></Suspense>:null}
  {support?<Suspense fallback={<p role="status">{say('Loading conversation tools...','正在加载会话工具...')}</p>}><AssistantSupportActions key={`${view.task_id}:${view.revision}`} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing} clientActions={clientActions}/></Suspense>:null}
  {feedback?<Suspense fallback={<p role="status">{say('Loading feedback...','正在加载反馈...')}</p>}><AssistantFeedbackActions key={`${view.task_id}:${view.revision}`} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing}/></Suspense>:null}
  {settings?<Suspense fallback={<p role="status">{say('Loading settings...','正在加载设置...')}</p>}><AssistantSettingsActions key={`${view.task_id}:${view.revision}`} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing} onClinicalChanged={onClinicalChanged}/></Suspense>:null}
  {account?<Suspense fallback={<p role="status">{say('Loading secure form...','正在加载安全表单...')}</p>}><AssistantAccountActions key={`${view.task_id}:${view.revision}`} view={view} busy={busy} onDirtyChange={setEditing} onIdentityChanged={onAccountIdentityChanged}/></Suspense>:null}
  {notificationDevice?<Suspense fallback={<p role="status">{say('Loading device controls...','正在加载设备操作...')}</p>}><AssistantNotificationActions key={view.task_id} view={view} busy={busy} onDirtyChange={setEditing}/></Suspense>:null}
  {reminderChange?<Suspense fallback={<p role="status">{say('Loading reminder details...','正在加载提醒资料...')}</p>}><AssistantReminderChanges key={`${view.task_id}:${view.revision}`} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing} onClinicalChanged={onClinicalChanged}/></Suspense>:null}
  {reminderReads.has(view.capability_id)?<Suspense fallback={<p role="status">{say('Loading reminder options...','正在加载提醒选项...')}</p>}><AssistantReminderActions key={view.task_id} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing}/></Suspense>:null}
  {view.capability_id==='source.preview'?<Suspense fallback={<p role="status">{say('Loading source preview...','正在加载来源预览...')}</p>}><AssistantSourcePreview key={view.task_id} view={view} busy={busy} onEvent={onEvent} onView={onView} onOriginalUploadState={onOriginalUploadState} onDirtyChange={setEditing}/></Suspense>:null}
  {view.capability_id==='image.compare'?<Suspense fallback={<p role="status">{say('Loading photo check...','正在加载照片比对...')}</p>}><AssistantImageCompare key={view.task_id} view={view} busy={busy} onEvent={onEvent} onView={onView} onOriginalUploadState={onOriginalUploadState} onDirtyChange={setEditing}/></Suspense>:null}
  {view.capability_id==='library.pdf.add'?<Suspense fallback={<p role="status">{say('Loading PDF upload...','正在加载 PDF 上传...')}</p>}><AssistantPdfUpload key={view.task_id} view={view} busy={busy} onEvent={onEvent} onView={onView} onOriginalUploadState={onOriginalUploadState} onDirtyChange={setEditing} onClinicalChanged={onClinicalChanged}/></Suspense>:null}
  {view.capability_id==='gallery.photo.add'?<Suspense fallback={<p role="status">{say('Loading photo upload...','正在加载照片上传...')}</p>}><AssistantPhotoUpload key={view.task_id} view={view} busy={busy} onEvent={onEvent} onView={onView} onOriginalUploadState={onOriginalUploadState} onDirtyChange={setEditing} onClinicalChanged={onClinicalChanged}/></Suspense>:null}
  {mediaChanges.has(view.capability_id)?<Suspense fallback={<p role="status">{say('Loading file review...','正在加载文件核对...')}</p>}><AssistantMediaLifecycle key={`${view.task_id}:${view.revision}`} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing} onClinicalChanged={onClinicalChanged}/></Suspense>:null}
  {recordRead?<Suspense fallback={<p role="status">{say('Loading records…','正在加载记录…')}</p>}><AssistantRecordActions key={view.task_id} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing}/></Suspense>:null}
  {patientReport&&view.state==='completed'?<p>{String(view.visible_fields.medication_name??'')}: {t(intakeStatusWords(String(view.visible_fields.intake_status)))}</p>:null}
  {!terminal&&view.state!=='suspended'?view.actions.map((action,index)=>{
   switch(action.kind){
    case 'choice':if(support)return null;return <div className="actions" key={index}>{action.options.filter(option=>action.action_id==='enrollment.method'&&(option.value==='manual'||option.value==='photo')||action.action_id==='enrollment.duplicate'&&(option.value==='different_product'||option.value==='distinct_product'||Boolean(option.label_text?.trim()))||action.action_id==='enrollment.source_product'&&Boolean(option.label_text?.trim())||(action.action_id==='medication.target'||action.action_id==='medication.end_target'||action.action_id==='medication.delete_target'||action.action_id==='medication.resume_target'||action.action_id==='medication.change_target')&&Boolean(option.label_text?.trim())||recordRead&&(action.action_id==='record.medication'||action.action_id==='record.course')&&Boolean(option.label_text?.trim())||recordRead&&action.action_id==='record.page'||patientReport&&action.action_id==='report.target'&&Boolean(option.label_text?.trim())||care&&action.action_id.startsWith('care.')||historicalReport&&(action.action_id==='late.target'||action.action_id==='late.page')||patientReport&&action.action_id==='report.page'||action.action_id==='medication.page'||source&&action.action_id==='source.target'&&Boolean(option.label_text?.trim())||source&&action.action_id==='source.page').map(option=><button key={option.value} disabled={busy||editing} onClick={()=>onEvent(workflowChoice(view,action,option.value))}>{label(option.label_key)}{option.label_text?`: ${option.label_text}`:''}</button>)}</div>;
    case 'upload':return <div key={index}><button disabled={busy||!onUpload} onClick={onUpload}>{say('Choose a photo','选择照片')}</button>{!onUpload?<p>{say('Photo upload is unavailable. Try again later.','暂时无法上传照片，请稍后重试。')}</p>:null}</div>;
    case 'fields':if(feedback||support)return null;return action.schema_id==='medication.enroll:v1'?null:<p key={index}>{say('This input form is currently unavailable.','当前无法打开这项输入表单。')}</p>;
    case 'resume_task':return (recovery&&action.owned_ref.kind==='regimen'||source&&action.owned_ref.kind==='enrollment_task')&&view.save_mode==='allowed'&&action.owned_ref.version===action.expected_version?<button key={index} disabled={busy||editing||!onResumeDraft} onClick={()=>void onResumeDraft?.()}>{say('Continue original enrollment','继续原登记任务')}</button>:null;
    case 'existing_review':if(care||reminderChange||settings||feedback)return null;if(historicalReport&&action.component_key==='existing_late_report'&&view.save_mode==='allowed'&&view.result_ref?.id===action.owned_ref.id&&action.owned_ref.kind==='dose_occurrence'&&view.result_ref.version===action.expected_version)return <Suspense key={index} fallback={<p role="status">{say('Loading review...','\u6b63\u5728\u52a0\u8f7d\u6838\u5bf9...')}</p>}><AssistantLateReportActions key={`${view.task_id}:${action.owned_ref.id}`} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing} onClinicalChanged={onClinicalChanged}/></Suspense>;if(patientReport&&action.component_key==='existing_self_report'&&view.save_mode==='allowed'&&view.result_ref?.id===action.owned_ref.id&&action.owned_ref.kind==='regimen'&&view.result_ref.version===action.expected_version)return <Suspense key={index} fallback={<p role="status">{say('Loading report review...','\u6b63\u5728\u52a0\u8f7d\u81ea\u8ff0\u6838\u5bf9...')}</p>}><AssistantDoseReportActions key={`${view.task_id}:${action.owned_ref.id}`} view={view} busy={busy} onEvent={onEvent} onDirtyChange={setEditing} onClinicalChanged={onClinicalChanged}/></Suspense>;return source&&action.component_key==='existing_source_review'?<Suspense key={index} fallback={<p role="status">{say('Loading review...','\u6b63\u5728\u52a0\u8f7d\u6838\u5bf9\u2026')}</p>}><AssistantSourceActions key={view.task_id} view={view} busy={busy} onEvent={onEvent} onClinicalChanged={onClinicalChanged} onDirtyChange={setEditing} onUpload={onUpload}/></Suspense>:action.component_key==='existing_activation'&&(enrollment||source)&&view.save_mode==='allowed'&&action.owned_ref.kind==='regimen'&&view.result_ref?.id===action.owned_ref.id&&view.result_ref.version===action.expected_version&&!reviewHidden?<Suspense key={index} fallback={<p role="status">{say('Loading review…','正在加载核对…')}</p>}><EnrollScreen key={`${view.task_id}:${view.revision}:${action.owned_ref.id}:${action.expected_version}`} sessionId={sessionId} medications={null} preparedReview={{regimenId:action.owned_ref.id,version:action.expected_version,workflow:{task_id:view.task_id,expected_revision:view.revision}}} onReviewBack={()=>{setReviewHidden(true);setExpanded(true);}} onChanged={async()=>{await event('report_business_result');onClinicalChanged?.();}}/></Suspense>:null;
    default:return media||notificationDevice||account||support?null:<p key={index}>{say('This action is currently unavailable.','当前无法执行此操作。')}</p>;
   }
  }):null}
  {originalPlan&&!terminal?<div role="region" aria-label={say('Original recorded plan','原登记计划')}>
   <p>{say('Original recorded plan','原登记计划')} · v{String(originalPlan.version_no)}</p>
   <dl><dt>{say('Amount per dose','每次用量')}</dt><dd>{String(originalPlan.dose_amount??'—')} {String(originalPlan.dose_unit??'')}</dd>
    <dt>{say('Recorded times','原登记时间')}</dt><dd>{originalPlan.is_prn?say('Only when needed','按需服用'):originalTimes||say('See original instructions','请查看原说明')}</dd>
    {originalPlan.course_start_date||originalPlan.course_end_date?<><dt>{say('Recorded course','原登记疗程')}</dt><dd>{String(originalPlan.course_start_date??'—')} – {String(originalPlan.course_end_date??'—')}</dd></>:null}
   </dl>
   {view.state!=='failed_recoverable'?<p>{originalPlan.state==='active'?say('The original plan remains active until you review and separately confirm the new version.','在您核对并单独确认新版本之前，原计划会继续保持启用。'):say('This creates a new course draft. It does not resume a past plan automatically.','这会准备新的疗程草稿，不会自动恢复过去的计划。')}</p>:null}
  </div>:null}
  {!terminal&&enrollment&&view.visible_fields.method?<div hidden={!fieldAction&&!editing&&!expanded}>
   <AssistantEnrollmentFields fixedIdentity={planChange} key={view.task_id} view={view} fieldNames={formFields} busy={busy||view.state==='suspended'||view.state==='outcome_unknown'} onEvent={collectEvent} onDirtyChange={setEditing}/>
  </div>:null}
  {view.state==='ready_for_review'&&!fieldAction&&enrollment?<button disabled={busy} onClick={()=>setExpanded(value=>!value)}>{say('Edit details','修改资料')}</button>:null}
  {!terminal&&view.state!=='suspended'&&!view.result_ref&&view.capability_id==='medication.enroll'&&view.visible_fields.method?<button disabled={busy||editing} onClick={()=>onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'choose_method',values:{method:view.visible_fields.method==='photo'?'manual':'photo'}})}>{view.visible_fields.method==='photo'?say('Switch to manual entry','改为手动录入'):say('Switch to photo entry','改为拍照录入')}</button>:null}
  {view.state==='ready_for_review'&&view.save_mode==='allowed'&&enrollment?<button disabled={busy||editing} onClick={async()=>{await event('prepare_confirmation');onClinicalChanged?.();}}>{say('Review this medication','核对这项药物')}</button>:null}
  {source&&view.state==='ready_for_review'&&view.save_mode==='allowed'?<button disabled={busy||editing} onClick={()=>event('prepare_confirmation')}>{say('Review medication source','核对药物来源')}</button>:null}
  {feedback&&view.state==='ready_for_review'&&view.save_mode==='allowed'?<button disabled={busy||editing} onClick={()=>event('prepare_confirmation')}>{say('Prepare feedback review','准备反馈核对')}</button>:null}
  {settings&&view.state==='ready_for_review'&&view.save_mode==='allowed'?<button disabled={busy||editing} onClick={()=>event('prepare_confirmation')}>{say('Prepare settings review','准备设置核对')}</button>:null}
  {reminderChange&&view.state==='ready_for_review'&&view.save_mode==='allowed'?<button disabled={busy||editing} onClick={()=>event('prepare_confirmation')}>{say('Prepare reminder review','准备提醒核对')}</button>:null}
  {care&&view.state==='ready_for_review'&&view.save_mode==='allowed'?<button disabled={busy||editing} onClick={()=>event('prepare_confirmation')}>{say('Prepare care review','\u51c6\u5907\u5173\u6000\u6838\u5bf9')}</button>:null}
  {historicalReport&&view.state==='ready_for_review'&&view.save_mode==='allowed'?<button disabled={busy||editing} onClick={()=>event('prepare_confirmation')}>{say('Prepare historical review','\u51c6\u5907\u5386\u53f2\u6838\u5bf9')}</button>:null}
  {patientReport&&view.state==='ready_for_review'&&view.save_mode==='allowed'?<button disabled={busy||editing} onClick={()=>event('prepare_confirmation')}>{say('Review dose report','核对服药自述')}</button>:null}
  {reviewHidden&&view.state==='awaiting_confirmation'?<button disabled={busy||editing} onClick={()=>{setReviewHidden(false);setExpanded(false);}}>{say('Return to saved draft review','返回已保存草稿的核对')}</button>:null}
  {editing?<p>{say('Apply or undo the unsent details before continuing.','请先使用或撤回尚未提交的资料，再继续其他操作。')}</p>:null}
  {!terminal?<div className="actions">
   {onRefresh?<button disabled={busy} onClick={onRefresh}>{say('Check task status','核查办理状态')}</button>:null}
   {view.save_mode==='allowed'&&view.prompt_key==='assistant.enrollment.check_preparation'?<button disabled={busy||editing} onClick={()=>event('report_business_result')}>{say('Check prepared draft result','核查已准备的草稿结果')}</button>:null}
   {view.save_mode==='ephemeral'?['gallery.photo.add','library.pdf.add','image.compare','source.preview'].includes(view.capability_id)?null:<button disabled={busy||editing} onClick={()=>event('allow_save')}>{medicationRead||recordRead||media||settingsRead?say('Save this query','保存本次查询'):view.capability_id==='medication.enroll'||source?say('Save this medication and continue review','现在保存药物并继续核对'):say('Save this task and continue review','保存本次任务并继续核对')}</button>:<button disabled={busy&&!canRevoke} onClick={()=>event('cancel_save')}>{say('Do not save this workflow','不保存本次办理')}</button>}
   {view.save_mode==='allowed'&&view.storage_state==='save_failed'?<button disabled={busy} onClick={()=>event('allow_save')}>{say('Retry saving task','重试保存任务')}</button>:null}
   {view.save_mode==='ephemeral'&&view.state==='outcome_unknown'?<button disabled={busy} onClick={()=>event('retry')}>{say('Recover interrupted task','恢复中断的办理')}</button>:null}
   <button disabled={busy||editing&&view.state!=='suspended'||view.prompt_key==='assistant.enrollment.check_preparation'} onClick={()=>event(view.state==='suspended'?'resume':'pause')}>{view.state==='suspended'?say('Resume task','继续办理'):say('Pause task','暂停办理')}</button>
  </div>:null}
  {!terminal&&view.save_mode==='ephemeral'&&!['gallery.photo.add','library.pdf.add','image.compare','source.preview'].includes(view.capability_id)?<p>{medicationRead||recordRead||media||settingsRead||view.capability_id==='medication.knowledge'?say('Saving keeps this query as a task. It does not change medication records.','保存后将保留本次查询任务，不会修改药物记录。'):reminderChange?say('Saving keeps this reminder draft. Apply the details, then review and confirm separately.','保存后将保留提醒草稿，请使用资料，再独立核对并确认。'):settings?say('Saving keeps this settings draft. The change still needs separate review and confirmation.','保存后将保留设置草稿，变更仍需单独核对与确认。'):feedback?say('Saving keeps this feedback draft. Submission still needs separate review and confirmation.','保存后会保留反馈草稿，提交仍需单独核对并确认。'):support?say('Saving keeps this support task. Device and conversation actions still need your explicit operation.','保存后会保留此支持任务，设备和会话动作仍需您手动操作。'):account?say('Account secrets stay in the secure form. Saving this task does not save them.','账户秘密仅留在安全表单中，保存此任务不会保存这些秘密。'):say('Saving keeps these details as a draft. The plan still needs review and separate confirmation.','保存后将保留草稿资料，用药计划仍需核对并单独确认。')}</p>:null}
 </section>;
}
