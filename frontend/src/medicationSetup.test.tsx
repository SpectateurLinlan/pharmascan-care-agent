// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import type {EvidenceTask,RegimenHistoryItem} from './api/client';
import {medicationSetupEntries} from './medicationSetup';
import {PendingEvidenceTasks} from './components/PendingEvidenceTasks';
afterEach(cleanup);
const source:EvidenceTask={id:'DEMO-source-task',medication_id:'DEMO-med',version:1,status:'pending_information',product:{name:'DEMO medication',strength:null,dose_form:null,formulation:null,brand:null,ingredients:[],category:'unknown',verification:'source_supplied'},source_ids:[],missing:['schedule'],conflicts:[],possible_duplicate_ids:[],draft_regimen_id:null,suggested_regimen:null};
const draft:RegimenHistoryItem={regimen_id:'DEMO-draft',display_name:'DEMO draft',version_no:1,state:'draft',effective_from:null,effective_to:null,medication_id:'DEMO-med',course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:[]};
it('keeps incomplete source tasks without a regimen and excludes completed source tasks',()=>{
 expect(medicationSetupEntries([source,{...source,id:'DEMO-done',status:'draft_created'}],[])).toEqual([{kind:'source',id:source.id,name:'DEMO medication',conflicting:false}]);
});
it('counts a linked open draft once and retains conflicts and independent drafts',()=>{
 const rows=medicationSetupEntries([{...source,status:'conflict',conflicts:['DEMO conflict'],draft_regimen_id:draft.regimen_id}],[draft,{...draft,regimen_id:'DEMO-other'},{...draft,regimen_id:'DEMO-active',state:'active'}]);
 expect(rows).toHaveLength(2);expect(rows[0]).toMatchObject({kind:'source',conflicting:true});expect(rows[1]).toMatchObject({kind:'draft',id:'DEMO-other'});
 expect(medicationSetupEntries([{...source,status:'draft_created',draft_regimen_id:draft.regimen_id}],[draft])).toEqual([{kind:'draft',id:draft.regimen_id,name:draft.display_name}]);
});
it('does not announce an empty list while loading or on a failed request',()=>{
 const props={onRetry:vi.fn(),onContinue:vi.fn(),onResume:vi.fn()};
 const view=render(<PendingEvidenceTasks {...props} entries={null} error={null}/>);
 expect(screen.getByRole('status').textContent).toContain('Loading');expect(screen.queryByText('No unfinished medication setup.')).toBeNull();
 view.rerender(<PendingEvidenceTasks {...props} entries={null} error={new Error('DEMO offline')}/>);
 expect(screen.queryByText('No unfinished medication setup.')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'Retry loading records'}));expect(props.onRetry).toHaveBeenCalledOnce();
});
it('routes a source-only registration and a saved draft to their respective executable flows',()=>{
 const onContinue=vi.fn(),onResume=vi.fn();
 render(<PendingEvidenceTasks entries={medicationSetupEntries([source],[draft])} error={null} onRetry={vi.fn()} onContinue={onContinue} onResume={onResume}/>);
 fireEvent.click(screen.getByRole('button',{name:/DEMO medication/}));expect(onContinue).toHaveBeenCalledWith(source.id);
 fireEvent.click(screen.getByRole('button',{name:/DEMO draft/}));expect(onResume).toHaveBeenCalledWith(draft.regimen_id);
});
