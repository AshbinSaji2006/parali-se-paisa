import type { ReactNode } from 'react';
import type { SystemStatus } from '../api/types';

const paths: Record<string, ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
  map: <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/></>,
  layers: <><path d="m12 2 9 5-9 5-9-5z"/><path d="m3 12 9 5 9-5M3 17l9 5 9-5"/></>,
  route: <><circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 5h8a4 4 0 0 1 0 8H9a4 4 0 0 0 0 8h8"/></>,
  shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></>,
  file: <><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h4M9 12h6M9 16h6"/></>,
  truck: <><path d="M3 6h11v11H3zM14 10h4l3 3v4h-7z"/><circle cx="7" cy="18" r="2"/><circle cx="18" cy="18" r="2"/></>,
  box: <><path d="m12 2 9 5-9 5-9-5zM3 7v10l9 5 9-5V7M12 12v10"/></>,
  sprout: <><path d="M12 22V10M12 14c-5 0-8-3-8-8 5 0 8 3 8 8ZM12 11c0-5 3-8 8-8 0 5-3 8-8 8Z"/></>,
  activity: <path d="M2 12h5l3-8 4 16 3-8h5"/>,
  panel: <><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/></>,
  menu: <path d="M3 6h18M3 12h18M3 18h18"/>,
  play: <path d="m8 5 11 7-11 7z"/>,
  expand: <path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5"/>,
  info: <><circle cx="12" cy="12" r="10"/><path d="M12 11v6M12 7h.01"/></>,
  close: <path d="M5 5l14 14M19 5 5 19"/>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
  search: <><circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/></>,
  alert: <><path d="M12 3 2 21h20z"/><path d="M12 9v5M12 18h.01"/></>,
  check: <path d="m4 12 5 5L20 6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/></>,
  chart: <><path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/></>,
};
export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.info}</svg>;
}
export function SystemModeBadge({ status }: { status?: SystemStatus }) {
  return <details className="system-mode"><summary><span className="signal-dot"/> {status?.mode || 'STATUS UNAVAILABLE'}</summary><div className="system-mode-detail"><strong>Provider readiness</strong><dl>{Object.entries(status?.providers || {}).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}<dt>Data mode</dt><dd>{status?.mode || 'Unavailable'}</dd></dl></div></details>;
}
export function PageHeader({ eyebrow, title, description, actions, children }: { eyebrow: string; title: string; description?: string; actions?: ReactNode; children?: ReactNode }) {
  return <header className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1>{description && <p>{description}</p>}{children}</div>{actions && <div className="heading-actions">{actions}</div>}</header>;
}
export function FilterBar({ children }: { children: ReactNode }) { return <div className="filter-bar">{children}</div>; }
export function SearchField({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="search-field"><Icon name="search"/><span className="sr-only">{placeholder}</span><input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}/></label>;
}
export function EmptyState({ title, detail }: { title: string; detail?: string }) { return <div className="empty-state"><span className="empty-icon"><Icon name="layers" size={24}/></span><strong>{title}</strong>{detail && <p>{detail}</p>}</div>; }
export function LoadingSkeleton({ variant = 'cards' }: { variant?: 'cards' | 'table' | 'map' }) {
  return <div className={`skeleton-layout skeleton-${variant}`} role="status" aria-label="Loading records"><span className="sr-only">Loading stored records</span>{Array.from({ length: variant === 'cards' ? 6 : 4 }, (_, i) => <div className="skeleton-card" key={i}><span/><span/><span/></div>)}</div>;
}
export function RiskBadge({ level }: { level?: string | null }) { const tone = level === 'HIGH' ? 'danger' : level === 'MEDIUM' ? 'warning' : level === 'LOW' ? 'success' : 'neutral'; return <span className={`badge ${tone}`}>{level || 'Unavailable'} risk</span>; }
export function SectionHeader({ title, aside }: { title: string; aside?: ReactNode }) { return <div className="section-header"><h2>{title}</h2>{aside}</div>; }
export function InfoGrid({ items }: { items: [string, ReactNode][] }) { return <dl className="info-grid">{items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>; }
export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) { return <aside className="detail-drawer" aria-label={title}><div className="drawer-head"><span className="eyebrow">FIELD INTELLIGENCE</span><button className="icon-button" onClick={onClose} aria-label="Close field detail"><Icon name="close"/></button></div>{children}</aside>; }
