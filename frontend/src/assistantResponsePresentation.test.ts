import {describe,it,expect} from 'vitest';
import {answerExplanation,toolTraceLabel,explanationStepsFromTrace,presentExplanation} from './assistantResponsePresentation';
import type {ToolTrace} from './api/client';

const trace:ToolTrace={tool_name:'get_long_term_care',status:'success',error_code:null,requires_confirmation:false,clarification_question:null,payload:{action:'get_medication_understanding'}};
describe('Assistant response provenance',()=>{
 it('does not describe guided workflow steps as an AI outage',()=>{
  expect(answerExplanation('workflow')).not.toContain('unavailable');
  expect(answerExplanation('workflow')).toContain('review');
 });
 it('does not infer an AI outage from a deliberate records-only response',()=>{
  expect(answerExplanation('records_only')).not.toContain('unavailable');
  expect(answerExplanation('records_only')).toContain('without AI-generated');
  expect(answerExplanation('gemini')).toContain('AI-assisted');
  expect(answerExplanation('deterministic_degraded')).toContain('temporarily unavailable');
 });
 it('shows medication education action without renaming other grouped reads or untrusted actions',()=>{
  expect(toolTraceLabel(trace)).toBe('get_medication_understanding');
  expect(toolTraceLabel({...trace,payload:{action:'get_inventory'}})).toBe('get_long_term_care');
  expect(toolTraceLabel({...trace,tool_name:'list_active_medications'})).toBe('list_active_medications');
 });
});

it('describes an unsupported name as not queried rather than a successful tool',()=>{
 const steps=explanationStepsFromTrace({...trace,payload:{action:'get_medication_understanding',general_knowledge:{status:'no_reliable_match',reason:'unsupported_search_name'}}});
 expect(steps[0]?.outcome).toBe('not_attempted');
 expect(presentExplanation(steps[0]!,'zh')).toContain('尚未查询');
 expect(presentExplanation(steps[0]!,'en')).not.toContain('success');
});

it('explains actual patient catalogue reads and failed public searches separately',()=>{
 const list=explanationStepsFromTrace({...trace,tool_name:'list_active_medications',payload:{medications:[{},{}]}});
 expect(presentExplanation(list[0]!,'zh')).toContain('正在服用');
 const lookup=explanationStepsFromTrace({...trace,payload:{action:'get_medication_understanding',general_knowledge:{status:'no_reliable_match',reason:'not_found'}}});
 expect(presentExplanation(lookup[0]!,'zh')).toContain('openFDA');
 expect(presentExplanation(lookup[0]!,'zh')).toContain('未找到');
});
