import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CircleMarker, ImageOverlay, MapContainer, Popup, useMap } from 'react-leaflet';
import { latLngBounds, type LatLngBoundsExpression } from 'leaflet';
import { request, requestObjectUrl } from '../api/client';
import { Badge, Metric, Panel, State, date, num } from '../components/common';
import { EmptyState, LoadingSkeleton, PageHeader, SectionHeader } from '../components/ui';

type CensusRow = { year: number; viirs_alerts: number; viirs_alerts_incl_noaa21: number; modis_alerts: number; crop_fields: number; crop_ha: number;
  burned_strict_ha: number; burned_loose_ha: number; burned_strict_share: number; burned_loose_share: number; strict_fields_per_viirs_alert: number;
  burns_with_viirs_short_window: number; control_with_viirs_short_window: number; viirs_alerts_with_s2_burn_nearby: number; s2_dates: number };
type ReplayRow = { fleet: number; policy: string; preempted_share: number; preempted_ha: number; baled_t: number };
type Week = { week_start: string; expected_harvest_ha: number; range_ha: [number, number]; expected_baleable_straw_t: number; expected_total_straw_t: number };
type Overlay = { name: string; png: string; bounds: [[number, number], [number, number]]; year: number; kind: string; legend: [string, string][] };
type Summary = { notice: string; data_mode: string; figures: string[]; overlays: Overlay[]; results: {
  census: CensusRow[]; latency: Record<string, { median_days: number; share_within_5d: number }>; replay: ReplayRow[];
  replay_impact: Record<string, { preempted_share: number; fifo_share: number; preempted_ha: number; avoided_CH4_N2O_CO2e_t: number; avoided_PM25_t: number; straw_value_preempted_rs_crore: number }>;
  risk_model: Record<string, unknown> & { persistence: { p_burn_given_prior_burn: number; p_burn_given_no_prior: number } };
  emissions_burned_area: Record<string, { strict: Record<string, { median: number; p05: number; p95: number }>; loose: Record<string, { median: number; p05: number; p95: number }> }>;
  nowcast_2026: { latest_image: string; harvested_share_now: number; same_date_prior: Record<string, number>; crop_ha: number; district_straw_total_t: number; weekly_forecast: Week[]; preseason_risk: { top_decile_fields: number; top_decile_ha: number } };
  caveats: string[] } };
type Fire = { date: string; lat: number; lon: number; sensor: string; frp_mw: number | null };
type WatchItem = { field_id: string; lat: number; lon: number; area_ha: number; risk_decile: number; burned_last_season: boolean; neighbourhood_burn_rate_last_season: number; harvested_2026: boolean };
type SeasonEvent = { year: number; harvest_observed: string | null; burn_tier: string; burn_observed: string | null; last_unburned_observation: string | null; harvest_to_burn_days: number | null; peak_ndvi: number };

const FIGURES: Record<string, [string, string]> = {
  'f1_alerts_vs_scars.png': ['Fire alerts fell, burn scars did not', 'VIIRS active-fire alerts against Sentinel-2 burn-scar area, indexed to 2023, at a harmonised 5-day revisit.'],
  'f2_blind_spot.png': ['The fire-count blind spot', 'Share of Sentinel-2 confirmed burns with any VIIRS alert within 500 m, against a proximity control.'],
  'f3_smoke_blindness.png': ['Smoke blinds optical monitoring', 'Clear-sky observability collapses during peak burning; the SWIR-based detector keeps most fields observable.'],
  'f4_naive_vs_aware.png': ['Harvest-aware burn detection', 'A naive dNBR mistakes the paddy harvest for a fire; harvest-aware logic scores only post-harvest char.'],
  'f5_intervention_window.png': ['The intervention window', 'Days from the first harvested observation to the first char observation, 2025.'],
  'f6_replay.png': ['Season replay: dispatch policies', 'Share of real 2025 burns a baler fleet could have pre-empted under each dispatch policy.'],
  'f7_nowcast_2026.png': ['Live 2026 harvest nowcast', 'This season against the 2023-2025 harvest curves.'],
  'f8_burn_map_2025.png': ['District burn-scar map, 2025', 'Every crop field classified by Sentinel-2 burn tier, with VIIRS alerts overlaid.'],
};

const pct = (v: number | undefined | null, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? `${(100 * v).toFixed(d)}%` : 'Unavailable');

function useObjectUrl(path: string | null) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!path) return;
    let live = true, made: string | null = null;
    requestObjectUrl(path).then(u => { made = u; if (live) setUrl(u); else URL.revokeObjectURL(u); }).catch(() => live && setFailed(true));
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [path]);
  return { url, failed };
}

function Figure({ name }: { name: string }) {
  const { url, failed } = useObjectUrl(`/research/figures/${name}`);
  const [title, caption] = FIGURES[name] || [name, ''];
  return <figure className="research-figure"><figcaption><strong>{title}</strong><span>{caption}</span></figcaption>
    {url ? <img src={url} alt={`${title}. ${caption}`} loading="lazy" /> : failed ? <EmptyState title="Figure unavailable" /> : <div className="research-figure-loading" role="status">Loading figure…</div>}</figure>;
}

function FitTo({ bounds }: { bounds: LatLngBoundsExpression }) { const map = useMap(); useEffect(() => { map.fitBounds(bounds); }, [map, bounds]); return null; }

function BurnMap({ overlays }: { overlays: Overlay[] }) {
  const [name, setName] = useState(overlays.find(o => o.year === 2025)?.name || overlays[0]?.name || '');
  const [showFires, setShowFires] = useState(false);
  const layer = overlays.find(o => o.name === name);
  const img = useObjectUrl(layer ? `/research/overlays/${layer.png}` : null);
  const fires = useQuery({ queryKey: ['research-fires', layer?.year], queryFn: () => request<{ items: Fire[] }>(`/research/fires/${layer?.year}`), enabled: !!layer && layer.kind === 'burn_tier' });
  const bounds = useMemo(() => layer ? latLngBounds(layer.bounds) : null, [layer]);
  if (!layer || !bounds) return <EmptyState title="Map overlays not built" detail="Run scripts/build_research_maps.py" />;
  return <Panel title="Field-level burn-scar and risk map" className="research-map-panel">
    <div className="filter-bar" role="group" aria-label="Map layer">
      {overlays.map(o => <button key={o.name} className={o.name === name ? 'button' : 'secondary-button'} aria-pressed={o.name === name} onClick={() => setName(o.name)}>{o.kind === 'risk_decile' ? `${o.year} pre-season risk` : `${o.year} burn scars`}</button>)}
      {layer.kind === 'burn_tier' && <label className="checkbox-label"><input type="checkbox" checked={showFires} onChange={e => setShowFires(e.target.checked)} /> VIIRS fire alerts ({fires.data?.items.length ?? '…'})</label>}
    </div>
    <div className="map research-map" aria-label={`Map of ${layer.name}`}><MapContainer bounds={bounds} scrollWheelZoom={false} zoomSnap={0.25}>
      <FitTo bounds={bounds} />
      {img.url && <ImageOverlay url={img.url} bounds={bounds} opacity={0.95} />}
      {showFires && layer.kind === 'burn_tier' && fires.data?.items.map((f, i) => <CircleMarker key={i} center={[f.lat, f.lon]} radius={2} pathOptions={{ stroke: false, fillColor: '#0b0b0b', fillOpacity: 0.8 }}>
        <Popup><strong>{f.sensor.replace('_', ' ')}</strong><br />{date(f.date)}{f.frp_mw !== null ? ` · ${f.frp_mw} MW` : ''}</Popup></CircleMarker>)}
    </MapContainer></div>
    <div className="legend">{layer.legend.map(([label, color]) => <span key={label}><i style={{ background: color }} />{label}</span>)}{layer.kind === 'burn_tier' && <span><i style={{ background: '#0b0b0b', borderRadius: '50%' }} />VIIRS 375 m fire alert</span>}</div>
    <p className="map-caption">Fields of The World research boundaries rasterised at 20 m. Burn tiers are rule-derived Sentinel-2 candidates for pickup prioritisation, not enforcement evidence.</p>
  </Panel>;
}

export function ResearchEvents({ fieldId }: { fieldId: string }) {
  const q = useQuery({ queryKey: ['research-field', fieldId], queryFn: () => request<{ seasons: SeasonEvent[] }>(`/research/fields/${encodeURIComponent(fieldId)}/events`), retry: false });
  if (q.isLoading) return null;
  if (!q.data) return <Panel title="Satellite season events"><EmptyState title="No dense-time-series events for this field" detail="Research events cover Fields of The World polygons with at least 3 Sentinel-2 pixels." /></Panel>;
  return <Panel title="Satellite season events (dense Sentinel-2)"><div className="table-wrap"><table><thead><tr><th>Season</th><th>Harvest observed</th><th>Burn tier</th><th>Burn observed</th><th>Harvest → burn</th></tr></thead><tbody>
    {q.data.seasons.map(s => <tr key={s.year}><td>{s.year}</td><td>{s.harvest_observed ? date(s.harvest_observed) : 'Not yet'}</td><td><Badge tone={s.burn_tier === 'CHAR_STRICT' ? 'danger' : s.burn_tier === 'CHAR_LOOSE' ? 'warning' : 'neutral'}>{s.burn_tier === 'NONE' ? 'No burn candidate' : s.burn_tier === 'CHAR_STRICT' ? 'Char confirmed' : 'Burn candidate'}</Badge></td><td>{s.burn_observed ? `${date(s.last_unburned_observation)} – ${date(s.burn_observed)}` : '—'}</td><td>{s.harvest_to_burn_days !== null ? `${s.harvest_to_burn_days} days` : '—'}</td></tr>)}
  </tbody></table></div><p className="notice">Rule-derived candidates from harvest-aware Sentinel-2 logic; not ground truth and never a basis for penalties.</p></Panel>;
}

export function Research() {
  const q = useQuery({ queryKey: ['research-summary'], queryFn: () => request<Summary>('/research/summary'), staleTime: 60_000 });
  const watch = useQuery({ queryKey: ['research-watch'], queryFn: () => request<{ items: WatchItem[]; notice: string }>('/research/watchlist?limit=8') });
  if (q.isLoading) return <LoadingSkeleton />;
  if (!q.data) return <State error={q.error as Error} retry={() => q.refetch()} />;
  const r = q.data.results;
  const c = Object.fromEntries(r.census.map(x => [x.year, x])) as Record<number, CensusRow>;
  const c23 = c[2023], c25 = c[2025];
  const imp = r.replay_impact['100'];
  const now = r.nowcast_2026;
  const fleets = [...new Set(r.replay.map(x => x.fleet))];
  const policies: [string, string][] = [['fifo', 'First harvested, first served'], ['random', 'Random'], ['dynamic', 'Contagion hazard, re-scored each pass'], ['risk', 'Pre-season history ranking (ours)'], ['oracle', 'Oracle (upper bound)']];
  const em25 = r.emissions_burned_area['2025'];
  return <>
    <PageHeader eyebrow="REAL SATELLITE EVIDENCE · SRI MUKTSAR SAHIB · 2023–2026" title="Research evidence" description="Dense Sentinel-2 time series for every field in the district, matched against VIIRS/MODIS fire alerts and replayed as a dispatch digital twin." />
    <p className="notice">{q.data.notice}</p>
    <div className="metric-grid">
      <Metric label="VIIRS fire alerts, 2023 → 2025" value={`−${Math.round(100 * (1 - c25.viirs_alerts / c23.viirs_alerts))}%`} note={`${num(c23.viirs_alerts, 0)} → ${num(c25.viirs_alerts, 0)} alerts (S-NPP + NOAA-20)`} />
      <Metric label="Char-confirmed burn area, 2025 vs 2023" value={`${Math.round(100 * c25.burned_strict_ha / c23.burned_strict_ha)}`} note={`index · ${num(c25.burned_strict_ha, 0)} ha strict, ${num(c25.burned_loose_ha, 0)} ha loose`} />
      <Metric label="Confirmed burns with a VIIRS alert, 2025" value={pct(c25.burns_with_viirs_short_window)} note={`proximity control ${pct(c25.control_with_viirs_short_window)} · ≤5-day windows`} />
      <Metric label="Intervention window" value={`${r.latency['2025'].median_days} days`} note="median, first harvested → first char observation (2025)" />
      <Metric label="Burns pre-empted with 100 balers" value={pct(imp.preempted_share)} note={`risk-ranked vs ${pct(imp.fifo_share, 1)} first-come-first-served`} />
      <Metric label={`2026 harvest, ${date(now.latest_image)}`} value={pct(now.harvested_share_now, 1)} note={`same date: ${Object.entries(now.same_date_prior).map(([y, v]) => `${y} ${pct(v, 1)}`).join(' · ')}`} />
    </div>
    <BurnMap overlays={q.data.overlays} />
    <SectionHeader title="Findings" aside={<Badge>REAL DATA</Badge>} />
    <div className="research-grid">{q.data.figures.filter(f => FIGURES[f]).map(f => <Figure key={f} name={f} />)}</div>
    <div className="detail-grid">
      <Panel title="Season census (harmonised 5-day revisit)"><div className="table-wrap"><table><thead><tr><th>Season</th><th>VIIRS alerts</th><th>Strict burn ha</th><th>Loose burn ha</th><th>Burned fields per alert</th><th>Alerts with S2 burn nearby</th></tr></thead><tbody>
        {r.census.map(x => <tr key={x.year}><td>{x.year}</td><td>{num(x.viirs_alerts, 0)}</td><td>{num(x.burned_strict_ha, 0)}</td><td>{num(x.burned_loose_ha, 0)}</td><td>{num(x.strict_fields_per_viirs_alert, 1)}</td><td>{pct(x.viirs_alerts_with_s2_burn_nearby)}</td></tr>)}
      </tbody></table></div><p className="map-caption">2024 burn area is a lower bound: smog removed 3–21 Nov observations.</p></Panel>
      <Panel title="Dispatch replay, 2025 (share of burns pre-empted)"><div className="table-wrap"><table><thead><tr><th>Policy</th>{fleets.map(f => <th key={f}>{f} balers</th>)}</tr></thead><tbody>
        {policies.map(([p, label]) => <tr key={p}><td>{label}</td>{fleets.map(f => <td key={f}>{pct(r.replay.find(x => x.fleet === f && x.policy === p)?.preempted_share, 1)}</td>)}</tr>)}
      </tbody></table></div><p className="map-caption">With 100 balers, risk ranking pre-empts {num(imp.preempted_ha, 0)} ha of burning: ≈{num(imp.avoided_CH4_N2O_CO2e_t, 0)} t CO₂e (CH₄+N₂O), {num(imp.avoided_PM25_t, 0)} t PM2.5, ₹{num(imp.straw_value_preempted_rs_crore, 2)} crore of straw. Assumes baling prevents burning.</p></Panel>
      <Panel title={`2026 straw supply forecast (from ${date(now.latest_image)})`}><div className="table-wrap"><table><thead><tr><th>Week of</th><th>Expected harvest</th><th>Range</th><th>Baleable straw</th></tr></thead><tbody>
        {now.weekly_forecast.slice(0, 7).map(w => <tr key={w.week_start}><td>{date(w.week_start)}</td><td>{num(w.expected_harvest_ha, 0)} ha</td><td>{num(w.range_ha[0], 0)}–{num(w.range_ha[1], 0)} ha</td><td>{num(w.expected_baleable_straw_t, 0)} t</td></tr>)}
      </tbody></table></div><p className="map-caption">District crop area {num(now.crop_ha, 0)} ha · ≈{num(now.district_straw_total_t / 1e5, 1)} lakh t straw at 6.3 t/ha. Typical-pace assumption.</p></Panel>
      <Panel title="Pre-season baler pre-booking list, 2026">{watch.data ? <><div className="table-wrap"><table><thead><tr><th>Field</th><th>Area</th><th>Risk decile</th><th>Burned 2025</th><th>Neighbourhood 2025</th></tr></thead><tbody>
        {watch.data.items.map(w => <tr key={w.field_id}><td className="nowrap" title={`${w.lat}, ${w.lon}`}>{w.field_id.replace('FTW-IN-PB-', 'FTW ')}</td><td className="nowrap">{num(w.area_ha, 1)} ha</td><td>{w.risk_decile}</td><td>{w.burned_last_season ? 'Yes' : 'No'}</td><td>{pct(w.neighbourhood_burn_rate_last_season)}</td></tr>)}
      </tbody></table></div><p className="map-caption">{watch.data.notice} Top decile: {num(now.preseason_risk.top_decile_fields, 0)} fields, {num(now.preseason_risk.top_decile_ha, 0)} ha.</p></> : <EmptyState title="Watch-list unavailable" />}</Panel>
    </div>
    <div className="detail-grid">
      <Panel title="Emissions from 2025 burning (char-confirmed area)"><p>{num(c25.burned_strict_ha, 0)} ha strict burn area ≈ <strong>{num(em25.strict.CH4_N2O_CO2e_t.median, 0)} t CO₂e</strong> (CH₄ + N₂O, 90% range {num(em25.strict.CH4_N2O_CO2e_t.p05, 0)}–{num(em25.strict.CH4_N2O_CO2e_t.p95, 0)}), <strong>{num(em25.strict['PM2.5_t'].median, 0)} t PM2.5</strong>, {num(em25.strict.BC_t.median, 1)} t black carbon. Loose tier: {num(em25.loose.CH4_N2O_CO2e_t.median, 0)} t CO₂e.</p><p className="map-caption">Andreae (2019) agricultural-residue emission factors; IPCC AR6 GWP100 (CH₄ 27.0, N₂O 273); biogenic CO₂ excluded from CO₂e. Monte Carlo over straw load, dry matter and combustion factor.</p></Panel>
      <Panel title="What this evidence does not show"><ul>{r.caveats.map(x => <li key={x}>{x}</li>)}</ul></Panel>
    </div>
  </>;
}
