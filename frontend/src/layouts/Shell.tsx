import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../auth/Auth';
import { Icon, SystemModeBadge } from '../components/ui';

const groups: {name: string; items: [string, string, string][]}[] = [
  { name: 'Workspace', items: [['Overview', '/', 'grid'], ['Command Map', '/map', 'map'], ['Fields', '/fields', 'layers'], ['Dispatch', '/dispatch', 'route'], ['Verification', '/verification', 'shield'], ['Certificates', '/certificates', 'file'], ['Research Evidence', '/research', 'chart']] },
  { name: 'Operations', items: [['Balers', '/balers', 'truck'], ['Buyers', '/buyers', 'box']] },
  { name: 'Portals', items: [['Farmer Portal', '/farmer', 'sprout'], ['Operator Portal', '/operator', 'truck'], ['Buyer Portal', '/buyer', 'box']] },
  { name: 'Administration', items: [['System Status', '/system', 'activity']] },
];

export function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [presentation, setPresentation] = useState(false);
  const [storyOpen, setStoryOpen] = useState(false);
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 });
  const status = useQuery({ queryKey: ['system'], queryFn: api.status });
  const admin = ['OFFICIAL', 'ADMIN'].includes(user?.role || '');
  const own = user?.role === 'FARMER' ? '/farmer' : user?.role === 'BALER_OPERATOR' ? '/operator' : user?.role === 'BUYER' ? '/buyer' : '';
  const allowed = (path: string) => admin ? !['/operator', '/buyer'].includes(path) : path === own || path === '/system' || (user?.role === 'FARMER' && path === '/fields');
  const page = groups.flatMap(g => g.items).find(([, path]) => path === location.pathname)?.[0]
    || (location.pathname.startsWith('/fields/') ? 'Field Investigation' : location.pathname.startsWith('/verification/') ? 'Verification Evidence' : location.pathname.startsWith('/certificates/') ? 'Certificate Record' : 'Workspace');
  const story = [
    ['Open Field', '/fields/SYNTHETIC-ACTION-FIELD-01'], ['Review Risk', '/fields/SYNTHETIC-ACTION-FIELD-01'],
    ['Optimise Dispatch', '/dispatch'], ['Track Collection', '/dispatch'],
    ['Review Verification', '/verification'], ['Open Certificate', '/certificates'],
  ];
  const navGroups = <nav aria-label="Primary navigation">{groups.map(group => {
    const items = group.items.filter(([, path]) => allowed(path));
    return items.length ? <div className="nav-group" key={group.name}><span className="nav-group-label">{group.name}</span>{items.map(([label, path, icon]) => <NavLink end={path === '/'} key={path} to={path} title={label} onClick={() => setMobileOpen(false)} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><Icon name={icon} /><span>{label}</span></NavLink>)}</div> : null;
  })}</nav>;
  return <div className={`app-layout ${collapsed ? 'is-collapsed' : ''} ${presentation ? 'presentation-mode' : ''}`}>
    {mobileOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
    <aside className={`sidebar ${mobileOpen ? 'mobile-open' : ''}`}>
      <div className="sidebar-head"><NavLink className="brand" to="/" onClick={() => setMobileOpen(false)} aria-label="Parali Se Paisa home"><span className="brand-mark"><Icon name="sprout" /></span><span className="brand-copy"><strong>PARALI<br />SE PAISA</strong><small>FIELD INTELLIGENCE</small></span></NavLink><button className="sidebar-toggle" onClick={() => setCollapsed(v => !v)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}><Icon name="panel" /></button></div>
      <div className="sidebar-mode"><span className="signal-dot" />{status.data?.mode || 'DEMO / SYNTHETIC'}</div>
      {navGroups}
      <div className="sidebar-bottom"><div className="sidebar-account"><span className="avatar">{user?.username?.slice(0, 2).toUpperCase()}</span><span><strong>{user?.username}</strong><small>{user?.role?.replaceAll('_', ' ')}</small></span></div><div className="sidebar-health"><span className={`health-dot ${health.data?.status === 'ok' ? 'ok' : ''}`} />API {health.data?.status || 'Checking'} <span>·</span> {status.data?.mode || 'Demo'}</div><button className="sidebar-signout" onClick={() => { logout(); navigate('/login', { replace: true }); }}>Sign out</button></div>
    </aside>
    <div className="content"><header className="topbar"><div className="topbar-left"><button className="mobile-menu" aria-label="Menu" aria-expanded={mobileOpen} onClick={() => setMobileOpen(v => !v)}><Icon name="menu" /></button><span className="topbar-context">{page}</span></div><div className="topbar-actions"><SystemModeBadge status={status.data} /><span className="health-indicator" title={`API ${health.data?.status || 'Checking'}`}><span className={`health-dot ${health.data?.status === 'ok' ? 'ok' : ''}`} />{health.data?.status === 'ok' ? 'API online' : 'API checking'}</span>{admin && status.data?.mode === 'DEMO / SYNTHETIC' && <button className="topbar-tool" onClick={() => setStoryOpen(v => !v)} aria-expanded={storyOpen}><Icon name="play" /><span>Demo story</span></button>}<button className="topbar-tool" onClick={() => setPresentation(v => !v)} aria-pressed={presentation}><Icon name="expand" /><span>{presentation ? 'Exit presentation' : 'Present'}</span></button><span className="topbar-avatar" title={`${user?.username} · ${user?.role}`}>{user?.username?.slice(0, 2).toUpperCase()}</span><button className="signout-button" onClick={() => { logout(); navigate('/login', { replace: true }); }}>Sign out</button></div></header>
      <div className="mode-banner"><Icon name="info" /><span><strong>{status.data?.mode || 'DATA MODE'}</strong> {status.data?.notice || 'Checking data source status.'}</span></div>
      {storyOpen && <div className="story-popover"><div className="story-popover-head"><strong>Demo story</strong><button className="icon-button" aria-label="Close demo story" onClick={() => setStoryOpen(false)}><Icon name="close" /></button></div><p>Follow the recorded workflow across existing pages.</p><ol>{story.map(([label, path], index) => <li key={index}><NavLink to={path} onClick={() => setStoryOpen(false)}><span>{index + 1}</span>{label}<Icon name="arrow" /></NavLink></li>)}</ol></div>}
      <main className="page-content"><Outlet /></main><footer>PARALI SE PAISA · Research prototype · No government determination or payment approval</footer>
    </div>
  </div>;
}
