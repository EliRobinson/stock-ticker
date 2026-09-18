'use client'

import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

// Contains a render failure to one region (one chart or table in an Ask
// answer), so a bad payload never takes the rest of the screen with it.
export class RegionBoundary extends Component<
  { fallback: ReactNode; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Region failed to render', error, info.componentStack)
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}
