// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api,type EvidenceTask} from '../api/client';
import {workflowApi,type WorkflowView} from '../api/assistantWorkflows';
import {AssistantSourceActions} from './AssistantSourceActions';

afterEach(()=>{cleanup();vi.restoreAllMocks();localStorage.clear();});
const task:EvidenceTask={id:'DEMO-source',medication_id:'DEMO-med',version:2,status:'ready_for_review',product:{name:'DEMO medicine',strength:'200mg',dose_form:null,formulation:null,brand:null,manufacturer:null,ingredients:[],external_identifiers:{},category:'unknown',verification:'source_supplied'},source_ids:[],missing:[],conflicts:[],possible_duplicate_ids:[],draft_regimen_id:null,suggested_regimen:{medication_name:'DEMO medicine',dose_amount:1,dose_unit:'tablet',frequency_rule:{kind:'daily',local_times:['08:00'],days_of_week:[],every_hours:null},is_prn:false,food_instruction:null}};
const view:WorkflowView={task_id:'DEMO-task',revision:4,capability_id:'medication.source.add',state:'awaiting_confirmation',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.source.patient_review',visible_fields:{source_saved:true},missing_fields:[],actions:[{kind:'existing_review',component_key:'existing_source_review',owned_ref:{kind:'enrollment_task',id:'DEMO-source',version:2},expected_version:2}],result_ref:{kind:'enrollment_task',id:'DEMO-source',version:2},explanations:[]};
function sourceMocks(){
 vi.spyOn(workflowApi,'originals').mockResolvedValue([]);
 vi.spyOn(api,'evidenceTask').mockResolvedValue(task);vi.spyOn(api,'evidenceSources').mockResolvedValue([]);
 vi.spyOn(api,'reviewEvidence').mockResolvedValue({...task,status:'draft_created',version:3,draft_regimen_id:'DEMO-plan'});
 vi.spyOn(api,'requestChallenge').mockRejectedValue(new Error('Source preparation cannot activate'));
}
it('saves from a versioned preparation marker without loading an invented native registration',async()=>{
 sourceMocks();vi.mocked(workflowApi.originals).mockResolvedValue([{id:'DEMO-original',task_id:view.task_id,original_checksum:'a'.repeat(64),content_type:'image/png',byte_size:120,state:'saved',extraction_status:'succeeded',reason:null,cleanup_pending:false}]);
 const save=vi.spyOn(api,'saveEvidenceOriginal').mockResolvedValue(task),event=vi.fn();
 const marker={kind:'media_review' as const,id:view.task_id,version:view.revision};
 render(<AssistantSourceActions view={{...view,visible_fields:{source_saved:false,source_task_id:task.id},result_ref:marker,actions:[{kind:'existing_review',component_key:'existing_source_review',owned_ref:marker,expected_version:view.revision}]}} busy={false} onEvent={event}/>);
 const button=await screen.findByRole('button',{name:'Save this source and continue review'});
 await waitFor(()=>expect(button).toHaveProperty('disabled',false));fireEvent.click(button);
 await waitFor(()=>expect(save).toHaveBeenCalledWith(task.id,'DEMO-original',{task_id:view.task_id,expected_revision:view.revision}));
 expect(api.evidenceTask).not.toHaveBeenCalled();expect(api.evidenceSources).not.toHaveBeenCalled();
 await waitFor(()=>expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'report_business_result',values:{}})));
});
it('reuses source fields, requires acknowledgement, binds review and reports without requesting activation',async()=>{
 sourceMocks();const event=vi.fn();render(<AssistantSourceActions view={view} busy={false} onEvent={event}/>);
 await screen.findByRole('heading',{name:'DEMO medicine'});
 expect(screen.getByRole('button',{name:'Save reviewed source and continue'})).toHaveProperty('disabled',true);
 fireEvent.click(screen.getByLabelText('I reviewed these details against my medication instructions.'));
 fireEvent.click(screen.getByRole('button',{name:'Save reviewed source and continue'}));
 await waitFor(()=>expect(api.reviewEvidence).toHaveBeenCalledWith(task.id,expect.objectContaining({dose_amount:1}),false,{product_category:'unknown',replace_active_plan:false},{task_id:'DEMO-task',expected_revision:4}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'report_business_result',expected_revision:4,values:{}}));
 expect(api.requestChallenge).not.toHaveBeenCalled();expect(localStorage.length).toBe(0);
});
it('retains unsent form inputs when review fails and exposes retry with no activation',async()=>{
 sourceMocks();vi.mocked(api.reviewEvidence).mockRejectedValue(new Error('DEMO source unavailable'));
 render(<AssistantSourceActions view={view} busy={false} onEvent={vi.fn()}/>);
 await screen.findByRole('heading',{name:'DEMO medicine'});fireEvent.change(screen.getByLabelText('Dose amount'),{target:{value:'2'}});
 fireEvent.click(screen.getByLabelText('I reviewed these details against my medication instructions.'));
 fireEvent.click(screen.getByRole('button',{name:'Save reviewed source and continue'}));
 await screen.findByRole('alert');expect(screen.getByLabelText('Dose amount')).toHaveProperty('value','2');
 expect(screen.getByRole('button',{name:'Save reviewed source and continue'})).toHaveProperty('disabled',false);
});
it('saves only a selected successful original and reports the owned result',async()=>{
 vi.spyOn(workflowApi,'originals').mockResolvedValue([{id:'DEMO-original',task_id:'DEMO-task',state:'saved',extraction_status:'succeeded',content_type:'image/png',byte_size:10,original_checksum:'a'.repeat(64),reason:null,cleanup_pending:false}]);
 vi.spyOn(api,'saveEvidenceOriginal').mockResolvedValue(task);
 const event=vi.fn();render(<AssistantSourceActions view={{...view,visible_fields:{source_saved:false},result_ref:{...view.result_ref!,version:1},actions:[{kind:'existing_review',component_key:'existing_source_review',owned_ref:{...view.result_ref!,version:1},expected_version:1}]}} busy={false} onEvent={event}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Save this source and continue review'}));
 await waitFor(()=>expect(api.saveEvidenceOriginal).toHaveBeenCalledWith('DEMO-source','DEMO-original',{task_id:'DEMO-task',expected_revision:4}));
 expect(event).toHaveBeenCalledWith(expect.objectContaining({kind:'report_business_result',values:{}}));
});
it('does not read or write patient source APIs for an initially unsaved task',()=>{
 sourceMocks();render(<AssistantSourceActions view={{...view,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={vi.fn()}/>);
 expect(api.evidenceTask).not.toHaveBeenCalled();expect(api.reviewEvidence).not.toHaveBeenCalled();
 expect(screen.queryByRole('button',{name:'Save reviewed source and continue'})).toBeNull();
});
it('lets a saved registration explicitly add a successful additional original without recreating a plan',async()=>{
 sourceMocks();vi.mocked(workflowApi.originals).mockResolvedValue([{id:'DEMO-more',task_id:'DEMO-task',state:'saved',extraction_status:'succeeded',content_type:'image/png',byte_size:10,original_checksum:'a'.repeat(64),reason:null,cleanup_pending:false}]);
 const saved=vi.spyOn(api,'saveEvidenceOriginal').mockResolvedValue({...task,version:3});const upload=vi.fn();
 render(<AssistantSourceActions view={view} busy={false} onEvent={vi.fn()} onUpload={upload}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Add another source'}));expect(upload).toHaveBeenCalledOnce();
 fireEvent.click(screen.getByRole('button',{name:'Save selected additional source'}));
 await waitFor(()=>expect(saved).toHaveBeenCalledWith('DEMO-source','DEMO-more',{task_id:'DEMO-task',expected_revision:4}));
 expect(api.reviewEvidence).not.toHaveBeenCalled();expect(api.requestChallenge).not.toHaveBeenCalled();
});
