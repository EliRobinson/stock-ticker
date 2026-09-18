import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { Providers } from '@/components/providers'
import './globals.css'

export const metadata: Metadata = {
  title: {
    template: '%s | Stock Ticker',
    default: 'Stock Ticker'
  },
  description: 'S&P 500 research app.'
}

export default function RootLayout({
  children
}: Readonly<{
  children: ReactNode
}>) {
  return (
    <html lang='en'>
      <body className='antialiased'>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
