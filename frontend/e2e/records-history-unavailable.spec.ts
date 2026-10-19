/** DEMO_ONLY browser regression: history service failures do not hide current medicines. */
import {expect,test} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

test('shows only an inline retry when history is unavailable, without rejected current medicines or popup',async({page})=>{
 const {errors,setMedications}=await mockPatientApp(page);
 setMedications([{medication_id:'DEMO-medication',regimen_id:'DEMO-regimen',display_name:'DEMO Amlodipine',dose_amount:5,dose_unit:'mg',is_prn:false,version_no:1,identity_status:'reviewed',source_backed:true}]);
 await page.route(url=>new URL(url).pathname==='/api/me/medication-history/catalogue',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({code:'PROVIDER_UNAVAILABLE',message:'This service is temporarily unavailable. Please try again.',rule_id:null})}));
 await page.goto('/');await page.locator('[data-guide="records"]').click();
 await expect(page.getByRole('heading',{name:'Current medicines'})).toHaveCount(0);
 await expect(page.getByRole('alert')).toContainText('Could not load medication history. Please retry.');
 await expect(page.getByRole('button',{name:'Retry history query'})).toBeVisible();
 await expect(page.getByText('Please review this')).toHaveCount(0);
 expect(errors).toEqual([]);
});
