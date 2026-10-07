import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import {LoadingSkeleton,EmptyState,Icon} from './ui';
export const human = (s:string|undefined|null) => s ? s.replaceAll('_',' ').toLowerCase().replace(/^./,c=>c.toUpperCase()) : 'Unavailable';
export const num=(v:unknown,digits=2)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-IN',{maximumFractionDigits:digits}):'Unavailable';
export const date=(v:string|null|undefined)=>v ? new Date(v).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}) : 'Unavailable';
export const candidate=(s:string|null|undefined)=>s==='BURNT'?'Burn evidence candidate':s?`${human(s)} candidate`:'Insufficient evidence';
export function Badge({children,tone='neutral'}:{children:ReactNode;tone?:string}){return <span className={`badge ${tone}`}>{children}</span>}
export function State({error,loading,empty,retry}:{error?:Error|null;loading?:boolean;empty?:string;retry?:()=>void}){
  if(loading)return <LoadingSkeleton/>;
  if(error)return <div className="state error" role="alert"><Icon name="alert" size={24}/><h2>Unable to load this view</h2><p>Unavailable. Please check the connection and try again.</p>{retry&&<button onClick={retry}>Retry</button>}</div>;
  return <EmptyState title={empty || 'No records yet.'}/>;
}
export function Panel({title,children,className=''}:{title:string;children:ReactNode;className?:string}){return <section className={`panel ${className}`}><h2>{title}</h2>{children}</section>}
export function Action({label,run,disabled=false,onSuccess}:{label:string;run:()=>Promise<unknown>;disabled?:boolean;onSuccess?:()=>void}){
  const client=useQueryClient();const mutation=useMutation({mutationFn:run,onSuccess:async()=>{await client.invalidateQueries({queryKey:['product']});onSuccess?.();}});
  return <span className="action"><button disabled={disabled||mutation.isPending} onClick={()=>mutation.mutate()}>{mutation.isPending?'Working…':label}</button>{mutation.error&&<span className="error-text" role="alert">{mutation.error.message}</span>}{mutation.isSuccess&&<span className="success-text" role="status">Saved</span>}</span>
}
export function Metric({label,value,note}:{label:string;value:ReactNode;note?:string}){return <div className="metric"><span>{label}</span><strong>{value}</strong>{note&&<small>{note}</small>}</div>}
export function Provenance({value}:{value:string}){return <Badge tone={value==='REAL'?'neutral':'demo'}>{value==='REAL'?'Real source':`${value} demonstration`}</Badge>}
