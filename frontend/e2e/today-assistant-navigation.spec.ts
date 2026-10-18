import {test,expect} from '@playwright/test';
import {mockPatientApp} from './polish-a1-fixture';

test('Today Assistant jumps to medications and folds all recent exchanges after navigation',async({page})=>{
 page.setDefaultTimeout(10000);await page.setViewportSize({width:390,height:844});
 const {errors}=await mockPatientApp(page);
 await page.route(url=>new URL(url).pathname==='/api/agent/messages',route=>route.fulfill({json:{
  message:'SIMULATED answer',intent:'clarification',session_id:'DEMO-session',session_state:'idle',requires_confirmation:false,tool_traces:[],mode:'rules',
 }}));
 await page.goto('/e2e/patient-feedback.html?shell=1');
 const assistant=page.locator('.today-assistant'),medicationSection=page.locator('#today-medication');
 await assistant.getByRole('button',{name:'View today’s medication',exact:true}).click();
 await expect(medicationSection).toBeInViewport();

 await assistant.getByRole('button',{name:'Understand medicines',exact:true}).click();
 await assistant.getByRole('button',{name:'Send',exact:true}).click();
 await expect(assistant.locator('.turn')).toHaveCount(1);
 const secondQuestion='DEMO review my past seven days of dose reports and health observations';
 await assistant.getByRole('textbox').fill(secondQuestion);await assistant.getByRole('button',{name:'Send',exact:true}).click();
 await expect(assistant.locator('.turn')).toHaveCount(2);await expect(assistant.getByText(secondQuestion)).toBeVisible();
 const recent=assistant.locator('details.recent-chat');await expect(recent).toHaveAttribute('open','');
 await page.locator('[data-guide="medicines"]').click();await page.locator('[data-guide="today"]').click();
 await expect(recent).not.toHaveAttribute('open','');

 await assistant.locator('.today-assistant__expand').click();
 const workspace=page.locator('.conversation-workspace');
 await workspace.getByRole('button',{name:'View today’s medication',exact:true}).click();
 await expect(medicationSection).toBeInViewport();expect(errors).toEqual([]);
});
