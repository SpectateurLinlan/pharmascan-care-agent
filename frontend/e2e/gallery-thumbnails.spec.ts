import {skipInitialGuide} from './navigation-helpers';
/** REAL browser/Auth/RLS/private PNG, synthetic packaging; no model/speech provider. */
import {test,expect} from '@playwright/test';
test.skip(process.env.RUN_LIVE_BROWSER!=='1','Synthetic live UI opt-in required');
test('private packaging thumbnails decode on the product list and survive reload',async({page})=>{
 await page.goto('/');await skipInitialGuide(page);await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('button',{name:/Add medication/}).click();await page.getByRole('button',{name:/Add manually/}).click();
 await page.getByLabel('Medication name',{exact:true}).fill('DEMO Metformin 500 mg');await page.getByLabel('Dose amount',{exact:true}).fill('1');await page.getByLabel('Unit',{exact:true}).fill('tablet');await page.locator('#med-time-0').fill('20:00');
 await page.getByRole('button',{name:'Create draft',exact:true}).click();await page.getByRole('button',{name:'I have reviewed these details'}).click();await page.getByRole('button',{name:'Show me the summary to confirm'}).click();await page.getByRole('button',{name:'Yes, save this medication'}).click();
 await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('button',{name:/Personal gallery/}).click();await page.locator('.gallery-entry').click();
 await page.getByLabel('Photo type').selectOption('package');await page.getByLabel('Take or choose a photo').filter({visible:true}).setInputFiles('../outputs/gallery-demo/package.png');await page.getByLabel('Where is this reference from?').fill('DEMO synthetic packaging reference');await page.getByLabel('I reviewed this photo against the selected product and its source.').check();await page.getByLabel('I agree to private storage and the selected image processing. Use synthetic files for this demo.').filter({visible:true}).check();await page.getByRole('button',{name:'Save reference photo'}).click();await page.getByRole('button',{name:'Back to gallery'}).click();
 const thumbnail=page.locator('.gallery-entry img');await expect(thumbnail).toHaveCount(1);await expect.poll(()=>thumbnail.evaluate(image=>(image as HTMLImageElement).complete&&(image as HTMLImageElement).naturalWidth>0)).toBe(true);
 await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'../outputs/gallery-demo/gallery-thumbnail390.png'});
 await page.reload();await page.getByRole('button',{name:'Medicines',exact:true}).click();await page.getByRole('button',{name:/Personal gallery/}).click();await expect(thumbnail).toHaveCount(1);await expect.poll(()=>thumbnail.evaluate(image=>(image as HTMLImageElement).naturalWidth>0)).toBe(true);
 await page.setViewportSize({width:430,height:932});await page.screenshot({path:'../outputs/gallery-demo/gallery-thumbnail430.png'});await page.setViewportSize({width:1280,height:900});await page.screenshot({path:'../outputs/gallery-demo/gallery-thumbnail-desktop.png'});
});
