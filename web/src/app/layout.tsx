import type { Metadata } from 'next'
import { Barlow, Barlow_Condensed as BarlowCondensed } from 'next/font/google'
import { ThemeProvider } from 'next-themes'
import type { ReactNode } from 'react'

import { Providers } from '@/components/providers'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'

import './globals.css'

const barlow = Barlow({
  subsets: ['latin'],
  weight: ['400', '500', '700'],
  variable: '--font-barlow',
  display: 'swap'
})

const barlowCondensed = BarlowCondensed({
  subsets: ['latin'],
  weight: ['400', '600'],
  variable: '--font-barlow-condensed',
  display: 'swap'
})

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
    <html
      lang='en'
      suppressHydrationWarning
      className={`${barlow.variable} ${barlowCondensed.variable}`}
    >
      <body className='antialiased'>
        <ThemeProvider
          attribute='class'
          defaultTheme='system'
          enableSystem
          disableTransitionOnChange
        >
          <Providers>
            <TooltipProvider delayDuration={300}>
              {children}
              <Toaster
                position='bottom-center'
                toastOptions={{
                  classNames: {
                    toast: 'rounded-none! border-border! shadow-md! font-sans!',
                    actionButton:
                      'bg-transparent! text-brand-strong! font-heading! font-semibold! text-md!'
                  }
                }}
              />
            </TooltipProvider>
          </Providers>
        </ThemeProvider>
      </body>
    </html>
  )
}
