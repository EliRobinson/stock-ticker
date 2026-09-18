import path from 'node:path'
import type { NextConfig } from 'next'

// Validate env vars at build time (fails fast instead of at runtime in prod).
import './src/env'

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  typedRoutes: true,
  images: {
    formats: ['image/avif', 'image/webp']
  },
  turbopack: {
    // The pnpm workspace root, one level up — this is where pnpm-lock.yaml
    // and node_modules/.pnpm actually live, so `next` resolves there via a
    // symlink. Pointing turbopack at web/ itself (its old value, from before
    // this was a workspace) makes it refuse to resolve next/package.json:
    // Turbopack won't follow package resolution outside its configured root.
    root: path.join(__dirname, '..')
  }
}

export default nextConfig
