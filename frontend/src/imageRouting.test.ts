import {expect,it} from 'vitest';
import {sourceRoute} from './imageRouting';
import type {ImageRoute} from './api/client';
const route=(image_type:ImageRoute['image_type'],checked=true,abstained=true):ImageRoute=>({image_type,checked,abstained,suggested_workflow:'ask_patient',message:'DEMO only'});
it('uses checked source evidence without interpreting abstention as invalid OCR',()=>{
 expect(sourceRoute(route('package'))).toBe('package');expect(sourceRoute(route('printed'))).toBe('pharmacy_label');expect(sourceRoute(route('document'))).toBe('prescription');
});
it('asks for unsupported blister/unchecked input and never obeys remote tool suggestions',()=>{
 expect(sourceRoute(route('blister'))).toBe('clarify');expect(sourceRoute(route('package',false))).toBe('clarify');expect(sourceRoute(route('unchecked'))).toBe('clarify');expect(sourceRoute(route('loose_pills',true,false))).toBe('pill');expect(sourceRoute(route('loose_pills'))).toBe('clarify');
});
