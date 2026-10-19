import {expect,it} from 'vitest';
import {sourceReviewHints} from './sourceReviewHints';
import type {SourcePreview} from './api/client';

it('quotes unstructured release, duration and explicit clock without turning them into confirmed fields',()=>{
 const candidates:SourcePreview['candidates']=[{product:{name:'DEMO product',strength:null,source_lines:['DEMO ER tablets. Take one tablet at 20:00. For 7 days. Expiry 08:00.']},review_status:'extracted',can_activate_regimen:false,regimen_evidence:{directions:null,dose_amount:null,frequency:null,administration_times:null,duration:null}}];
 expect(sourceReviewHints(candidates)).toEqual({clocks:['20:00'],release:['ER'],duration:['For 7 days']});
 expect(candidates[0]?.regimen_evidence.administration_times).toBeNull();
});
it('does not infer a clock from morning, daily frequency or dispensing dates',()=>{
 expect(sourceReviewHints([{product:{name:'DEMO',strength:null,source_lines:['Daily in the morning. Dispensed 2026/10/18.']},review_status:'extracted',can_activate_regimen:false,regimen_evidence:{directions:null,dose_amount:null,frequency:null,administration_times:null,duration:null}}]).clocks).toEqual([]);
});
it('retains the actual evening clock when the label uses AM/PM',()=>{
 expect(sourceReviewHints([{product:{name:'DEMO',strength:null,source_lines:['Take at 8:30 pm.']},review_status:'extracted',can_activate_regimen:false,regimen_evidence:{directions:null,dose_amount:null,frequency:null,administration_times:null,duration:null}}]).clocks).toEqual(['20:30']);
});
