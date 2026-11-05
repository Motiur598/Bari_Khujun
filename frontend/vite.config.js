import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Headers for every page the app serves. frame-ancestors/X-Frame-Options stop the QR confirmation screen from being
// framed by another site (clickjacking). Production hosting must send the same headers (see README).
const baseHeaders = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  // Camera for scanning handshake QR codes, geolocation for "Use my current location" when pinning a listing.
  'Permissions-Policy': 'camera=(self), microphone=(), geolocation=(self), payment=()',
}

// The built app has no inline scripts, so `vite preview` (and production) can use a strict script policy.
// The dev server needs inline scripts for React fast refresh, so it only sets frame-ancestors.
const productionCsp = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data: blob: https:",
  // Reverse geocoding for the listing location picker (src/api/geocode.js). 'self' also covers the realtime socket
  // (ws:/wss: on this host) in current browsers.
  "connect-src 'self' https://nominatim.openstreetmap.org",
  "media-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join('; ')

// Where /api is proxied to; API_PROXY_TARGET points it at an API on another port (e.g. a second copy for testing).
const apiTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000'
// /ws carries the realtime socket (chat and notifications) to the same API.
const proxy = {
  '/api': apiTarget,
  '/ws': { target: apiTarget.replace(/^http/, 'ws'), ws: true },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy,
    headers: { ...baseHeaders, 'Content-Security-Policy': "frame-ancestors 'none'; object-src 'none'; base-uri 'self'" },
  },
  preview: {
    proxy,
    headers: { ...baseHeaders, 'Content-Security-Policy': productionCsp },
  },
})
