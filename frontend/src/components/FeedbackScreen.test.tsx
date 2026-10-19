// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {LanguageProvider} from '../language';
import {FeedbackScreen} from './FeedbackScreen';

afterEach(()=>{cleanup();vi.restoreAllMocks();});
it('acknowledges only persisted feedback and does not claim email delivery or review',async()=>{
 const submit=vi.spyOn(api,'feedback').mockResolvedValue({id:'DEMO-feedback',status:'received',created_at:'2026-10-20T00:00:00Z'});
 render(<LanguageProvider><FeedbackScreen/></LanguageProvider>);
 fireEvent.change(screen.getByLabelText('Description'),{target:{value:'DEMO issue description'}});fireEvent.click(screen.getByRole('button',{name:'Send feedback'}));
 await screen.findByText(/saved to your account feedback record/);expect(submit).toHaveBeenCalledOnce();expect(screen.queryByText(/emailed or reviewed/)).toBeTruthy();
});
it('retains the form and reports submission failure',async()=>{
 vi.spyOn(api,'feedback').mockRejectedValue(new Error('SIMULATED unavailable'));
 render(<LanguageProvider><FeedbackScreen/></LanguageProvider>);fireEvent.change(screen.getByLabelText('Description'),{target:{value:'DEMO feedback body'}});fireEvent.click(screen.getByRole('button',{name:'Send feedback'}));
 await screen.findByRole('alert');expect((screen.getByLabelText('Description') as HTMLTextAreaElement).value).toBe('DEMO feedback body');await waitFor(()=>expect(screen.getByRole('button',{name:'Send feedback'}).hasAttribute('disabled')).toBe(false));
});
