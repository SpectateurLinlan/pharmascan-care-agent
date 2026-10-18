// @vitest-environment jsdom
/** DEMO_ONLY UI state tests, including delayed out-of-order real-shaped HTTP responses. */
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,within,waitFor} from '@testing-library/react';
import {api,type MedicationHistoryPage} from '../api/client';
import {HistoryScreen} from './HistoryScreen';
import {historyCatalogue,historyRecords,historyPage,historyOffset} from './historyTestFixture';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{historyCatalogue:vi.fn(),medicationHistory:vi.fn()}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it.each([0,1,5,6,20])('shows %i stored records with real page requests only when available',async count=>{
 vi.mocked(api.historyCatalogue).mockResolvedValue(historyCatalogue);
 vi.mocked(api.medicationHistory).mockImplementation(async (_query,cursor)=>historyPage(historyRecords(count),historyOffset(cursor)));
 render(<HistoryScreen/>);await screen.findByText(/Displayed records/);
 expect(screen.getByLabelText('Medicine')).toHaveProperty('value','');expect(screen.getByLabelText('Medication plan')).toHaveProperty('value','');expect(screen.getByLabelText('Date range')).toHaveProperty('value','30');
 const list=screen.getByRole('list');expect(within(list).queryAllByRole('listitem')).toHaveLength(Math.min(5,count));
 for(let n=5;n<count;n+=5){fireEvent.click(screen.getByRole('button',{name:'Load more records'}));await waitFor(()=>expect(within(list).queryAllByRole('listitem')).toHaveLength(Math.min(n+5,count)));}
 expect(within(list).queryAllByRole('listitem')).toHaveLength(count);expect(screen.queryByRole('button',{name:'Load more records'})).toBeNull();
 expect(api.medicationHistory).toHaveBeenCalledTimes(Math.max(1,Math.ceil(count/5)));
});
it('groups equal names while preserving registrations, scopes plans and resets pagination while ignoring stale queries',async()=>{
 let release:((value:MedicationHistoryPage)=>void)|undefined;
 vi.mocked(api.historyCatalogue).mockResolvedValue(historyCatalogue);
 vi.mocked(api.medicationHistory).mockImplementation(async (query,cursor)=>query.regimen_id==='DEMO-old'?new Promise(resolve=>{release=resolve;}):historyPage(historyRecords(query.medication_name==='demo metformin'?1:20),historyOffset(cursor)));
 render(<HistoryScreen/>);await screen.findByText(/Displayed records/);
 const medicine=screen.getByLabelText('Medicine'),plan=screen.getByLabelText('Medication plan');
 const labels=within(medicine).getAllByRole('option').map(row=>row.textContent);expect(new Set(labels).size).toBe(3);expect(labels).toContain('DEMO Amlodipine');
 fireEvent.click(screen.getByRole('button',{name:'Load more records'}));await waitFor(()=>expect(screen.getAllByRole('listitem')).toHaveLength(10));
 fireEvent.change(screen.getByLabelText('Date range'),{target:{value:'7'}});await screen.findByText(/Displayed records/);expect(screen.getAllByRole('listitem')).toHaveLength(5);
 fireEvent.change(medicine,{target:{value:'demo amlodipine'}});await screen.findByText(/Displayed records/);
 expect(within(plan).getAllByRole('option').map(row=>(row as HTMLOptionElement).value)).toEqual(['','DEMO-new','DEMO-plan-B','DEMO-old']);
 fireEvent.change(plan,{target:{value:'DEMO-old'}});expect(screen.queryAllByRole('listitem')).toHaveLength(0);
 fireEvent.change(medicine,{target:{value:'demo metformin'}});await screen.findByText(/Displayed records/);expect(screen.getAllByRole('listitem')).toHaveLength(1);
 await act(async()=>release?.(historyPage(historyRecords(20))));expect(screen.getAllByRole('listitem')).toHaveLength(1);expect(plan).toHaveProperty('value','');
});
it('supports functional custom dates and exposes plan-period only after a specific plan is selected',async()=>{
 vi.mocked(api.historyCatalogue).mockResolvedValue(historyCatalogue);vi.mocked(api.medicationHistory).mockResolvedValue(historyPage([]));render(<HistoryScreen/>);await screen.findByText(/Displayed records/);
 fireEvent.change(screen.getByLabelText('Date range'),{target:{value:'custom'}});expect(screen.queryByRole('option',{name:'Selected plan effective period'})).toBeNull();
 const count=vi.mocked(api.medicationHistory).mock.calls.length;
 fireEvent.change(screen.getByLabelText('Start date'),{target:{value:'2026-10-01'}});expect(api.medicationHistory).toHaveBeenCalledTimes(count);
 fireEvent.change(screen.getByLabelText('End date'),{target:{value:'2026-10-10'}});await waitFor(()=>expect(api.medicationHistory).toHaveBeenLastCalledWith({range_kind:'custom',start:'2026-10-01',end:'2026-10-10'}));
 fireEvent.change(screen.getByLabelText('Medication plan'),{target:{value:'DEMO-old'}});fireEvent.change(screen.getByLabelText('Date range'),{target:{value:'plan'}});await waitFor(()=>expect(api.medicationHistory).toHaveBeenLastCalledWith({range_kind:'plan',regimen_id:'DEMO-old'}));
});
it('keeps schedule/event/submission time separate and missing report unknown',async()=>{
 vi.mocked(api.historyCatalogue).mockResolvedValue(historyCatalogue);const rows=historyRecords(4);vi.mocked(api.medicationHistory).mockResolvedValue(historyPage(rows));render(<HistoryScreen/>);await screen.findByText(/Displayed records/);
 const items=screen.getAllByRole('listitem');expect(items[3]?.textContent).toContain('This dose has no record of whether you took it yet.');expect(items[3]?.textContent).not.toContain('You reported taking');
 expect(items[0]?.textContent).toContain(new Date(rows[0]!.sort_time).toLocaleString('en-SG',{timeZone:'Asia/Singapore'}));
 fireEvent.click(within(items[0]!).getByText('Report timestamps'));expect(items[0]?.textContent).toContain('Submitted at');expect(items[0]?.textContent).toContain('Event time');
});

it('discards an old load-more response after changing the medicine',async()=>{
 let release:((value:MedicationHistoryPage)=>void)|undefined;
 vi.mocked(api.historyCatalogue).mockResolvedValue(historyCatalogue);
 vi.mocked(api.medicationHistory).mockImplementation(async (query,cursor)=>cursor?new Promise(resolve=>{release=resolve;}):historyPage(historyRecords(query.medication_name==='demo metformin'?1:20)));
 render(<HistoryScreen/>);await screen.findByText(/Displayed records/);
 fireEvent.click(screen.getByRole('button',{name:'Load more records'}));
 fireEvent.change(screen.getByLabelText('Medicine'),{target:{value:'demo metformin'}});await screen.findByText(/Displayed records/);
 await act(async()=>release?.(historyPage(historyRecords(20),5)));
 expect(screen.getAllByRole('listitem')).toHaveLength(1);expect(screen.queryByRole('button',{name:'Load more records'})).toBeNull();
});

it('searches real English and Chinese names, clears search and keeps the all-medicines option',async()=>{
 const data={...historyCatalogue,medications:historyCatalogue.medications.map((row,i)=>({...row,display_name:i===2?'\u4e8c\u7532\u53cc\u80cd':row.display_name}))};
 vi.mocked(api.historyCatalogue).mockResolvedValue(data);vi.mocked(api.medicationHistory).mockResolvedValue(historyPage([]));
 render(<HistoryScreen/>);await screen.findByText(/Displayed records/);
 const search=screen.getByRole('searchbox',{name:'Search medicines'}),select=screen.getByLabelText('Medicine');
 fireEvent.change(search,{target:{value:'AMLODIPINE'}});expect(within(select).getAllByRole('option')).toHaveLength(2);
 fireEvent.change(search,{target:{value:'\u4e8c\u7532'}});expect(within(select).getAllByRole('option')).toHaveLength(2);
 fireEvent.change(search,{target:{value:'not found'}});expect(within(select).getAllByRole('option')).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'Clear search'}));expect(within(select).getAllByRole('option')).toHaveLength(3);expect(document.activeElement).toBe(search);
});

it('retains results when the same filter is selected again',async()=>{
 vi.mocked(api.historyCatalogue).mockResolvedValue(historyCatalogue);vi.mocked(api.medicationHistory).mockResolvedValue(historyPage(historyRecords(1)));
 render(<HistoryScreen/>);await screen.findByText(/Displayed records/);
 fireEvent.change(screen.getByLabelText('Medicine'),{target:{value:'demo amlodipine'}});await screen.findByText(/Displayed records/);
 const count=vi.mocked(api.medicationHistory).mock.calls.length;fireEvent.change(screen.getByLabelText('Medicine'),{target:{value:'demo amlodipine'}});
 expect(screen.getAllByRole('listitem')).toHaveLength(1);expect(api.medicationHistory).toHaveBeenCalledTimes(count);
});

it('keeps current medicines visible and reports history failures inline without a global confirmation-style popup',async()=>{
 vi.mocked(api.historyCatalogue).mockRejectedValue(new Error('temporary network failure'));
 render(<HistoryScreen currentMedications={[{medication_id:'private-medication-id',regimen_id:'private-regimen-id',display_name:'Amlodipine',dose_amount:5,dose_unit:'mg',is_prn:false,version_no:1,identity_status:'reviewed',source_backed:true}]}/>);
 expect((await screen.findByRole('alert')).textContent).toContain('Medication history could not be loaded. Your current medicines are still shown above.');
 expect(screen.getByRole('heading',{name:'Current medicines'})).toBeTruthy();expect(screen.getByText('Amlodipine')).toBeTruthy();
 expect(screen.queryByText('Please review this')).toBeNull();expect(screen.getByRole('button',{name:'Retry history query'})).toBeTruthy();
 expect((screen.getByLabelText('Medicine') as HTMLSelectElement).value).toBe('');
});
