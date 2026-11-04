// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {workflowApi,type KnowledgeQueryResult,type WorkflowView} from '../api/assistantWorkflows';
import {AssistantWorkflow} from './AssistantWorkflow';

afterEach(()=>{cleanup();vi.restoreAllMocks();});
const view:WorkflowView={task_id:'DEMO-knowledge',revision:2,capability_id:'medication.knowledge',state:'ready_for_review',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.knowledge.ready',input_fields:{medication_name:'ibuprofen'},visible_fields:{medication_name:'ibuprofen',name_resolution:{status:'resolved',candidates:[]}},missing_fields:[],actions:[],explanations:[],result_ref:null};
const result:KnowledgeQueryResult={clarification_required:false,medication_id:null,regimen_id:null,question:'general_use',medication_name:'IBUPROFEN',patient_safe_summary:'DEMO sourced general-use summary',personal_instructions:null,personal_indication:null,explanations:[{operation_key:'knowledge.lookup',outcome:'partial',source_name:'openFDA / SPL',source_refs:[],reason_key:null,count:null}],general_knowledge:{status:'matched',reason:'DEMO-partial',match_scope:'US_label_ingredient',candidate_count:1,use_statement:'DEMO source excerpt',use_statement_zh:null,translation_status:'original_english_only',personal_dosing_authority:false,regulatory_note:'DEMO coverage',sources:[{source_name:'openFDA Drug Label / SPL',market:'US',set_id:'DEMO-set',label_id:'DEMO-label',version:'1',effective_time:'20261001',retrieved_at:'2026-10-27T12:00Z',url:'https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=DEMO',api_url:'https://api.fda.gov/drug/label.json',sections:[{field:'purpose',text:'DEMO original source text',truncated:false}]}]}};

it('waits for an explicit query and renders actual readable evidence and source links',async()=>{
 const ask=vi.spyOn(workflowApi,'knowledge').mockResolvedValue(result);
 render(<AssistantWorkflow view={view} busy={false} onEvent={vi.fn()}/>);
 const button=await screen.findByRole('button',{name:'Search medication knowledge'});expect(ask).not.toHaveBeenCalled();
 fireEvent.click(button);await screen.findByText(result.patient_safe_summary);
 expect(ask).toHaveBeenCalledWith(view.task_id,{expected_revision:2});
 expect(screen.getByText(/retrieved partial use evidence/)).toBeTruthy();
 fireEvent.click(screen.getByText('Knowledge sources'));expect(screen.getByRole('link').getAttribute('href')).toContain('dailymed.nlm.nih.gov');
});
it('requires an explicit current name suggestion and sends page-only input for no-save',async()=>{
 const ask=vi.spyOn(workflowApi,'knowledge').mockResolvedValue(result);
 render(<AssistantWorkflow view={{...view,save_mode:'ephemeral',input_fields:{medication_name:'ibuprofne'},visible_fields:{medication_name:'ibuprofne',name_resolution:{status:'needs_confirmation',candidates:[{id:'ingredient:ibuprofen',display_name:'IBUPROFEN'}]}}}} busy={false} onEvent={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Use IBUPROFEN and search'}));
 await waitFor(()=>expect(ask).toHaveBeenCalledWith(view.task_id,{expected_revision:2,candidate_id:'ingredient:ibuprofen',ephemeral:{capability_id:'medication.knowledge',fields:{medication_name:'ibuprofne'}}}));
});
it('keeps the name after a failed lookup and clears the prior answer when privacy changes',async()=>{
 const ask=vi.spyOn(workflowApi,'knowledge').mockRejectedValueOnce(new Error('DEMO network failure')).mockResolvedValue(result);
 const {rerender}=render(<AssistantWorkflow view={view} busy={false} onEvent={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Search medication knowledge'}));await screen.findByRole('alert');
 expect((screen.getByRole('textbox',{name:'Medicine name'}) as HTMLInputElement).value).toBe('ibuprofen');
 fireEvent.click(screen.getByRole('button',{name:'Search medication knowledge'}));await screen.findByText(result.patient_safe_summary);expect(ask).toHaveBeenCalledTimes(2);
 rerender(<AssistantWorkflow view={{...view,revision:3,save_mode:'ephemeral'}} busy={false} onEvent={vi.fn()}/>);
 await waitFor(()=>expect(screen.queryByText(result.patient_safe_summary)).toBeNull());
});
it('updates the typed name without querying and does not mount the query while suspended',async()=>{
 const ask=vi.spyOn(workflowApi,'knowledge'),send=vi.fn();
 const {rerender}=render(<AssistantWorkflow view={view} busy={false} onEvent={send}/>);
 fireEvent.change(await screen.findByRole('textbox',{name:'Medicine name'}),{target:{value:'IBUPROFEN'}});
 fireEvent.click(screen.getByRole('button',{name:'Apply medicine name'}));
 await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:{medication_name:'IBUPROFEN'}})));expect(ask).not.toHaveBeenCalled();
 rerender(<AssistantWorkflow view={{...view,state:'suspended'}} busy={false} onEvent={send}/>);
 expect(screen.queryByRole('button',{name:'Search medication knowledge'})).toBeNull();
});
