import {expect,it} from 'vitest';
import {canClaimNoRegistrations,canRenderClinicalToday,type StartupState} from './startupState';

function ready():StartupState {
 return {identity:{status:'ready',data:'DEMO-owner'},preferences:{status:'ready',data:{patient_id:'DEMO-owner',timezone:'Asia/Singapore'} as NonNullable<StartupState['preferences']['data']>},active:{status:'ready',data:{medications:[],item_count:0,note:'DEMO_ONLY'}},regimens:{status:'ready',data:[]},session:{status:'loading'},health:{status:'ready',data:{status:'ok',runtime_contract:'patient-ux-reminders-v1'} as NonNullable<StartupState['health']['data']>}};
}
it('clinical Today waits for verified preferences and records, independently of Agent setup and history',()=>{
 const state=ready();expect(canRenderClinicalToday(state)).toBe(true);
 expect(canRenderClinicalToday({...state,regimens:{status:'loading'}})).toBe(true);
 expect(canRenderClinicalToday({...state,preferences:{status:'loading'}})).toBe(false);
 expect(canRenderClinicalToday({...state,active:{status:'error',error:new Error('DEMO')}})).toBe(false);
});
it('no registrations requires both successful active and historical reads',()=>{
 const state=ready();expect(canClaimNoRegistrations(state)).toBe(true);
 expect(canClaimNoRegistrations({...state,regimens:{status:'loading'}})).toBe(false);
 expect(canClaimNoRegistrations({...state,regimens:{status:'error'}})).toBe(false);
});
it('does not treat missing preference data or a different owner as a trusted clinical state',()=>{
 const state=ready();
 expect(canRenderClinicalToday({...state,preferences:{status:'ready'}})).toBe(false);
 expect(canRenderClinicalToday({...state,identity:{status:'ready',data:'DEMO-other'}})).toBe(false);
});
