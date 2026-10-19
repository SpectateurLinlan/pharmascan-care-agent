// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {api,type MedicationSummary} from '../api/client';
import {TodayAttentionOverview} from './TodayAttentionOverview';
beforeEach(()=>vi.spyOn(api,'doseFollowUps').mockResolvedValue({items:[{occurrence_id:'old-occ',regimen_id:'0',medication_id:'m0',medication_name:'Old dose',due_at:'2026-10-18T00:00:00Z',dose_amount:1,dose_unit:'tablet',report_id:null,intake_status:null,actual_administration_at:null,recorded_at:null,reason:null,notes:''}],has_more:false,timezone:'Asia/Singapore',as_of:'2026-10-18T04:00:00Z'}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.useRealTimers();});
const medicines=['Old dose','Next dose','PRN'].map((name,index)=>({regimen_id:String(index),medication_id:`m${index}`,display_name:name,is_prn:index===2,dose_amount:1,dose_unit:'tablet',version_no:1,identity_status:'reviewed',source_backed:true} as MedicationSummary));
it('removes expired and PRN plans from the attention list without claiming not taken',async()=>{
 vi.spyOn(api,'todayAttention').mockResolvedValue({as_of:'2026-10-18T04:00:00Z',local_date:'2026-10-18',timezone:'Asia/Singapore',plans:[{regimen_id:'0',state:'unrecorded',unrecorded_times:['2026-10-18T00:00:00Z']},{regimen_id:'1',state:'upcoming',unrecorded_times:[]},{regimen_id:'2',state:'as_needed',unrecorded_times:[]}]});
 render(<TodayAttentionOverview medications={medicines} focusRegimenId={null} onHistory={()=>undefined}>{medicine=><button>{medicine.display_name} report</button>}</TodayAttentionOverview>);
 expect(await screen.findByRole('button',{name:'Next dose report'})).toBeTruthy();
 expect(screen.queryByRole('button',{name:'Old dose report'})).toBeNull();
 await screen.findByRole('button',{name:'Report dose status'});
 expect(document.querySelector('.today-unrecorded')?.textContent).toContain('Old dose');
 expect(document.querySelector('.today-unrecorded')?.textContent).toContain('Not recorded does not mean not taken.');
 expect(document.querySelector('.today-prn')?.hasAttribute('open')).toBe(false);
 expect(document.querySelector('.today-prn')?.textContent).toContain('no daily required dose');
 expect(screen.queryByText(/reported not taking/)).toBeNull();
});
it('does not turn a lookup failure into an empty or completed medication day',async()=>{
 vi.spyOn(api,'todayAttention').mockRejectedValue(new Error('unavailable'));
 render(<TodayAttentionOverview medications={medicines} focusRegimenId={null} onHistory={()=>undefined}>{medicine=><p>{medicine.display_name}</p>}</TodayAttentionOverview>);
 expect(await screen.findByRole('alert')).toBeTruthy();
 expect(screen.getByRole('button',{name:'Retry loading schedule'})).toBeTruthy();
 expect(screen.queryByText('No scheduled doses need attention right now.')).toBeNull();
});
it('keeps today medication visible when there are no eligible late reports',async()=>{
 vi.spyOn(api,'todayAttention').mockResolvedValue({as_of:'2026-10-19T04:00:00Z',local_date:'2026-10-19',timezone:'Asia/Singapore',plans:[{regimen_id:'0',state:'upcoming',next_due_at:'2026-10-19T05:00:00Z',unrecorded_times:[]}]});
 vi.spyOn(api,'doseFollowUps').mockResolvedValue({items:[{occurrence_id:'yesterday',regimen_id:'0',medication_id:'m0',medication_name:'Old dose',due_at:'2026-10-18T15:00:00Z',dose_amount:1,dose_unit:'tablet',report_id:null,intake_status:null,actual_administration_at:null,recorded_at:null,reason:null,notes:''}],has_more:false,timezone:'Asia/Singapore',as_of:'2026-10-19T04:00:00Z'});
 render(<TodayAttentionOverview medications={medicines.slice(0,1)} focusRegimenId={null} onHistory={()=>undefined}>{medicine=><button>{medicine.display_name} schedule</button>}</TodayAttentionOverview>);
 expect(await screen.findByRole('button',{name:'Old dose schedule'})).toBeTruthy();expect(await screen.findByText('No eligible doses to report today.')).toBeTruthy();expect(screen.queryByRole('button',{name:'Report dose status'})).toBeNull();
});
it('keeps an unsupported schedule visible for review instead of inventing a time or empty day',async()=>{
 vi.spyOn(api,'todayAttention').mockResolvedValue({as_of:'2026-10-18T04:00:00Z',local_date:'2026-10-18',timezone:'Asia/Singapore',plans:[{regimen_id:'0',state:'unavailable',unrecorded_times:[]}]});
 render(<TodayAttentionOverview medications={medicines.slice(0,1)} focusRegimenId={null} onHistory={()=>undefined}>{medicine=><p>{medicine.display_name}</p>}</TodayAttentionOverview>);
 expect(await screen.findByText('Old dose')).toBeTruthy();expect(screen.getByRole('status').textContent).toContain('cannot be assessed automatically');expect(screen.queryByText('No scheduled doses need attention right now.')).toBeNull();
});
it('does not unmount an active confirmation when the attention window expires',async()=>{
 vi.useFakeTimers();
 const read={as_of:'2026-10-18T04:00:00Z',local_date:'2026-10-18',timezone:'Asia/Singapore',plans:[{regimen_id:'0',state:'pending' as const,unrecorded_times:[]}]};
 vi.spyOn(api,'todayAttention').mockResolvedValueOnce(read).mockResolvedValue({...read,plans:[{regimen_id:'0',state:'unrecorded',unrecorded_times:['2026-10-18T00:00:00Z']}]});
 let release:(()=>void)|undefined;
 render(<TodayAttentionOverview medications={medicines.slice(0,1)} focusRegimenId={null} onHistory={()=>undefined}>{(medicine,lock)=><button onClick={()=>{lock(medicine.regimen_id,true);release=()=>lock(medicine.regimen_id,false);}}>Lock report</button>}</TodayAttentionOverview>);
 await act(async()=>{await Promise.resolve();});fireEvent.click(screen.getByRole('button',{name:'Lock report'}));
 await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});expect(screen.getByRole('button',{name:'Lock report'})).toBeTruthy();
 release?.();await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});expect(screen.queryByRole('button',{name:'Lock report'})).toBeNull();
 expect(screen.getByText('No scheduled doses need attention right now.')).toBeTruthy();
});
