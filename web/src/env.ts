import { createEnv } from '@t3-oss/env-nextjs'
import { z } from 'zod'

/**
 * Type-safe, validated environment variables.
 * Import `env` instead of using `process.env` directly so missing/invalid
 * vars fail fast at build/boot time rather than deep in a request handler.
 *
 * This app never talks to a database directly. It calls the Python API,
 * which the browser reaches at NEXT_PUBLIC_API_URL directly (no Next.js
 * rewrite: a rewrite would buffer the /chat SSE stream).
 */
export const env = createEnv({
  server: {
    NODE_ENV: z
      .enum(['development', 'test', 'production'])
      .default('development')
  },
  client: {
    NEXT_PUBLIC_API_URL: z.string().url().default('http://127.0.0.1:8000')
  },
  experimental__runtimeEnv: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL
  },
  skipValidation: !!process.env.SKIP_ENV_VALIDATION
})
