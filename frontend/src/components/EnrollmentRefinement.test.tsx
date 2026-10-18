// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {EnrollScreen,courseDuration,courseEndForDuration} from './EnrollScreen';
import {AutoDismissNotice} from './primitives';
import {api,type RegimenHistoryItem} from '../api/client';
afterEach(()=>{cleanup();vi.useRealTimers();vi.restoreAllMocks();});
it('calculates inclusive calendar days across months/leap days and rejects reversed dates',()=>{
 expect(courseEndForDuration('2028-02-28',3)).toBe('2028-03-01');expect(courseDuration('2028-02-28','2028-03-01')).toBe('3');
 expect(courseDuration('2026-10-18','2026-10-18')).toBe('1');expect(courseDuration('2026-10-19','2026-10-18')).toBe('');expect(courseDuration('2026-02-30','2026-03-02')).toBe('');
});
it('asks for only days or end date, converts between modes and keeps the original course fields',()=>{
 render(<EnrollScreen sessionId={null} medications={null} onChanged={()=>undefined}/>);
 fireEvent.change(screen.getByLabelText('Course start date'),{target:{value:'2028-02-28'}});
 fireEvent.change(screen.getByLabelText('Number of days'),{target:{value:'3'}});
 expect(screen.queryByLabelText('Last day (inclusive)')).toBeNull();expect(screen.getByText('Last day (inclusive): 2028-03-01')).toBeTruthy();
 fireEvent.click(screen.getByRole('radio',{name:'Enter last day'}));expect(screen.getByLabelText('Last day (inclusive)')).toHaveProperty('value','2028-03-01');expect(screen.queryByLabelText('Number of days')).toBeNull();
 fireEvent.change(screen.getByLabelText('Last day (inclusive)'),{target:{value:'2028-03-03'}});expect(screen.getByText('Number of days: 5')).toBeTruthy();
 fireEvent.click(screen.getByRole('radio',{name:'Enter number of days'}));expect(screen.getByLabelText('Number of days')).toHaveProperty('value','5');
 fireEvent.change(screen.getByLabelText('Course start date'),{target:{value:'2028-03-01'}});expect(screen.getByText('Last day (inclusive): 2028-03-05')).toBeTruthy();
});
it('automatically removes a success notice without a close button or focus change',()=>{
 vi.useFakeTimers();render(<><button>Keep focus</button><AutoDismissNotice>DEMO added</AutoDismissNotice></>);screen.getByRole('button').focus();
 expect(screen.getByRole('status').textContent).toBe('DEMO added');expect(screen.queryByRole('button',{name:'Close'})).toBeNull();
 act(()=>vi.advanceTimersByTime(4500));expect(screen.queryByRole('status')).toBeNull();expect(document.activeElement).toBe(screen.getByRole('button'));
});

it('does not restart a resumed draft when the parent refreshes its plan snapshot',async()=>{
 const saved={medication_id:'DEMO-med',regimen_id:'DEMO-draft',state:'draft',source_id:'DEMO-source',missing_instructions:[],reviewable_field_ids:[],note:'DEMO only'};
 const resume=vi.spyOn(api,'resumeDraft').mockResolvedValue(saved);
 const row:RegimenHistoryItem={medication_id:'DEMO-med',regimen_id:'DEMO-draft',display_name:'DEMO resumed',version_no:1,state:'draft',effective_from:null,effective_to:null,course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:['08:00']};
 const props={resumeRegimenId:'DEMO-draft',resumeRow:row,sessionId:'DEMO-session',medications:null,onChanged:()=>undefined};
 const {rerender}=render(<EnrollScreen {...props}/>);await screen.findByDisplayValue('DEMO resumed');
 await waitFor(()=>expect(screen.getByRole('button',{name:'Review and add'})).toHaveProperty('disabled',false));
 fireEvent.click(screen.getByRole('button',{name:'Review and add'}));expect(screen.getByRole('button',{name:'Add this medication'})).toBeTruthy();
 rerender(<EnrollScreen {...props} resumeRow={{...row}}/>);expect(screen.getByRole('button',{name:'Add this medication'})).toBeTruthy();expect(resume).toHaveBeenCalledTimes(1);
});
