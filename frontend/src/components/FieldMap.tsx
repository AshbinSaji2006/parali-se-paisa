import { MapContainer, GeoJSON, CircleMarker, Popup, Polyline, TileLayer, useMap } from 'react-leaflet';
import { latLngBounds, type LatLngTuple } from 'leaflet';
import { useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { FieldRecord, Snapshot, Run } from '../api/types';
import { candidate, num, date } from './common';
const colors:Record<string,string>={STANDING:'#2b6949',HARVESTED:'#b87916',BURNT:'#af3f38',SOWN:'#306caa',UNKNOWN:'#68716c'};
export function FieldPopup({field,data}:{field:FieldRecord;data?:Snapshot}){
  const i=field.intelligence,j=data?.jobs.find(j=>j.field_id===field.field_id && !['CANCELLED','FAILED'].includes(j.state));
  return <div className="field-popup"><strong>{field.field_id}</strong><p>{candidate(i.field_status.status_candidate)}</p><dl>
    <dt>Area</dt><dd>{num(field.area_ha)} ha</dd><dt>Observation</dt><dd>{date(i.provenance.observation_datetime)}</dd><dt>Method</dt><dd>{i.field_status.method}</dd>
    <dt>Straw estimate</dt><dd>{num(i.straw.estimated_straw_tonnes)} t</dd><dt>Risk score</dt><dd>{num(i.burn_risk.risk_score)} / {i.burn_risk.risk_level || 'Unavailable'}</dd>
    <dt>Baler / buyer</dt><dd>{j?`${j.baler_id} / ${j.buyer_id}`:'Unassigned'}</dd><dt>Verification</dt><dd>{data?.verification.find(c=>c.field_id===field.field_id)?.state || 'Not started'}</dd>
    <dt>Certificate</dt><dd>{data?.certificates.some(c=>c.field_id===field.field_id)?'Prototype available':'Not issued'}</dd></dl><Link to={`/fields/${field.field_id}`}>View Field →</Link></div>
}
function Fit({fields}:{fields:FieldRecord[]}){const map=useMap();useEffect(()=>{const coords=fields.filter(f=>f.centroid.latitude!==null&&f.centroid.longitude!==null).map(f=>[f.centroid.latitude!,f.centroid.longitude!] as LatLngTuple);if(coords.length)map.fitBounds(latLngBounds(coords).pad(.3),{maxZoom:15});},[map,fields]);return null}
export default function FieldMap({fields,data,run,onSelect,selectedId,showFields=true,showBalers=true,showBuyers=true,showRoutes=true}:{fields:FieldRecord[];data?:Snapshot;run?:Run;onSelect?:(field:FieldRecord)=>void;selectedId?:string;showFields?:boolean;showBalers?:boolean;showBuyers?:boolean;showRoutes?:boolean}){
  const navigate=useNavigate();
  const tiles=import.meta.env.VITE_MAP_TILE_URL;
  const routes:LatLngTuple[][]=[];
  if(run&&data)for(const r of run.dispatch.baler_routes){const b=data.balers.find(b=>b.baler_id===r.baler_id);if(!b)continue;
    const line:LatLngTuple[]=[[b.current_location_lat??b.latitude,b.current_location_lon??b.longitude]];
    for(const s of r.stops){const f=fields.find(f=>f.field_id===s.field_id);if(f?.centroid.latitude!=null&&f.centroid.longitude!=null)line.push([f.centroid.latitude,f.centroid.longitude]);}
    // Buyer legs are separate context lines, not included in the optimiser's return-to-baler distance.
    routes.push(line);
    for(const s of r.stops){const f=fields.find(f=>f.field_id===s.field_id),buyer=data.buyers.find(b=>b.buyer_id===s.buyer_id);if(f?.centroid.latitude!=null&&f.centroid.longitude!=null&&buyer)routes.push([[f.centroid.latitude,f.centroid.longitude],[buyer.latitude,buyer.longitude]]);}
  }
  return <><div className="map" data-testid="field-map" aria-label={`Field map with ${fields.length} fields`}><MapContainer center={[30.024,74.524]} zoom={14} scrollWheelZoom={false}>
    {tiles&&<TileLayer url={tiles} attribution={import.meta.env.VITE_MAP_ATTRIBUTION || 'Configured basemap provider'}/>}
    <Fit fields={fields}/>{showFields&&fields.map(f=>{const i=f.intelligence,color=colors[f.intelligence.field_status.status_candidate||'UNKNOWN']||colors.UNKNOWN;
      const verified=data?.verification.some(v=>v.field_id===f.field_id&&v.state==='NO_BURN_VERIFIED');
      const manual=data?.verification.some(v=>v.field_id===f.field_id&&v.state==='MANUAL_REVIEW_REQUIRED');
      const burn=data?.verification.some(v=>v.field_id===f.field_id&&v.state==='BURN_SIGNAL_DETECTED');
      const high=i.burn_risk.risk_level==='HIGH';
      const outline=selectedId===f.field_id?'#122d24':burn?'#a53b34':manual?'#765483':verified?'#27805a':high?'#c06230':color;
      const popup=<Popup><FieldPopup field={f} data={data}/></Popup>;
      return f.geometry?<GeoJSON key={f.field_id} data={f.geometry} style={{color:outline,weight:selectedId===f.field_id?5:verified||high||manual||burn?4:2,fillColor:color,fillOpacity:.44}}
        onEachFeature={(_feature,layer)=>{const root=document.createElement('div');root.className='field-popup';
          const title=document.createElement('strong');title.textContent=f.field_id;root.append(title);
          const text=document.createElement('p');text.textContent=`${candidate(i.field_status.status_candidate)} · ${i.field_status.method}`;root.append(text);
          const metrics=document.createElement('p');metrics.textContent=`${num(f.area_ha)} ha · Straw ${num(i.straw.estimated_straw_tonnes)} t · Risk score ${num(i.burn_risk.risk_score)} / ${i.burn_risk.risk_level||'Unavailable'}`;root.append(metrics);
          const assigned=data?.jobs.find(j=>j.field_id===f.field_id&&!['CANCELLED','FAILED'].includes(j.state));
          const destination=document.createElement('p');destination.textContent=assigned?`${assigned.baler_id} → ${assigned.field_id} → ${assigned.buyer_id}`:'Baler / buyer: Unassigned';root.append(destination);
          const ver=data?.verification.find(x=>x.field_id===f.field_id);const verification=document.createElement('p');verification.textContent=`Verification: ${ver?.state||'Not started'} · Certificate: ${data?.certificates.some(c=>c.field_id===f.field_id)?'Prototype available':'Not issued'}`;root.append(verification);
          const link=document.createElement('a');link.href=`/fields/${encodeURIComponent(f.field_id)}`;link.textContent='View Field';link.addEventListener('click',event=>{event.preventDefault();navigate(link.getAttribute('href')!);});root.append(link);
          layer.bindPopup(root);
          layer.on('click',()=>onSelect?.(f));
          layer.on('mouseover',()=>{if('setStyle' in layer) (layer as unknown as {setStyle:(style:object)=>void}).setStyle({weight:5,fillOpacity:.6});});
          layer.on('mouseout',()=>{if('setStyle' in layer) (layer as unknown as {setStyle:(style:object)=>void}).setStyle({weight:selectedId===f.field_id?5:verified||high||manual||burn?4:2,fillOpacity:.44});});
        }} />:f.centroid.latitude!==null&&f.centroid.longitude!==null?<CircleMarker key={f.field_id} center={[f.centroid.latitude,f.centroid.longitude]} radius={10} pathOptions={{color:outline,fillColor:color,fillOpacity:.7,weight:verified||high||manual||burn?4:2}} eventHandlers={{click:()=>onSelect?.(f)}}>{popup}</CircleMarker>:null;
    })}{showRoutes&&routes.map((positions,index)=><Polyline key={index} positions={positions} pathOptions={{color:'#234e40',dashArray:'6 8',weight:3}}/>)}
    {showBalers&&run&&data?.balers.filter(b=>run.dispatch.baler_routes.some(r=>r.baler_id===b.baler_id)).map(b=><CircleMarker key={b.baler_id} center={[b.current_location_lat??b.latitude,b.current_location_lon??b.longitude]} radius={7} pathOptions={{color:'#245d57',fillColor:'#245d57',fillOpacity:1}}><Popup>Baler: {b.name}</Popup></CircleMarker>)}
    {showBuyers&&run&&data?.buyers.filter(b=>run.buyer_matching.allocations.some(a=>a.buyer_id===b.buyer_id)).map(b=><CircleMarker key={b.buyer_id} center={[b.latitude,b.longitude]} radius={8} pathOptions={{color:'#66548c',fillColor:'#66548c',fillOpacity:1}}><Popup>Buyer: {b.name}</Popup></CircleMarker>)}
  </MapContainer></div><div className="map-caption">{tiles?'Configured basemap':'Offline coordinate map · basemap unavailable'} · Polygons are registered boundaries; circles mark fields without geometry.</div>
  <div className="legend">{Object.entries(colors).map(([key,color])=><span key={key}><i style={{background:color}}/>{candidate(key==='UNKNOWN'?null:key)}</span>)}<span><i style={{background:'#703ca0'}}/>Prototype evidence checks passed</span></div>{run&&<p className="notice">Straight-line planning proxy (GEODESIC_PROXY). Dashed buyer legs show destination context; route distance covers baler → fields → baler. No road route or travel time is available.</p>}</>
}
