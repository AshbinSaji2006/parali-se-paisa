import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',fullyParallel:false,workers:1,timeout:90_000,retries:0,reporter:'list',
 use:{baseURL:'http://127.0.0.1:5173',viewport:{width:1366,height:768},headless:true,launchOptions:{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--no-sandbox']}}
});
