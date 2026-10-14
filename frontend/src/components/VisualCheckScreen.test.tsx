// @vitest-environment jsdom
import {afterEach,it,expect,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {VisualCheckScreen} from './VisualCheckScreen';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{visualCheck:vi.fn(),checkPersonalDose:vi.fn()}}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks();});
it('previews a selected image and requires consent before selected-regimen visual evidence',async()=>{
 vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:synthetic-demo');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);
 vi.mocked(api.checkPersonalDose).mockResolvedValue({id:'DEMO-run',decision:'missing_reference',reason:'No eligible personal pill photos are available. Add a reference photo to your medication.',reference_ids:[],outcome:null,ingestion_proven:false,safe_to_take:false});
 render(<VisualCheckScreen regimenId="demo-regimen" onBack={vi.fn()}/>);
 const image=new File(['synthetic bytes'],'demo.png',{type:'image/png'});
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[image]}});
 expect(await screen.findByAltText('Selected image preview')).toBeTruthy();
 expect((screen.getByRole('button',{name:'Check photo'}) as HTMLButtonElement).disabled).toBe(true);expect(api.visualCheck).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Check photo'}));
 await screen.findByText('Add a personal reference first');expect(api.checkPersonalDose).toHaveBeenCalledWith(image,'demo-regimen');expect(api.visualCheck).not.toHaveBeenCalled();
 expect(screen.getByText(/photo cannot prove ingestion/)).toBeTruthy();
});
it('failed visual service does not fabricate a match or remove the return action',async()=>{
 vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:synthetic-demo');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);
 vi.mocked(api.visualCheck).mockRejectedValue(new Error('Visual evidence unavailable'));
 const back=vi.fn();render(<VisualCheckScreen regimenId={null} onBack={back}/>);
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['synthetic'],'demo.png',{type:'image/png'})]}});
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Check photo'}));
 await waitFor(()=>expect(screen.getByRole('alert')).toBeTruthy());expect(screen.queryByText('Medicine remains unverified')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Back to Today'}));expect(back).toHaveBeenCalledOnce();
});
