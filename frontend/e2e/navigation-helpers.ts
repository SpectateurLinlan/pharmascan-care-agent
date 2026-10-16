import {expect,type Page} from '@playwright/test';

/** Live journey tests explicitly skip the first-use tour; dedicated UX tests exercise it. */
export async function skipInitialGuide(page:Page){
  const skip=page.getByRole('button',{name:'Skip for now',exact:true});
  // The modal guide deliberately hides/inerts its background. Wait for either
  // ready state, then dismiss the guide before requiring the composer.
  await expect.poll(async()=>await skip.isVisible()||await page.locator('.composer-row').isVisible(),{timeout:120000}).toBe(true);
  if(await skip.isVisible())await skip.click();
  await expect(page.locator('.composer-row')).toBeVisible();
}
