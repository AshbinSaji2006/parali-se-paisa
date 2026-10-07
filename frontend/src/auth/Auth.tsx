import {createContext,useContext,useEffect,useMemo,useState,type ReactNode} from 'react';
import {useNavigate,useLocation,Link,Navigate} from 'react-router-dom';
import {api,setToken} from '../api/client';
import type {User} from '../api/types';
import {Icon} from '../components/ui';

type AuthValue={user:User|null;login:(u:string,p:string)=>Promise<User>;logout:()=>void};
const Context=createContext<AuthValue|null>(null);
export function AuthProvider({children}:{children:ReactNode}){
 const [user,setUser]=useState<User|null>(null);
 const logout=()=>{setToken(null);setUser(null);};
 useEffect(()=>{const h=()=>logout();window.addEventListener('session-expired',h);return()=>window.removeEventListener('session-expired',h);},[]);
 const value=useMemo<AuthValue>(()=>({user,logout,login:async(username,password)=>{const data=await api.login(username,password);setToken(data.access_token);setUser(data.user);return data.user;}}),[user]);
 return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useAuth(){const value=useContext(Context);if(!value)throw new Error('AuthProvider is missing');return value;}
export function Login(){const {login,user}=useAuth(),navigate=useNavigate(),location=useLocation();const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 if(user)return <Navigate to={location.state?.from?.pathname||'/'} replace/>;
 return <main className="login-page"><section className="login-identity"><div className="brand"><span className="brand-mark"><Icon name="sprout"/></span><span className="brand-copy"><strong>PARALI<br/>SE PAISA</strong><small>FIELD INTELLIGENCE</small></span></div><div><span className="eyebrow">SATELLITE INTELLIGENCE · FIELD OPERATIONS</span><h1>From field evidence to coordinated straw collection.</h1><p>A single workspace for monitoring paddy fields, planning collection, and tracking no-burn evidence.</p></div><small>Research prototype · Synthetic demonstration data</small></section><div className="login-form-wrap"><form className="login-card" onSubmit={async e=>{e.preventDefault();setError('');setBusy(true);const f=new FormData(e.currentTarget);try{await login(String(f.get('username')),String(f.get('password')));navigate(location.state?.from?.pathname||'/',{replace:true});}catch(err){setError(err instanceof Error?err.message:'Sign-in failed');}finally{setBusy(false);}}}>
  <span className="badge demo">DEMO ENVIRONMENT</span><h1>Welcome back</h1><p>Sign in to the field operations workspace.</p>
  <label>Username<input name="username" autoComplete="username" required autoFocus/></label><label>Password<input type="password" name="password" autoComplete="current-password" required/></label>
  {error&&<p role="alert" className="error-text">{error}</p>}<button disabled={busy}>{busy?'Signing in…':'Sign in'} <Icon name="arrow" size={16}/></button><small>Use an account from the locally seeded demonstration. Credentials are stored in the ignored <code>.demo/credentials.json</code> file.</small>
 </form></div></main>
}
export function RequireAuth({children}:{children:ReactNode}){const {user}=useAuth(),location=useLocation();if(!user)return <div className="state"><h1>Sign in required</h1><p>Your session is stored only in this browser tab.</p><Link to="/login" state={{from:location}}>Go to sign in</Link></div>;return children;}
