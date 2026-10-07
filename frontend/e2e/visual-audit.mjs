import { chromium } from '@playwright/test';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const root = resolve('..');
const output = resolve(root, '.demo', 'visual-audit');
await mkdir(output, { recursive: true });
const credentials = JSON.parse(await readFile(resolve(root, '.demo', 'credentials.json'), 'utf8'));
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const sizes = [[1366, 768], [1920, 1080], [768, 1024], [390, 844]];
const save = async (page, name, width) => {
  await page.waitForTimeout(350);
  await page.screenshot({ path: resolve(output, `${name}-${width}.png`), fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  process.stdout.write(`${name} ${width}: overflow ${overflow}px\n`);
  return overflow;
};
const navigate = async (page, path) => {
  await page.evaluate(path => { history.pushState({}, '', path); dispatchEvent(new PopStateEvent('popstate')); }, path);
  await page.waitForTimeout(300);
};
const routes = {
  official: [['Overview', '/'], ['Command Map', '/map'], ['Field Detail', '/fields/SYNTHETIC-ACTION-FIELD-01'], ['Dispatch', '/dispatch'], ['Verification', '/verification'], ['Certificates', '/certificates'], ['Balers', '/balers'], ['Buyers', '/buyers'], ['System', '/system']],
  farmer: [['Farmer', '/farmer']],
  operator: [['Operator', '/operator']],
  buyer: [['Buyer', '/buyer']],
};
for (const size of sizes) {
  const loginContext = await browser.newContext({ viewport: { width: size[0], height: size[1] } });
  const login = await loginContext.newPage();
  await login.goto('http://127.0.0.1:5173/login');
  await save(login, 'Login', size[0]);
  await loginContext.close();
}
for (const role of Object.keys(routes)) {
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:5173/login');
  await page.getByLabel('Username').fill(role);
  await page.getByLabel('Password').fill(credentials[role]);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL('http://127.0.0.1:5173/', { timeout: 10000 });
  for (const [name, route] of routes[role]) {
    await navigate(page, route);
    for (const [width, height] of sizes) {
      await page.setViewportSize({ width, height });
      await save(page, name, width);
    }
    if (name === 'Command Map') {
      await page.getByRole('button', { name: /SYNTHETIC-ACTION-FIELD-01/ }).click();
      for (const [width, height] of sizes) { await page.setViewportSize({ width, height }); await save(page, 'Field Drawer', width); }
    }
    if (name === 'Field Detail') {
      for (const tab of ['Satellite', 'History', 'Operations', 'Verification', 'Provenance']) {
        await page.getByRole('tab', { name: tab }).click();
        await save(page, `Field ${tab}`, 1366);
      }
      await page.getByRole('tab', { name: 'Overview' }).click();
    }
    if (name === 'Certificates') {
      const certificateLink = page.locator('.table-wrap tbody tr a').first();
      if (await certificateLink.count()) {
        const href = await certificateLink.getAttribute('href');
        await navigate(page, href);
        for (const [width, height] of sizes) { await page.setViewportSize({ width, height }); await save(page, 'Certificate Detail', width); }
        const certificateId = href.split('/').at(-1);
        await navigate(page, `/verify/${certificateId}`);
        await save(page, 'Certificate Public Verify', 1366);
        await navigate(page, '/certificates');
      }
    }
    if (name === 'Farmer') {
      const language = page.getByLabel('Language');
      for (const [value, label] of [['hi','Farmer Hindi'],['pa','Farmer Punjabi']]) {
        await language.selectOption(value);
        await save(page, label, 390);
      }
    }
    if (name === 'Overview') {
      for (const [width, height] of sizes.slice(0,2)) {
        await page.setViewportSize({width,height});
        await page.getByRole('button', {name:'Present'}).click();
        await save(page, 'Presentation Overview', width);
        await page.getByRole('button', {name:'Exit presentation'}).click();
      }
    }
  }
  if (errors.length) process.stderr.write(`${role} browser errors: ${errors.join('; ')}\n`);
  await context.close();
}
await browser.close();
