// @vitest-environment jsdom
import {afterEach,it,expect,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {VisualCheckScreen} from './VisualCheckScreen';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{visualCheck:vi.fn(),checkPersonalDose:vi.fn()}}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks();});
it('previews a selected image and requires consent before selected-regimen visual evidence',async()=>{
 vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:synthetic-demo');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);
 vi.mocked(api.checkPersonalDose).mockResolvedValue({id:'DEMO-run',decision:'missing_reference',reason:'No eligible personal pill photos are available. Add a reference photo to your medication.',reference_ids:[],outcome:null,ingestion_proven:false,safe_to_take:false});
 const onResult=vi.fn();const view=render(<VisualCheckScreen regimenId="demo-regimen" onBack={vi.fn()} onResult={onResult}/>);
 const image=new File(['synthetic bytes'],'demo.png',{type:'image/png'});
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[image]}});
 expect(await screen.findByAltText('Selected image preview')).toBeTruthy();
 expect((screen.getByRole('button',{name:'Check photo'}) as HTMLButtonElement).disabled).toBe(true);expect(api.visualCheck).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Check photo'}));
 await screen.findByText('Add a personal reference first');expect(api.checkPersonalDose).toHaveBeenCalledWith(image,'demo-regimen');expect(api.visualCheck).not.toHaveBeenCalled();
 expect(screen.getByText(/Compare the original label/)).toBeTruthy();expect(screen.queryByText(/photo cannot prove ingestion/)).toBeNull();
 expect(onResult).toHaveBeenCalledOnce();
 view.rerender(<VisualCheckScreen regimenId="demo-regimen" onBack={vi.fn()} showResult={false}/>);
 expect((screen.getByLabelText('Take or choose a photo') as HTMLInputElement).files?.[0]).toBe(image);
 expect(screen.queryByText('Add a personal reference first')).toBeNull();
});

it('leaving an in-flight check cannot navigate to its late result',async()=>{
 vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:synthetic-demo');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);
 let resolve:(value:Awaited<ReturnType<typeof api.checkPersonalDose>>)=>void=()=>undefined;
 vi.mocked(api.checkPersonalDose).mockReturnValue(new Promise(value=>{resolve=value;}));
 const onResult=vi.fn();const view=render(<VisualCheckScreen regimenId="demo-regimen" onBack={vi.fn()} onResult={onResult}/>);
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['DEMO synthetic'],'demo.png',{type:'image/png'})]}});
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Check photo'}));view.unmount();
 await act(async()=>resolve({id:'DEMO-run',decision:'missing_reference',reason:'DEMO no reference',reference_ids:[],outcome:null,ingestion_proven:false,safe_to_take:false}));
 expect(onResult).not.toHaveBeenCalled();
});
it('failed visual service does not fabricate a match or remove the return action',async()=>{
 vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:synthetic-demo');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);
 vi.mocked(api.visualCheck).mockRejectedValue(new Error('Visual evidence unavailable'));
 const back=vi.fn();render(<VisualCheckScreen regimenId={null} onBack={back}/>);
 fireEvent.change(screen.getByLabelText('Take or choose a photo'),{target:{files:[new File(['synthetic'],'demo.png',{type:'image/png'})]}});
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Check photo'}));
 await waitFor(()=>expect(screen.getByRole('alert')).toBeTruthy());expect(screen.queryByText('Medicine remains unverified')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Back'}));expect(back).toHaveBeenCalledOnce();
});
