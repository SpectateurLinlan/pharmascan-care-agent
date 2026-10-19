/** Browser acceptance with synthetic authenticated API responses; no real photos or provider calls. */
import {test,expect} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';
import type {GalleryEntry,GalleryImage,MedicationSummary,RegimenHistoryItem} from '../src/api/client';

const privatePng=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXuoAAAAASUVORK5CYII=','base64');
const image:GalleryImage={id:'DEMO-photo',medication_id:'DEMO-med',image_kind:'loose_pill',source_description:'personally_photographed',reviewed:true,eligibility:'associated',eligibility_reason:'image_content_not_independently_validated_comparison_disabled',created_at:'2026-10-18T00:00:00Z'};
const gallery:GalleryEntry[]=[
 {medication:{id:'DEMO-med',display_name:'DEMO Metformin',identity_status:'user_reviewed_document'},product:{name:'DEMO Metformin',strength:'500 mg',dose_form:'tablet',formulation:null,brand:'DEMO Brand',ingredients:['metformin'],category:'unknown',verification:'patient_reviewed'},evidence_task_id:null,similar_name_records:1,status:'current',regimens:[{id:'DEMO-plan',state:'active',version_no:1,effective_from:'2026-01-10T00:00:00Z',effective_to:null,course_start_date:'2026-01-12',course_end_date:null,dose_amount:1,dose_unit:'tablet'}],images:[image],eligible_count:0},
 {medication:{id:'DEMO-other-med',display_name:'DEMO Metformin',identity_status:'unknown'},product:{name:'DEMO Metformin',strength:'1000 mg',dose_form:'tablet',formulation:null,brand:null,ingredients:['metformin'],category:'unknown',verification:'source_supplied'},evidence_task_id:null,similar_name_records:1,status:'historical',regimens:[],images:[],eligible_count:0},
];
function libraryFiles(row:GalleryEntry|undefined){return{medication_id:row?.medication.id??'DEMO-med',files:(row?.images??[]).map(photo=>({id:photo.id,image_id:photo.id,image_ids:[photo.id],name:photo.source_description,format:'PNG' as const,content_type:'image' as const,photo_description:photo.image_kind,purpose_tags:['appearance_reference' as const],created_at:photo.created_at,eligibility:photo.eligibility,eligibility_reason:photo.eligibility_reason,sources:[]})),source_records:[],regimens:row?.regimens??[]};}
async function mockFiles(page:import('@playwright/test').Page,getRows:()=>GalleryEntry[]){await page.route(url=>new URL(url).pathname.endsWith('/files')&&new URL(url).pathname.startsWith('/api/evidence/gallery/'),route=>{const id=new URL(route.request().url()).pathname.split('/').at(-2);return route.fulfill({json:libraryFiles(getRows().find(row=>row.medication.id===id))});});}

async function openGallery(page:import('@playwright/test').Page){
 await page.goto('/');await page.locator('[data-guide="medicines"]').click();await page.getByRole('button',{name:'Medication Library'}).click();
}

test('database read failure is not presented as an empty gallery or new registration',async({page})=>{
 await mockPatientApp(page);
 await page.route(url=>new URL(url).pathname==='/api/evidence/gallery',route=>route.fulfill({status:503,json:{code:'PROVIDER_UNAVAILABLE',message:'The database service is not ready for this request. Please try again later.',rule_id:null}}));
 await page.goto('/#gallery');
 await expect(page.getByRole('heading',{name:'My Medication Library'})).toBeVisible();
 await expect(page.getByRole('alert')).toBeVisible();
 await expect(page.getByText('No medications match these filters.')).toHaveCount(0);
 await expect(page.getByText('Register a medication to begin your personal gallery.')).toHaveCount(0);
});

test('About keeps PDF prescription understanding explicitly in the future in English and Chinese',async({page})=>{
 const {prefs}=await mockPatientApp(page);
 await page.goto('/#about');
 await expect(page.getByRole('heading',{name:'PDF Prescription Understanding'})).toBeVisible();
 await expect(page.getByText('Future capability; not available yet. Current PDF upload only stores and displays the original file.')).toBeVisible();
 prefs.preferred_language='zh';await page.reload();
 await expect(page.getByRole('heading',{name:'处方 PDF 理解'})).toBeVisible();
 await expect(page.getByText('未来功能，目前尚不可用。当前 PDF 上传仅保存和显示原件。')).toBeVisible();
});

test('PDF original preview download edit and confirmed deletion use the private file API',async({page})=>{
 await mockPatientApp(page);
 const parts=['%PDF-1.4\n'];const offsets=[0];
 const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>'];
 objects.forEach((value,index)=>{offsets.push(Buffer.byteLength(parts.join('')));parts.push(`${index+1} 0 obj\n${value}\nendobj\n`);});
 const xref=Buffer.byteLength(parts.join(''));parts.push(`xref\n0 4\n0000000000 65535 f \n${offsets.slice(1).map(value=>`${String(value).padStart(10,'0')} 00000 n \n`).join('')}trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
 const pdf=Buffer.from(parts.join(''));let deleted=false;
 let file={id:'DEMO-pdf',file_id:'DEMO-pdf',image_id:null,image_ids:[],name:'DEMO original',original_filename:'DEMO.pdf',format:'PDF',content_type:'pdf',photo_description:null,purpose_tags:['source_document'],created_at:'2026-10-19T00:00:00Z',eligibility:'ineligible',eligibility_reason:'not_an_image',sources:[],category:'other',description:'DEMO',version:1,byte_size:pdf.length};
 await page.route(url=>new URL(url).pathname==='/api/evidence/gallery',route=>route.fulfill({json:[{...gallery[0],images:[],pdf_file_count:deleted?0:1}]}));
 await page.route(url=>new URL(url).pathname==='/api/evidence/gallery/DEMO-med/files',route=>route.fulfill({json:{medication_id:'DEMO-med',file_management_available:true,files:deleted?[]:[file],source_records:[],regimens:[]}}));
 await page.route('**/api/evidence/library-files/DEMO-pdf*',async route=>{
  const request=route.request();expect(request.headers().authorization).toBe('Bearer DEMO.synthetic-session-token');
  if(request.method()==='PATCH'){const body=request.postDataJSON();expect(body.expected_version).toBe(1);file={...file,name:body.title,version:2};await route.fulfill({json:{display_title:file.name,category:file.category,description:file.description,version:2}});return;}
  if(request.method()==='DELETE'){expect(new URL(request.url()).searchParams.get('confirmed')).toBe('true');deleted=true;await route.fulfill({json:{deleted:true}});return;}
  await route.fulfill({contentType:'application/pdf',body:pdf});
 });
 await page.goto('/#gallery?medication_id=DEMO-med');
 await page.getByRole('button',{name:'Preview PDF: DEMO original'}).click();
 await expect(page.getByTitle('PDF preview')).toHaveAttribute('src',/^blob:/);
 const downloadEvent=page.waitForEvent('download');await page.getByRole('link',{name:'Download original'}).click();
 const download=await downloadEvent;expect(download.suggestedFilename()).toBe('DEMO.pdf');
 await page.getByRole('button',{name:'Edit File Information'}).click();await page.getByLabel('File title').fill('DEMO reviewed original');await page.getByRole('button',{name:'Save changes'}).click();
 await expect(page.getByRole('heading',{name:'DEMO reviewed original',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Delete File',exact:true}).click();
 await page.getByRole('alertdialog').getByRole('button',{name:'Delete File',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByRole('button',{name:'Preview PDF: DEMO reviewed original'})).toHaveCount(0);
 expect(deleted).toBe(true);
});

test('global gallery searches product identity and keeps same-name medication records distinct',async({page})=>{
 const {errors,setMedications,setPlans}=await mockPatientApp(page);const medication:MedicationSummary={medication_id:'DEMO-med',regimen_id:'DEMO-plan',display_name:'DEMO Metformin',is_prn:false,version_no:1,identity_status:'user_reviewed_document',source_backed:true,dose_amount:1,dose_unit:'tablet',frequency_rule:{kind:'daily',local_times:['08:00'],days_of_week:[]}};const regimen:RegimenHistoryItem={regimen_id:'DEMO-plan',display_name:'DEMO Metformin',version_no:1,state:'active',medication_id:'DEMO-med',effective_from:null,effective_to:null,course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:['08:00']};setMedications([medication]);setPlans([regimen]);
 await page.route(url=>new URL(url).pathname==='/api/evidence/gallery',route=>route.fulfill({json:gallery}));await mockFiles(page,()=>gallery);await page.route('**/api/evidence/images/DEMO-photo',route=>route.fulfill({status:200,contentType:'image/png',body:privatePng}));
 await openGallery(page);await expect(page.locator('.gallery-entry')).toHaveCount(2);await page.getByLabel('Search gallery').fill('DEMO Brand');await expect(page.locator('.gallery-entry')).toHaveCount(1);await expect(page.locator('.gallery-entry')).toContainText('500 mg');
 await page.getByLabel('Search gallery').fill('not present');await expect(page.getByText('No medications match these filters.')).toBeVisible();await page.getByLabel('Search gallery').clear();await page.locator('.gallery-entry').first().click();
 await expect(page.getByRole('heading',{name:/DEMO Metformin.*Medication Files/})).toBeVisible();await expect(page.getByText(/Course dates: 2026-01-12/)).toBeVisible();await expect(page.getByText(/Version effective period: 10\/01\/2026/)).toBeVisible();await expect(page).toHaveURL(/#gallery\?medication_id=DEMO-med/);await expect(page.getByRole('button',{name:'All Files'})).toBeVisible();await expect(page.getByRole('button',{name:'Add reference photo'})).toBeVisible();await expect(page.getByRole('button',{name:'Medication details'})).toBeVisible();await expect(page.getByRole('button',{name:'Check this dose'})).toHaveCount(0);
 await page.goBack();await expect(page).toHaveURL(/#gallery$/);await expect(page.getByRole('heading',{name:'My Medication Library'})).toBeVisible();await expect(page.locator('.gallery-entry')).toHaveCount(2);
 await page.goForward();await expect(page).toHaveURL(/#gallery\?medication_id=DEMO-med/);await expect(page.getByRole('heading',{name:/DEMO Metformin.*Medication Files/})).toBeVisible();
 await page.reload();await expect(page.getByRole('heading',{name:/DEMO Metformin.*Medication Files/})).toBeVisible();await page.getByRole('button',{name:'Open photo preview: Pill reference photo'}).click();await expect(page.getByRole('dialog')).toContainText('Personally photographed');await expect(page.getByRole('dialog')).toContainText('For your reference');
});

test('source detail keeps medication scope across browser Back, Forward and direct refresh',async({page})=>{
 await mockPatientApp(page);await page.route(url=>new URL(url).pathname==='/api/evidence/gallery',route=>route.fulfill({json:gallery}));
 const source={id:'DEMO-source',source_kind:'prescription',review_status:'user_reviewed',reviewed_at:'2026-10-18T00:00:00Z',recorded_at:'2026-10-18T00:00:00Z',extraction_evidence:{source_document_id:'DEMO-source',source_kind:'prescription',provider_source:'photo',provider:'DEMO extractor',extraction_model:'DEMO-v1',candidates:[],note:'Synthetic extraction, review required.',review_required:true},fields:[{id:'DEMO-field',field_name:'medication_name',field_value:'DEMO Metformin',review_status:'user_reviewed',reviewed_at:'2026-10-18T00:00:00Z'}],regimen_ids:['DEMO-plan'],image_ids:['DEMO-photo']};
 await page.route(url=>new URL(url).pathname==='/api/evidence/gallery/DEMO-med/files',route=>route.fulfill({json:{medication_id:'DEMO-med',files:[{id:'DEMO-photo',image_id:'DEMO-photo',image_ids:['DEMO-photo'],name:'DEMO pharmacy label',format:'PNG',content_type:'image',photo_description:'package',purpose_tags:['appearance_reference','enrollment_source'],created_at:image.created_at,eligibility:image.eligibility,eligibility_reason:image.eligibility_reason,sources:[source]}],source_records:[],regimens:gallery[0]!.regimens}}));
 await page.route('**/api/evidence/images/DEMO-photo',route=>route.fulfill({status:200,contentType:'image/png',body:privatePng}));
 await page.goto('/#gallery?medication_id=DEMO-med');await page.getByRole('button',{name:'View source record: Prescription'}).click();
 await expect(page.getByRole('dialog',{name:'Source record details'})).toBeVisible();await expect(page.getByText('Synthetic extraction, review required.')).toBeVisible();await expect(page).toHaveURL(/source_id=DEMO-source/);
 await page.goBack();await expect(page).toHaveURL(/#gallery\?medication_id=DEMO-med$/);await expect(page.getByRole('dialog')).toHaveCount(0);
 await page.goForward();await expect(page.getByRole('dialog',{name:'Source record details'})).toBeVisible();
 await page.reload();await expect(page.getByRole('dialog',{name:'Source record details'})).toBeVisible();await expect(page.getByText('Patient reviewed').first()).toBeVisible();
});

test('upload is progressive and Stage2 workflow routing is not treated as image classification',async({page})=>{
 await mockPatientApp(page);let currentGallery=gallery;let submitted:Record<string,string>|null=null;
 let suggestionCalls=0;await page.route(url=>new URL(url).pathname==='/api/sources/check-input',route=>{suggestionCalls++;return route.fulfill({json:{image_type:'package',checked:true,abstained:false,suggested_workflow:'ask_patient',message:'DEMO Stage2 suggestion'}});});
 await page.route(url=>new URL(url).pathname==='/api/evidence/gallery',route=>route.fulfill({json:currentGallery}));await mockFiles(page,()=>currentGallery);
 await page.route(url=>new URL(url).pathname==='/api/evidence/images/DEMO-photo',route=>route.fulfill({status:200,contentType:'image/png',body:privatePng}));
 await page.route(url=>new URL(url).pathname==='/api/evidence/gallery/DEMO-med/images',async route=>{
  const requestUrl=new URL(route.request().url());submitted=Object.fromEntries(requestUrl.searchParams.entries());
  expect(route.request().headers()['x-stage2-consent']).toBe('true');
  const saved:GalleryImage={...image,id:'DEMO-uploaded-photo',image_kind:'source',source_description:'unknown',eligibility:'associated',eligibility_reason:'reference_photo_associated_only'};
  currentGallery=[{...gallery[0]!,images:[...gallery[0]!.images,saved]}];await route.fulfill({json:{photo:saved,duplicate:false}});
 });
 await openGallery(page);await page.locator('.gallery-entry').first().click();await page.getByRole('button',{name:'Add reference photo'}).click();
 await expect(page.getByRole('button',{name:'Take photo',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Choose existing photo',exact:true})).toBeVisible();
 await page.getByLabel('Choose a photo from device').setInputFiles({name:'DEMO-image.png',mimeType:'image/png',buffer:privatePng});await expect(page.getByRole('img',{name:'Selected image preview'})).toBeVisible();
 await page.getByRole('button',{name:'Continue'}).click();await expect(page.getByText('Step 2 of 6')).toBeVisible();await expect(page.getByText(/Automatic image content classification is unavailable/)).toBeVisible();await expect(page.getByLabel('Your description of the photo')).toHaveValue('loose_pill');expect(suggestionCalls).toBe(0);await page.getByLabel('Your description of the photo').selectOption('source');await page.getByRole('button',{name:'Continue'}).click();
 await page.getByLabel('Where did this image come from?').selectOption('unknown');await page.getByRole('button',{name:'Continue'}).click();
 await page.getByLabel('I confirm this photo is associated with the medication shown. This does not verify exact product identity.').check();await page.getByRole('button',{name:'Continue'}).click();
 await page.getByRole('button',{name:'Continue'}).click();await page.getByLabel('I agree to privately store and prepare this image for display.').check();await page.getByRole('button',{name:'Save reference photo'}).click();
 await expect.poll(()=>submitted).toMatchObject({image_kind:'source',source_description:'Unknown',reviewed:'true',for_comparison:'false'});await expect(page.locator('.gallery-file-tile')).toHaveCount(2);await expect(page.getByText('For your reference').first()).toBeVisible();
});

test('upload dialog confirms unsaved cancellation and keeps the gallery context',async({page})=>{
 await mockPatientApp(page);await page.route(url=>new URL(url).pathname==='/api/evidence/gallery',route=>route.fulfill({json:gallery}));await mockFiles(page,()=>gallery);
 await page.setViewportSize({width:1280,height:900});await openGallery(page);await page.locator('.gallery-entry').first().click();await page.getByRole('button',{name:'Add reference photo'}).click();
 const dialog=page.getByRole('dialog',{name:'Add a reference photo'});await expect(dialog).toBeVisible();
 await page.getByLabel('Choose a photo from device').setInputFiles({name:'DEMO-image.png',mimeType:'image/png',buffer:privatePng});
 await expect(page.getByRole('img',{name:'Selected image preview'})).toBeVisible();
 await page.keyboard.press('Escape');await expect(page.getByRole('alertdialog',{name:'Discard unsaved photo?'})).toBeVisible();
 await page.getByRole('button',{name:'Keep editing'}).click();await expect(page.getByRole('alertdialog')).toHaveCount(0);await expect(dialog).toBeVisible();await page.locator('.gallery-dialog-backdrop').click({position:{x:2,y:2}});await expect(page.getByRole('alertdialog')).toBeVisible();
 await page.getByRole('button',{name:'Keep editing'}).click();await expect(page.getByRole('alertdialog')).toHaveCount(0);await expect(dialog).toBeVisible();
 await page.getByRole('button',{name:'Cancel',exact:true}).click();await expect(page.getByRole('alertdialog')).toBeVisible();
 await page.getByRole('button',{name:'Discard changes'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 await expect(page).toHaveURL(/#gallery\?medication_id=DEMO-med/);await expect(page.getByRole('button',{name:'Add reference photo'})).toBeVisible();
});

test('duplicate upload explains reuse, opens the saved photo, and preserves the form for replacement',async({page})=>{
 await mockPatientApp(page);await page.route(url=>new URL(url).pathname==='/api/evidence/gallery',route=>route.fulfill({json:gallery}));await mockFiles(page,()=>gallery);
 await page.route('**/api/evidence/images/DEMO-photo',route=>route.fulfill({status:200,contentType:'image/png',body:privatePng}));
 await page.route(url=>new URL(url).pathname==='/api/evidence/gallery/DEMO-med/images',route=>route.fulfill({json:{photo:image,duplicate:true}}));
 await openGallery(page);await page.locator('.gallery-entry').first().click();await page.getByRole('button',{name:'Add reference photo'}).click();
 await page.getByLabel('Choose a photo from device').setInputFiles({name:'DEMO-image.png',mimeType:'image/png',buffer:privatePng});
 for(let step=0;step<3;step++)await page.getByRole('button',{name:'Continue'}).click();
 await page.getByLabel('I confirm this photo is associated with the medication shown. This does not verify exact product identity.').check();await page.getByRole('button',{name:'Continue'}).click();await page.getByRole('button',{name:'Continue'}).click();
 await page.getByLabel('I agree to privately store and prepare this image for display.').check();await page.getByRole('button',{name:'Save reference photo'}).click();
 await expect(page.getByRole('status')).toContainText('This photo is already saved for this medication. No duplicate copy was created.');
 await page.getByRole('button',{name:'View existing photo'}).click();await expect(page.getByRole('dialog')).toContainText('Photo details');
 await page.getByRole('button',{name:'Close photo details'}).click();const uploadDialog=page.getByRole('dialog',{name:'Add a reference photo'});await expect(uploadDialog).toBeVisible();
 for(let step=0;step<5;step++)await page.getByRole('button',{name:'Previous'}).click();await expect(page.getByRole('button',{name:'Replace photo'})).toBeVisible();
 await page.getByLabel('Choose a photo from device').setInputFiles({name:'DEMO-replacement.png',mimeType:'image/png',buffer:Buffer.from('another synthetic file')});
 await expect(page.getByRole('img',{name:'Selected image preview'})).toBeVisible();await expect(page.getByText('This photo is already saved for this medication. No duplicate copy was created.')).toHaveCount(0);
});

test('Chinese gallery, camera errors and localized medication details fit responsive layouts',async({page})=>{
 const zh=(...codepoints:number[])=>String.fromCharCode(...codepoints);
 const {prefs}=await mockPatientApp(page);prefs.preferred_language='zh';
 await page.addInitScript(()=>{Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>{throw new DOMException('permission denied','NotAllowedError');}}});});
 await page.route(url=>new URL(url).pathname==='/api/evidence/gallery',route=>route.fulfill({json:gallery}));await mockFiles(page,()=>gallery);
 await page.goto('/#gallery');await expect(page.getByRole('heading',{name:zh(0x6211,0x7684,0x836f,0x7269,0x8d44,0x6599,0x5e93)})).toBeVisible();
 await page.locator('.gallery-entry').first().click();
 await expect(page.getByRole('button',{name:zh(0x836f,0x7269,0x8be6,0x60c5)})).toBeVisible();
 await expect(page.getByRole('button',{name:zh(0x6dfb,0x52a0,0x53c2,0x8003,0x7167,0x7247)})).toBeVisible();
 await page.setViewportSize({width:1280,height:900});await page.getByRole('button',{name:zh(0x6dfb,0x52a0,0x53c2,0x8003,0x7167,0x7247)}).click();
 await expect(page.getByRole('button',{name:zh(0x62cd,0x6444,0x7167,0x7247)})).toBeVisible();
 await expect(page.getByRole('button',{name:zh(0x4ece,0x8bbe,0x5907,0x9009,0x62e9,0x7167,0x7247)})).toBeVisible();
 await page.getByRole('button',{name:zh(0x62cd,0x6444,0x7167,0x7247)}).click();
 await expect(page.getByRole('alert')).toContainText(zh(0x8bf7,0x5728,0x6d4f,0x89c8,0x5668,0x8bbe,0x7f6e,0x4e2d,0x5141,0x8bb8,0x4f7f,0x7528,0x76f8,0x673a));
 let bounds=await page.locator('.gallery-upload-dialog').boundingBox();expect(bounds).not.toBeNull();expect(bounds!.width).toBeLessThan(800);expect(bounds!.height).toBeLessThanOrEqual(828);
 await page.getByRole('button',{name:zh(0x53d6,0x6d88),exact:true}).click();await expect(page.getByRole('alertdialog')).toHaveCount(0);
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:zh(0x6dfb,0x52a0,0x53c2,0x8003,0x7167,0x7247)}).click();
 bounds=await page.locator('.gallery-upload-dialog').boundingBox();expect(bounds).not.toBeNull();expect(bounds!.width).toBe(390);expect(bounds!.height).toBe(844);
});
