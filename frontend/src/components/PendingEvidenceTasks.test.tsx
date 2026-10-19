// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {ApiError,api} from '../api/client';
import {PendingEvidenceTasks} from './PendingEvidenceTasks';

afterEach(()=>{cleanup();vi.restoreAllMocks();});

const entry={kind:'draft' as const,id:'DEMO-plan',name:'DEMO Metformin'};

it('keeps a failed draft visible with an inline error and lets the patient safely retry',async()=>{
 const remove=vi.spyOn(api,'deleteDraft').mockRejectedValueOnce(new ApiError(503,{code:'PROVIDER_UNAVAILABLE',message:'The database service is not ready for this request. Please try again later.',rule_id:null})).mockResolvedValueOnce({deleted:true,medication_deleted:true,cleanup_pending:false});
 const onRetry=vi.fn();
 render(<PendingEvidenceTasks entries={[entry]} error={null} onRetry={onRetry} onContinue={vi.fn()} onResume={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Delete draft'}));
 fireEvent.click(screen.getByRole('button',{name:'Confirm delete'}));
 const alert=await screen.findByRole('alert');
 expect(alert.textContent).toContain('The draft was not deleted. It is still saved.');
 expect(screen.getByRole('button',{name:'Delete draft'})).toBeTruthy();
 expect(document.querySelector('.patient-toast--error')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Retry deletion'}));
 await waitFor(()=>expect(remove).toHaveBeenCalledTimes(2));
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
 expect(onRetry).toHaveBeenCalledOnce();
});
