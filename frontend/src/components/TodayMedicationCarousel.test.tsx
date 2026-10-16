// @vitest-environment jsdom
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {TodayMedicationCarousel} from './TodayMedicationCarousel';
import type {MedicationSummary} from '../api/client';
afterEach(()=>{cleanup();vi.restoreAllMocks();});
const medicines=['Metformin','Amlodipine'].map((name,index)=>({medication_id:`DEMO-med-${index}`,regimen_id:`DEMO-plan-${index}`,display_name:name,dose_amount:index?10:500,dose_unit:'mg',is_prn:false,source_backed:true,version_no:1,identity_status:'unverified',frequency_rule:{kind:'daily',local_times:['20:00'],days_of_week:[]}} as MedicationSummary));
it('one medicine has no redundant selector or swipe controls',()=>{
  render(<TodayMedicationCarousel medications={[medicines[0]!]} focusRegimenId={null}>{row=><p>{row.display_name}</p>}</TodayMedicationCarousel>);
  expect(screen.getAllByText('Metformin')).toHaveLength(1);
  expect(screen.queryByRole('group',{name:'All current medicines'})).toBeNull();
  expect(screen.queryByRole('button',{name:'Next medicine'})).toBeNull();
});
it('shows all names/amounts and mounts actions only for the selected medicine',()=>{
  render(<TodayMedicationCarousel medications={medicines} focusRegimenId={null}>{row=><button>{row.display_name} report</button>}</TodayMedicationCarousel>);
  expect(screen.getByRole('button',{name:/Metformin Per dose: 500 mg/})).toBeTruthy();
  expect(screen.getByRole('button',{name:'Metformin report'})).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Amlodipine report'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:/Amlodipine Per dose: 10 mg/}));
  expect(screen.getByRole('button',{name:/Amlodipine Per dose: 10 mg/}).getAttribute('aria-pressed')).toBe('true');
  expect(screen.getByRole('button',{name:'Amlodipine report'})).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Metformin report'})).toBeNull();
});
it('labels existing same-name records for review without showing unrelated version-one identifiers',()=>{
 const first={...medicines[1]!,course_start_date:'2026-10-16',course_end_date:'2026-10-20'};
 const second={...first,regimen_id:'DEMO-duplicate',dose_amount:5,is_prn:true};
 render(<TodayMedicationCarousel medications={[first,second]} focusRegimenId={null}>{row=><p>{row.display_name}</p>}</TodayMedicationCarousel>);
 expect(screen.getByRole('status').textContent).toContain('Multiple recorded plans');
 expect(screen.queryByText(/Plan 1/)).toBeNull();
 expect(screen.getByText('2 medication plans')).toBeTruthy();
 expect(screen.getAllByRole('button').every(button=>button.textContent?.includes('2026-10-16'))).toBe(true);
});
