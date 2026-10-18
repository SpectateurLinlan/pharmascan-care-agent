import {expect,it} from 'vitest';
import {historyMedicationOptions,historyPlanLabel} from './historyFilterLabels';
import {historyCatalogue} from './components/historyTestFixture';
const t=(text:string)=>text;
it('groups exact names for browsing without discarding original registration IDs',()=>{
 const rows=historyMedicationOptions(historyCatalogue,t);expect(rows).toHaveLength(2);
 const group=rows.find(row=>row.label==='DEMO Amlodipine')!;expect(group.medication_ids).toEqual(['DEMO-A','DEMO-B']);expect(group.label).not.toContain('record');
});
it('keeps similar but unequal names separate and normalizes case and whitespace only',()=>{
 const data={...historyCatalogue,medications:[...historyCatalogue.medications,{...historyCatalogue.medications[0]!,id:'DEMO-similar',display_name:'DEMO Amlodipine combination'},{...historyCatalogue.medications[0]!,id:'DEMO-case',display_name:'  demo   AMLODIPINE '}]};
 const rows=historyMedicationOptions(data,t);expect(rows).toHaveLength(3);expect(rows.find(row=>row.id==='demo amlodipine')!.medication_ids).toContain('DEMO-case');
});
it('separates strength and dose and displays only real frequency and end date',()=>{
 const row={...historyCatalogue.plans[0]!,dosage_form:'tablet',frequency:{kind:'daily',local_times:['08:00','20:00'],days_of_week:[],every_hours:null}};
 const label=historyPlanLabel(row,t,'en-SG','Asia/Singapore');expect(label).toContain('Strength per tablet: 5 mg');expect(label).toContain('Per dose: 1 tablet');expect(label).toContain('Daily 08:00, 20:00');expect(label).toContain('Effective until');
 const open=historyPlanLabel({...row,effective_to:null},t,'en-SG','Asia/Singapore');expect(open).not.toContain('Effective until');
 expect(historyPlanLabel({...row,frequency:null},t,'en-SG','Asia/Singapore')).toContain('Frequency not recorded');
});
