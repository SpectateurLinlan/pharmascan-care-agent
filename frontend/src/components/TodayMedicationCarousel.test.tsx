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
it('shows all names/amounts, supports direct and next selection and keeps offscreen actions inert',()=>{
  const scroll=vi.fn();Object.defineProperty(HTMLElement.prototype,'scrollTo',{value:scroll,configurable:true});
  render(<TodayMedicationCarousel medications={medicines} focusRegimenId={null}>{row=><button>{row.display_name} report</button>}</TodayMedicationCarousel>);
  expect(screen.getByRole('button',{name:/Metformin 500 mg/})).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Next medicine'}));
  expect(screen.getByRole('button',{name:/Amlodipine 10 mg/}).getAttribute('aria-pressed')).toBe('true');
  const slides=document.querySelectorAll<HTMLElement>('.medicine-slide');expect(slides[0]?.inert).toBe(true);expect(slides[1]?.inert).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:/Metformin 500 mg/}));
  expect(slides[0]?.inert).toBe(false);expect(scroll).toHaveBeenCalled();
});
