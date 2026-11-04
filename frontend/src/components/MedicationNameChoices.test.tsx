// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {LanguageProvider} from '../language';
import {MedicationNameChoices} from './MedicationChoices';

afterEach(cleanup);
it('submits the offered name and version without a patient medication identity',()=>{
 const choose=vi.fn();
 render(<LanguageProvider><MedicationNameChoices disabled={false} onChoose={choose} choice={{id:'DEMO-choice',version:1,original:'ibuprofne',expires_at:'2099-01-01T00:00:00Z',options:[{id:'ingredient:ibuprofen',canonical_name:'IBUPROFEN',display_name:'IBUPROFEN',medication_id:null,source_refs:['DEMO-source']}]}}/></LanguageProvider>);
 fireEvent.click(screen.getByRole('button',{name:'IBUPROFEN'}));
 expect(choose).toHaveBeenCalledWith({choice_id:'DEMO-choice',candidate_id:'ingredient:ibuprofen',expected_version:1},'IBUPROFEN');
});
