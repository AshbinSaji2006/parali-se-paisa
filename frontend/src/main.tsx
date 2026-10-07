import React from 'react';
import ReactDOM from 'react-dom/client';
import {BrowserRouter,Navigate,Route,Routes} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import 'leaflet/dist/leaflet.css';
import './styles.css';
import {AuthProvider,Login,RequireAuth} from './auth/Auth';
import {Shell} from './layouts/Shell';
import {Overview,CommandMap,Fields,FieldDetail} from './pages/advanced';
import {Dispatch,Verification,VerificationDetail,Certificates,CertificateDetail,PublicVerify} from './pages/workflows';
import {Farmer,Operator,BuyerView,System,ResourceTable} from './pages/portals';
import {Research} from './pages/research';

const client=new QueryClient({defaultOptions:{queries:{retry:1,refetchOnWindowFocus:false}}});
function App(){return <QueryClientProvider client={client}><AuthProvider><BrowserRouter><Routes>
 <Route path="/login" element={<Login/>}/><Route path="/verify/:certificateId" element={<PublicVerify/>}/>
 <Route element={<RequireAuth><Shell/></RequireAuth>}>
  <Route index element={<Overview/>}/><Route path="map" element={<CommandMap/>}/><Route path="fields" element={<Fields/>}/><Route path="fields/:fieldId" element={<FieldDetail/>}/>
  <Route path="dispatch" element={<Dispatch/>}/><Route path="balers" element={<ResourceTable kind="baler"/>}/><Route path="buyers" element={<ResourceTable kind="buyer"/>}/>
  <Route path="verification" element={<Verification/>}/><Route path="verification/:fieldId" element={<VerificationDetail/>}/>
  <Route path="certificates" element={<Certificates/>}/><Route path="certificates/:certificateId" element={<CertificateDetail/>}/>
  <Route path="farmer" element={<Farmer/>}/><Route path="operator" element={<Operator/>}/><Route path="buyer" element={<BuyerView/>}/><Route path="system" element={<System/>}/><Route path="research" element={<Research/>}/>
  <Route path="*" element={<Navigate to="/" replace/>}/>
 </Route></Routes></BrowserRouter></AuthProvider></QueryClientProvider>}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
