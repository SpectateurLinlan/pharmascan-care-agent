// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import type {WorkflowView} from '../api/assistantWorkflows';
import type {StockStatus} from '../api/care';
import {AssistantWorkflow} from './AssistantWorkflow';

afterEach(()=>{cleanup();vi.restoreAllMocks();});
const id='00000000-0000-4000-8000-000000000099';
const stock={id,kind:'count',quantity:12,unit:'tablet',low_threshold:7,note:'DEMO reviewed note',confirmed:false};
const view:WorkflowView={task_id:'DEMO-care',revision:2,capability_id:'inventory.count',state:'awaiting_confirmation',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.care.patient_review',input_fields:{medication_id:id,quantity:12,unit:'tablet'},visible_fields:{target_name:'DEMO selected medicine',care_review:{target_id:id,payload:stock},proposal:{action:'stock',medication_id:id,stock}},missing_fields:[],actions:[{kind:'existing_review',component_key:'existing_care_review',owned_ref:{kind:'care_review',id,version:1},expected_version:1}],explanations:[],result_ref:{kind:'care_review',id,version:1}};

it('uses separate patient confirmation with current task headers and no mount write',async()=>{
 const write=vi.spyOn(api,'recordStock').mockResolvedValue({medication_id:id,transactions:[]} as unknown as StockStatus);
 const send=vi.fn().mockResolvedValue({...view,revision:3,state:'completed'});
 render(<AssistantWorkflow view={view} busy={false} onEvent={send}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review care record'}));expect(write).not.toHaveBeenCalled();
 expect(screen.getByRole('dialog').textContent).toContain('DEMO selected medicine');
 expect((screen.getByRole('spinbutton',{name:'Quantity'}) as HTMLInputElement).readOnly).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'Confirm record'}));
 await waitFor(()=>expect(write).toHaveBeenCalledWith(id,{...stock,confirmed:true},{task_id:view.task_id,expected_revision:2}));
 await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'report_business_result',values:{}})));
});
it('cancels without a write and hides an old review when saving is prohibited',async()=>{
 const write=vi.spyOn(api,'recordStock'),send=vi.fn();const {rerender}=render(<AssistantWorkflow view={view} busy={false} onEvent={send}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review care record'}));fireEvent.click(screen.getByRole('button',{name:'Cancel'}));expect(write).not.toHaveBeenCalled();
 rerender(<AssistantWorkflow view={{...view,save_mode:'ephemeral'}} busy={false} onEvent={send}/>);
 expect(screen.queryByRole('button',{name:'Review care record'})).toBeNull();
});
it('retains the reviewed draft on a lost response and checks actual result before retry',async()=>{
 const write=vi.spyOn(api,'recordStock').mockRejectedValue(new Error('DEMO response lost')),send=vi.fn();
 render(<AssistantWorkflow view={view} busy={false} onEvent={send}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Review care record'}));fireEvent.click(screen.getByRole('button',{name:'Confirm record'}));
 fireEvent.click(await screen.findByRole('button',{name:'Check care result'}));
 await waitFor(()=>expect(send).toHaveBeenCalled());expect(write).toHaveBeenCalledOnce();
 expect((screen.getByRole('textbox',{name:'Your note'}) as HTMLTextAreaElement).value).toBe(stock.note);
});
it('collects missing stock data as typed draft fields without writing stock',async()=>{
 const send=vi.fn(),write=vi.spyOn(api,'recordStock');render(<AssistantWorkflow view={{...view,state:'collecting',actions:[],result_ref:null,input_fields:{medication_id:id,kind:'count',low_threshold:7,note:''},visible_fields:{medications:[{id,name:'DEMO medicine'}],regimens:[],timezone:'Asia/Singapore'},missing_fields:['quantity','unit']}} busy={false} onEvent={send}/>);
 fireEvent.change(await screen.findByRole('spinbutton',{name:'Quantity'}),{target:{value:'12'}});
 fireEvent.click(screen.getByRole('button',{name:'Apply care details'}));
 await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:expect.objectContaining({quantity:12,unit:'tablet'})})));expect(write).not.toHaveBeenCalled();
});
it('preserves the original observation instant when its visible minute fields were not edited',async()=>{
 const occurred='2026-10-27T10:23:45.123456Z',send=vi.fn();
 render(<AssistantWorkflow view={{...view,capability_id:'observation.edit',state:'collecting',result_ref:null,actions:[],input_fields:{observation_id:id},missing_fields:['description','occurred_at'],visible_fields:{observation:{description:'DEMO original note',occurred_at:occurred,kind:'note',notes:null},timezone:'Asia/Singapore',medications:[],regimens:[]}}} busy={false} onEvent={send}/>);
 fireEvent.change(await screen.findByRole('textbox',{name:'Describe how you feel (required)'}),{target:{value:'DEMO edited description'}});
 fireEvent.click(screen.getByRole('button',{name:'Apply care details'}));
 await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({values:expect.objectContaining({occurred_at:occurred})})));
});
