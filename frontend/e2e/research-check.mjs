// Screenshot the Research Evidence page. Usage: node e2e/research-check.mjs <apiPort> <username> <password>
import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const [apiPort = '8000', username = 'official', password = ''] = process.argv.slice(2);
const output = resolve('..', '.demo', 'visual-audit');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
if (apiPort !== '8000') {
  await page.route('**/api/v1/**', route => route.continue({ url: route.request().url().replace(':5173', `:${apiPort}`) }));
}
await page.goto('http://127.0.0.1:5173/login');
await page.getByLabel('Username').fill(username);
await page.getByLabel('Password').fill(password);
await page.getByRole('button', { name: 'Sign in' }).click();
await page.waitForURL('http://127.0.0.1:5173/', { timeout: 15000 });
await page.evaluate(() => { history.pushState({}, '', '/research'); dispatchEvent(new PopStateEvent('popstate')); });
await page.waitForSelector('.research-figure img', { timeout: 20000 });
await page.waitForTimeout(2500);
for (const [w, h] of [[1366, 768], [390, 844]]) {
  await page.setViewportSize({ width: w, height: h });
  await page.waitForTimeout(800);
  await page.screenshot({ path: resolve(output, `Research-${w}.png`), fullPage: true });
  await page.screenshot({ path: resolve(output, `Research-top-${w}.png`), fullPage: false });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  console.log(`Research ${w}: overflow ${overflow}px`);
}
console.log('errors:', JSON.stringify(errors.slice(0, 10)));
await browser.close();
