'use client'

import { Contrast, Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'

import { shellCopy as copy } from './copy'

export function ThemeMenu({ className }: { className?: string }) {
  const { theme = 'system', setTheme } = useTheme()
  const Icon = theme === 'dark' ? Moon : theme === 'light' ? Sun : Contrast
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant='outline'
          size='icon'
          aria-label={copy.theme(theme)}
          className={className}
        >
          <Icon aria-hidden='true' strokeWidth={1.5} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end' className='w-36'>
        <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
          <DropdownMenuRadioItem value='system'>
            <Contrast aria-hidden='true' strokeWidth={1.5} />
            {copy.themes.system}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value='light'>
            <Sun aria-hidden='true' strokeWidth={1.5} />
            {copy.themes.light}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value='dark'>
            <Moon aria-hidden='true' strokeWidth={1.5} />
            {copy.themes.dark}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
