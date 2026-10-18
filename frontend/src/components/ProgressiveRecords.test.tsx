// @vitest-environment jsdom
/** DEMO_ONLY report disclosure and bounded history page regression. */
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {HistoryScreen} from './HistoryScreen';
import {ReportDetails} from './ReportDetails';
import {historyCatalogue,historyRecords,historyPage,historyOffset} from './historyTestFixture';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{historyCatalogue:vi.fn(),medicationHistory:vi.fn()}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it.each([0,1,5,20])('shows %i real-shaped page records in server order without hiding additional records',async count=>{
 vi.mocked(api.historyCatalogue).mockResolvedValue(historyCatalogue);const rows=historyRecords(count);
 vi.mocked(api.medicationHistory).mockImplementation(async (_filters,cursor)=>historyPage(rows,historyOffset(cursor)));
 render(<HistoryScreen/>);await screen.findByText(/Displayed records/);const list=screen.getByRole('list');
 expect(within(list).queryAllByRole('listitem')).toHaveLength(Math.min(count,5));
 if(count){expect(within(list).getAllByRole('listitem')[0]?.textContent).toContain(new Date(rows[0]!.sort_time).toLocaleString('en-SG',{timeZone:'Asia/Singapore'}));}
 for(let n=5;n<count;n+=5){fireEvent.click(screen.getByRole('button',{name:'Load more records'}));await waitFor(()=>expect(within(list).queryAllByRole('listitem')).toHaveLength(Math.min(count,n+5)));}
 expect(within(list).queryAllByRole('listitem')).toHaveLength(count);expect(screen.queryByRole('button',{name:'Load more records'})).toBeNull();
});
it('opens every detail for print and restores the prior disclosure state',()=>{
 render(<ReportDetails><p>DEMO full printable evidence</p></ReportDetails>);
 const details=screen.getByText('Detailed records and sources').closest('details')!;
 expect(details.open).toBe(false);fireEvent(window,new Event('beforeprint'));expect(details.open).toBe(true);
 fireEvent(window,new Event('afterprint'));expect(details.open).toBe(false);
 details.open=true;fireEvent(window,new Event('beforeprint'));fireEvent(window,new Event('afterprint'));expect(details.open).toBe(true);
});
