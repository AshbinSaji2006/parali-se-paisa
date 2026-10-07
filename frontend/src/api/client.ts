import { snapshotSchema, type Snapshot, type User, type SystemStatus, type Run, type Certificate, type Verification } from './types';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');
let token: string | null = null; // Memory only. Reload requires login; no persistent token storage.
export const setToken = (value:string|null) => { token=value; };
export class ApiError extends Error { constructor(public status:number,message:string){super(message);} }
export async function request<T>(path:string, options:RequestInit = {}):Promise<T> {
  let response:Response;
  try { response=await fetch(API_BASE+path,{...options,headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(token?{Authorization:`Bearer ${token}`} : {}),...options.headers}}); }
  catch {throw new ApiError(0,'Cannot reach the backend. Check the connection and retry.');}
  if(!response.ok){
    const body=await response.json().catch(()=>({}));
    const detail=Array.isArray(body.detail)?body.detail.map((e:{loc:string[];msg:string})=>`${e.loc?.slice(1).join('.')}: ${e.msg}`).join('; '):body.detail;
    if(response.status===401 && token){setToken(null); window.dispatchEvent(new Event('session-expired'));}
    throw new ApiError(response.status, detail || `Request failed (${response.status}). Please retry.`);
  }
  return response.json() as Promise<T>;
}
export async function requestObjectUrl(path:string):Promise<string>{
  let response:Response;
  try { response=await fetch(API_BASE+path,{headers:token?{Authorization:`Bearer ${token}`}:{}}); }
  catch {throw new ApiError(0,'Cannot reach the backend. Check the connection and retry.');}
  if(!response.ok) throw new ApiError(response.status,`Request failed (${response.status}).`);
  return URL.createObjectURL(await response.blob());
}
const post=<T>(path:string,body?:unknown)=>request<T>(path,{method:'POST',...(body===undefined?{}:{body:JSON.stringify(body)})});
export const api={
  login:(username:string,password:string)=>post<{access_token:string;user:User}>('/auth/login',{username,password}),
  me:()=>request<User>('/auth/me'),
  product:async()=>snapshotSchema.parse(await request<unknown>('/product')) as unknown as Snapshot,
  status:()=>request<SystemStatus>('/system-status'), health:()=>request<{status:string;database:string}>('/health'),
  optimise:()=>post<Run>('/dispatch/optimise',{}),
  transition:(id:string,state:string)=>request(`/jobs/${encodeURIComponent(id)}/state`,{method:'PATCH',body:JSON.stringify({state})}),
  evidence:(scenario:string)=>post<Verification>(`/demo/evidence/${scenario}`),
  evaluate:(id:string)=>post<Verification>(`/verification/${encodeURIComponent(id)}/evaluate`),
  startVerification:(field:string)=>post<Verification>(`/verification/start/${encodeURIComponent(field)}`,{}),
  generate:(id:string)=>post<Certificate>(`/certificates/generate/${encodeURIComponent(id)}`),
  certificate:(id:string)=>request<Certificate>(`/public/certificates/${encodeURIComponent(id)}`),
  pickup:(id:string)=>post(`/pickup/${encodeURIComponent(id)}`),
  balerStatus:(id:string,status:string)=>request(`/balers/${encodeURIComponent(id)}`,{method:'PATCH',body:JSON.stringify({status})}),
  buyerStatus:(id:string,status:string)=>request(`/buyers/${encodeURIComponent(id)}`,{method:'PATCH',body:JSON.stringify({status})}),
};
