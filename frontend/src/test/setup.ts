import '@testing-library/jest-dom/vitest';
import {afterEach,vi} from 'vitest';
import {cleanup} from '@testing-library/react';
afterEach(()=>{cleanup();vi.restoreAllMocks();});
Object.defineProperty(window,'matchMedia',{writable:true,value:(query:string)=>({matches:query.includes('max-width: 720px'),media:query,onchange:null,addListener:()=>{},removeListener:()=>{},addEventListener:()=>{},removeEventListener:()=>{},dispatchEvent:()=>false})});
class ResizeObserverMock{observe(){}unobserve(){}disconnect(){}}
Object.defineProperty(window,'ResizeObserver',{value:ResizeObserverMock});
