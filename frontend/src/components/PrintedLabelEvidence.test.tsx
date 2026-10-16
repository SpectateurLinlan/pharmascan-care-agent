// @vitest-environment jsdom
import {afterEach,expect,it} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import type {SourcePreview} from '../api/client';
import {PrintedLabelEvidence} from './PrintedLabelEvidence';
afterEach(cleanup);
const candidate:SourcePreview['candidates'][number]={product:{name:'DEMO Metformin',strength:'500 mg',source_lines:['DEMO 500 mg']},review_status:'extracted',can_activate_regimen:false,regimen_evidence:{directions:{value:'Take one tablet twice daily',line:'DEMO original'},dose_amount:null,frequency:null,administration_times:null,duration:null,instructions:{text:'Take one tablet twice daily',line:'DEMO original',dose:{amount:1,amount_max:null,unit:'tablet'},times_per_day:2,every_hours:null,as_needed:false,times_of_day:[],food:'after_food',duration:null,max_per_day:null}}};
it('shows structured sticker evidence, missing values and limitations without invented times or confirmation',()=>{
 render(<PrintedLabelEvidence candidate={candidate}/>);
 expect(screen.getByText('1 tablet')).toBeTruthy();expect(screen.getByText('2')).toBeTruthy();
 expect(screen.getAllByText('Not printed or not read. Please check the original label.').length).toBeGreaterThan(0);
 expect(screen.getByText('Frequency does not specify clock times. Label dates and expiry are not course dates.')).toBeTruthy();
 expect(screen.queryByText('08:00')).toBeNull();expect(screen.queryByRole('button')).toBeNull();
});
it('strength-only packaging is not rendered as a dose and list_check is review-only evidence',()=>{
 render(<PrintedLabelEvidence candidate={{...candidate,regimen_evidence:{...candidate.regimen_evidence,directions:null,instructions:null},list_comparison:{status:'same_medicine',medication_id:'DEMO',message:'untrusted provider advice'}}}/>);
 expect(screen.queryByText('1 tablet')).toBeNull();expect(screen.queryByText('500 mg')).toBeNull();
 expect(screen.getByText('Possibly already registered — review before linking.')).toBeTruthy();
 expect(screen.queryByText('untrusted provider advice')).toBeNull();
});
it('shows the medicine’s general use with its source line, and invents nothing when the source returned none',()=>{
 const withIndication={...candidate,regimen_evidence:{...candidate.regimen_evidence,indication:{value:'Used to treat type 2 diabetes',line:'DEMO label section 1'}}};
 const first=render(<PrintedLabelEvidence candidate={withIndication}/>);
 expect(screen.getByText('What this medicine is used for')).toBeTruthy();
 expect(screen.getByText('Used to treat type 2 diabetes')).toBeTruthy();
 expect(screen.getByText(/DEMO label section 1/)).toBeTruthy();
 first.unmount();
 render(<PrintedLabelEvidence candidate={candidate}/>);
 expect(screen.queryByText('What this medicine is used for')).toBeNull();
 expect(screen.queryByText(/type 2 diabetes/)).toBeNull();
});
