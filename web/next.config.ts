import path from 'node:path'
import type { NextConfig } from 'next'

// Validate env vars at build time (fails fast instead of at runtime in prod).
import { env } from './src/env'

const isDev = process.env.NODE_ENV === 'development'

// System design §7: default-src 'self'; img-src 'self' data:;
// connect-src 'self' <API>. The rest is what Next.js and the libraries need:
// - script-src 'unsafe-inline': the App Router inlines its bootstrap and
//   flight-data scripts; without a per-request nonce (which would make every
//   page dynamic) they can only run with this.
// - script-src 'unsafe-eval' (dev only): React rebuilds server error stacks
//   in the browser with eval. Production never needs it.
// - script-src 'wasm-unsafe-eval': Shiki (the SQL code block in Ask) runs
//   its Oniguruma regex engine as WebAssembly.
// - style-src 'unsafe-inline': Radix positioning, lightweight-charts and the
//   virtualized table set element styles at runtime.
// - font-src 'self': next/font self-hosts Barlow at build time.
// - connect-src ws: (dev only): the HMR socket.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'${isDev ? " 'unsafe-eval'" : ''}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self' ${new URL(env.NEXT_PUBLIC_API_URL).origin}${isDev ? ' ws:' : ''}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'"
].join('; ')

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  typedRoutes: true,
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [{ key: 'Content-Security-Policy', value: csp }]
      }
    ]
  },
  images: {
    formats: ['image/avif', 'image/webp']
  },
  turbopack: {
    // The pnpm workspace root, one level up - this is where pnpm-lock.yaml
    // and node_modules/.pnpm actually live, so `next` resolves there via a
    // symlink. Pointing turbopack at web/ itself (its old value, from before
    // this was a workspace) makes it refuse to resolve next/package.json:
    // Turbopack won't follow package resolution outside its configured root.
    root: path.join(__dirname, '..')
  }
}

export default nextConfig
