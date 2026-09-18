import type { ReactNode } from 'react'

import { ShellContainer } from '@/components/containers/shell-container'

export default function AppLayout({ children }: { children: ReactNode }) {
  return <ShellContainer>{children}</ShellContainer>
}
