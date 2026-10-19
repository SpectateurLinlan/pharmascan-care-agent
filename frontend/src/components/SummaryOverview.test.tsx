// @vitest-environment jsdom
import {afterEach,expect,it} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {SummaryOverview} from './SummaryOverview';
import {observationText} from '../summaryPresentation';
import type {HealthObservation,ReviewSummary} from '../api/client';
afterEach(cleanup);
it('keeps saved measurements and units, including zero, in report text',()=>{
 const row={description:'DEMO saved reading',value:128,secondary_value:82,unit:'mmHg',notes:null} as HealthObservation;
 expect(observationText(row)).toContain('128/82 mmHg');
 expect(observationText({...row,value:0,secondary_value:null,unit:'score'})).toContain('0 score');
});
it('distinguishes real self-reports from unrecorded stored doses without inferring adherence',()=>{
 const data={medications:[{medication_id:'DEMO-A',without_report:2},{medication_id:'DEMO-A',without_report:1}],reported_taken:4,reported_not_taken:1,unsure:2,observations:[],questions:['DEMO question from records']} as unknown as ReviewSummary;
 render(<SummaryOverview data={data}/>);
 expect(screen.getByText('1 medicines · 7 dose reports · 0 health observations')).toBeTruthy();
 expect(screen.getByText(/3 stored past scheduled doses have no report/)).toBeTruthy();
 expect(screen.getByText('DEMO question from records')).toBeTruthy();
 expect(screen.queryByText(/%/)).toBeNull();
});
