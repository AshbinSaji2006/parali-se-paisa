import { chromium } from '@playwright/test';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const root = resolve('..'), output = resolve(root, '.demo', 'visual-audit');
await mkdir(output, { recursive: true });
const credentials = JSON.parse(await readFile(resolve(root, '.demo', 'credentials.json'), 'utf8'));
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
const page = await context.newPage();
page.on('pageerror', error => process.stderr.write(`Browser error: ${error.stack}\n`));
let token = '';
page.on('response', async response => {
  if (response.url().endsWith('/api/v1/auth/login') && response.ok()) token = (await response.json()).access_token;
});
await page.goto('http://127.0.0.1:5173/login');
await page.getByLabel('Username').fill('official');
await page.getByLabel('Password').fill(credentials.official);
await page.getByRole('button', { name: 'Sign in' }).click();
await page.getByRole('heading', { name: 'Field operations', exact: true }).waitFor();
await page.getByRole('link', { name: 'Command Map', exact: true }).click();
await page.getByRole('button', { name: /SYNTHETIC-ACTION-FIELD-01/ }).click();
await page.waitForTimeout(350);
await page.screenshot({ path: resolve(output, 'Field-Drawer-1366.png'), fullPage: true });
await page.screenshot({ path: resolve(output, 'Command-Map-Populated-1366.png'), fullPage: true });
await page.getByRole('link', { name: /View details/ }).click();
await page.screenshot({ path: resolve(output, 'Field-Detail-Populated-1366.png'), fullPage: true });
await page.getByRole('link', { name: 'Dispatch', exact: true }).first().click();
if (await page.getByRole('button', { name: 'Optimise dispatch' }).isEnabled()) await page.getByRole('button', { name: 'Optimise dispatch' }).click();
await page.getByRole('heading', { name: /Route.*DEMO-BALER/ }).waitFor();
for (const [width,height] of [[1366,768],[1920,1080],[390,844]]) {
  await page.setViewportSize({width,height});
  await page.waitForTimeout(350);
  await page.screenshot({path:resolve(output, `Dispatch-Populated-${width}.png`),fullPage:true});
}
const call = async (path,body={}) => {
  const response = await context.request.post(`http://127.0.0.1:8000/api/v1${path}`, { data: body, headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok()) throw new Error(`${path}: ${response.status()}`);
  return response.json();
};
const snapshotResponse = await context.request.get('http://127.0.0.1:8000/api/v1/product', { headers: { Authorization: `Bearer ${token}` } });
const snapshot = await snapshotResponse.json();
let certificate = snapshot.certificates.find(c=>c.field_id==='SYNTHETIC-ACTION-FIELD-01');
if (!certificate) {
  let verification;
  for (let index=0; index<3; index++) verification = await call('/demo/evidence/safe');
  certificate = await call(`/certificates/generate/${verification.verification_id}`);
}
await page.setViewportSize({width:1366,height:768});
await page.waitForTimeout(5500);
const navigate = async path => {await page.evaluate(path => {history.pushState({},'',path);dispatchEvent(new PopStateEvent('popstate'));},path);await page.waitForTimeout(1000);};
await navigate('/verification/SYNTHETIC-ACTION-FIELD-01');
process.stdout.write(`Verification: ${(await page.locator('body').innerText()).slice(0,80)}\n`);
await page.screenshot({path:resolve(output,'Verification-Detail-1366.png'),fullPage:true});
await navigate('/');
await page.screenshot({path:resolve(output,'Overview-Populated-1366.png'),fullPage:true});
await navigate('/verification');
await page.screenshot({path:resolve(output,'Verification-Centre-Populated-1366.png'),fullPage:true});
await navigate('/certificates');
process.stdout.write(`Registry: ${(await page.locator('body').innerText()).slice(0,80)}\n`);
await page.screenshot({path:resolve(output,'Certificate-Registry-Populated-1366.png'),fullPage:true});
await navigate(`/certificates/${certificate.certificate_id}`);
process.stdout.write(`Certificate: ${(await page.locator('body').innerText()).slice(0,80)}\n`);
await page.screenshot({path:resolve(output,'Certificate-Detail-1366.png'),fullPage:true});
await navigate(`/verify/${certificate.certificate_id}`);
await page.screenshot({path:resolve(output,'Certificate-Verification-1366.png'),fullPage:true});
await page.setViewportSize({width:390,height:844});
await page.waitForTimeout(400);
await page.screenshot({path:resolve(output,'Certificate-Detail-390.png'),fullPage:true});
await context.close();
for (const [role,route] of [['farmer','/farmer'],['operator','/operator'],['buyer','/buyer']]) {
  const portalContext = await browser.newContext({viewport:{width:1366,height:768}}), portal = await portalContext.newPage();
  await portal.goto('http://127.0.0.1:5173/login'); await portal.getByLabel('Username').fill(role); await portal.getByLabel('Password').fill(credentials[role]); await portal.getByRole('button',{name:'Sign in'}).click();
  await portal.waitForTimeout(500);
  await portal.goto(`http://127.0.0.1:5173${route}`); await portal.waitForTimeout(900);
  await portal.screenshot({path:resolve(output,`${role[0].toUpperCase()+role.slice(1)}-Portal-Populated-1366.png`),fullPage:true});
  await portalContext.close();
}
await browser.close();
