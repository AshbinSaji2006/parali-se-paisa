import {test,expect,type Page} from '@playwright/test';

async function login(page:Page,username:string,password:string){
 await page.goto('/login');await page.getByLabel('Username').fill(username);await page.getByLabel('Password').fill(password);
 await page.getByRole('button',{name:'Sign in'}).click();await expect(page.getByRole('heading',{name:'Field operations',exact:true})).toBeVisible();
}
test('official field investigation and dispatch workflow',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await login(page,'official','offline-judge-password');
 await page.getByRole('link',{name:'Command Map'}).first().click();await expect(page.getByTestId('field-map')).toBeVisible();
 await page.getByRole('button',{name:/SYNTHETIC-ACTION-FIELD-01/}).click();
 await page.getByRole('link',{name:'View details'}).click();
 await expect(page.getByText('Harvested candidate',{exact:true}).first()).toBeVisible();await expect(page.getByText('NORMALIZED_RULE_SCORE_NOT_PROBABILITY')).toBeVisible();
 await page.getByRole('main').getByRole('link',{name:'Dispatch',exact:true}).click();await page.getByRole('button',{name:'Optimise dispatch'}).click();
 await expect(page.getByRole('heading',{name:/Route.*DEMO-BALER/})).toBeVisible({timeout:20_000});await expect(page.getByText(/Dashed buyer legs show destination context/).first()).toBeVisible();
 await page.getByRole('link',{name:'Verification',exact:true}).first().click();await expect(page.getByRole('heading',{name:'Verification centre'})).toBeVisible();
 await page.getByRole('link',{name:'SYNTHETIC-ACTION-FIELD-01'}).click();await expect(page.getByRole('heading',{name:'Monitoring',exact:true}).last()).toBeVisible();
 for(let i=0;i<3;i++){const action=page.getByRole('button',{name:'Process next stored synthetic observation'});if(await action.isVisible())await action.click();}
 await expect(page.getByRole('heading',{name:'No burn verified',exact:true}).last()).toBeVisible({timeout:15_000});await expect(page.getByText(/3 stored observations/).first()).toBeVisible();
 await page.getByRole('button',{name:'Generate prototype certificate'}).click();await expect(page.getByRole('status').getByText('Saved')).toBeVisible({timeout:15_000});
 await page.getByRole('link',{name:'Certificates',exact:true}).click();await expect(page.getByRole('heading',{name:'Certificate registry'})).toBeVisible();
 await page.locator('.table-wrap tbody tr a').first().click();await expect(page.getByRole('heading',{name:'Prototype Verification Certificate'})).toBeVisible();
 await expect(page.getByText('Observation count')).toBeVisible();await expect(page.getByRole('img',{name:/QR code for the certificate/})).toBeVisible();await expect(page.getByRole('link',{name:'Open PDF'})).toBeVisible();
 for(const [width,height] of [[1366,768],[1920,1080],[768,1024],[390,844]]){await page.setViewportSize({width,height});const [overflow,offenders]=await page.evaluate(()=>[document.documentElement.scrollWidth-window.innerWidth,Array.from(document.querySelectorAll('*')).filter(el=>el.getBoundingClientRect().right>innerWidth+1).slice(0,8).map(el=>`${el.tagName}.${el.className} right=${Math.round(el.getBoundingClientRect().right)}`)] as const);expect(overflow,`horizontal overflow at ${width}×${height}: ${offenders.join('; ')}`).toBeLessThanOrEqual(0);}
 expect(errors).toEqual([]);
});

test('unauthenticated admin pages require sign-in and mobile layout fits viewport',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/');await expect(page.getByRole('heading',{name:'Sign in required'})).toBeVisible();
 await page.getByRole('link',{name:'Go to sign in'}).click();await login(page,'farmer','offline-judge-password');
 await page.getByRole('button',{name:'Menu'}).click();await page.getByRole('link',{name:'Farmer Portal'}).click();await expect(page.getByRole('heading',{name:'Your field update'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});
