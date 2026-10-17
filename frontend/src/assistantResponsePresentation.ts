import type {ToolTrace} from './api/client';

export function answerExplanation(mode:string):string {
 if(mode==='gemini')return 'AI-assisted answer using verified application tools.';
 if(mode==='records_only')return 'This answer uses application tools and available sources, without AI-generated interpretation.';
 return 'This answer uses the available records and rules; AI is temporarily unavailable.';
}

/** Public action distinguishes education from the shared long-term read audit category. */
export function toolTraceLabel(trace:ToolTrace):string {
 return trace.tool_name==='get_long_term_care'&&trace.payload.action==='get_medication_understanding'
  ?'get_medication_understanding':trace.tool_name;
}
