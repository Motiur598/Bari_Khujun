import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
// Leaflet's stylesheet is small, so it loads with the app; Leaflet itself only loads with the map pages.
import 'leaflet/dist/leaflet.css'
import App from './App.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import { CompareProvider } from './context/CompareContext.jsx'
import { RealtimeProvider } from './context/RealtimeContext.jsx'
import './index.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <RealtimeProvider>
          <CompareProvider>
            <App />
          </CompareProvider>
        </RealtimeProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
