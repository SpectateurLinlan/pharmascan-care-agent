import {describe,it,expect} from 'vitest';
import {answerExplanation,toolTraceLabel} from './assistantResponsePresentation';
import type {ToolTrace} from './api/client';

const trace:ToolTrace={tool_name:'get_long_term_care',status:'success',error_code:null,requires_confirmation:false,clarification_question:null,payload:{action:'get_medication_understanding'}};
describe('Assistant response provenance',()=>{
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
