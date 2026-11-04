import type {ToolTrace} from './api/client';
import type {ExplanationStep} from './api/assistantWorkflows';

export function answerExplanation(mode:string):string {
 if(mode==='workflow')return "The assistant is following the app's guided process. You will review any changes that require confirmation.";
 if(mode==='gemini')return 'AI-assisted answer using verified application tools.';
 if(mode==='records_only')return 'This answer uses application tools and available sources, without AI-generated interpretation.';
 return 'This answer uses the available records and rules; AI is temporarily unavailable.';
}

/** Public action distinguishes education from the shared long-term read audit category. */
export function toolTraceLabel(trace:ToolTrace):string {
 return trace.tool_name==='get_long_term_care'&&trace.payload.action==='get_medication_understanding'
  ?'get_medication_understanding':trace.tool_name;
}

export function explanationStepsFromTrace(trace:ToolTrace):ExplanationStep[] {
 const knowledge=trace.payload.general_knowledge;
 const step:ExplanationStep={operation_key:'application.check',outcome:trace.status==='success'?'success':'failed',source_name:null,source_refs:[],reason_key:null,count:null};
 if(knowledge&&typeof knowledge==='object'&&'status' in knowledge&&'reason' in knowledge){
  const reason=typeof knowledge.reason==='string'?knowledge.reason:'';
  const skipped=['unsupported_search_name','missing_form_route_or_release','name_not_resolved'].includes(reason);
  const partial='coverage' in knowledge&&knowledge.coverage==='partial';
  return [{...step,operation_key:'knowledge.lookup',reason_key:reason,source_name:skipped?null:'openFDA / SPL',
   outcome:skipped?'not_attempted':knowledge.status==='unavailable'?'unavailable':knowledge.status==='matched'?(partial?'partial':'success'):reason==='not_found'?'not_found':'failed'}];
 }
 if(trace.payload.name_resolution&&typeof trace.payload.name_resolution==='object'){
  return [{...step,operation_key:'knowledge.lookup',outcome:'not_attempted',reason_key:'name_not_resolved'}];
 }
 if(trace.tool_name==='list_active_medications'){
  const nested=trace.payload.payload;
  const rows=trace.payload.medications??(nested&&typeof nested==='object'&&'medications' in nested?nested.medications:null);
  return [{...step,operation_key:'medications.list',count:Array.isArray(rows)?rows.length:null}];
 }
 if(trace.tool_name==='get_medication_understanding'||trace.payload.action==='get_medication_understanding'){
  return [{...step,operation_key:'medications.reviewed_instructions'}];
 }
 return [step];
}

export function presentExplanation(step:ExplanationStep,language:'en'|'zh'):string {
 const zh=language==='zh';
 if(step.operation_key==='knowledge.lookup'){
  if(step.outcome==='not_attempted')return zh?'尚未查询公共药品资料库：请先确认药名或补充产品信息。':'The public label search has not run. Confirm the medicine name or provide product information first.';
  if(step.outcome==='not_found')return zh?'查询了 openFDA / SPL，本次未找到匹配标签。':'Searched openFDA / SPL; this query found no matching label.';
  if(step.outcome==='unavailable')return step.reason_key==='timeout'||step.reason_key==='request_budget_exceeded'
   ?(zh?'查询 openFDA / SPL 超时，尚未取得可用资料。':'The openFDA / SPL lookup timed out; usable information was not retrieved.')
   :(zh?'尝试查询 openFDA / SPL，但资料服务暂时不可用。':'Attempted the openFDA / SPL lookup, but the information service is unavailable.');
  if(step.outcome==='partial')return zh?'查询了 openFDA / SPL，取得部分带适用范围的用途资料；详见来源原文。':'Searched openFDA / SPL and retrieved partial use evidence with source-specific limits; see the original excerpts.';
  if(step.outcome==='success')return zh?'查询了 openFDA / SPL，取得有来源的一般用途资料。':'Searched openFDA / SPL and retrieved sourced general-use information.';
  return ['true_scope_conflict','conflicting_label_uses','duplicate_version_conflict'].includes(step.reason_key??'')
   ?(zh?'查询了 openFDA / SPL，但标签证据存在冲突，未采用相关结论。':'Searched openFDA / SPL; conflicting label evidence prevented a reliable conclusion.')
   :(zh?'查询了 openFDA / SPL，但资料不足以确认成分或适用范围。':'Searched openFDA / SPL; the evidence did not establish the ingredient or use scope.');
 }
 if(step.operation_key==='medications.list')return step.outcome==='success'
  ?(zh?`查询了您当前正在服用的药物${step.count===null?'':`（${step.count} 项）`}。`:`Checked your current medication list${step.count===null?'':` (${step.count} entries)`}.`)
  :(zh?'未能读取您当前的药物清单。':'Your current medication list could not be read.');
 if(step.operation_key==='medications.reviewed_instructions')return step.outcome==='success'
  ?(zh?'检查了当前药物记录中已核对的服药指示。':'Checked the reviewed instructions in your current medication record.')
  :(zh?'未能读取已核对的服药指示。':'The reviewed medication instructions could not be read.');
 return step.outcome==='success'?(zh?'已完成应用资料检查。':'Completed an application information check.')
  :(zh?'应用资料检查未完成。':'The application information check did not complete.');
}
