'use client'

import type { ComponentProps } from 'react'
import { defaultRehypePlugins, Streamdown } from 'streamdown'
import type { Components } from 'streamdown'

type StreamdownProps = ComponentProps<typeof Streamdown>
type Pluggable = NonNullable<StreamdownProps['rehypePlugins']>[number]

// Streamdown's defaults include rehype-raw, which turns HTML in the Markdown
// into real elements. Notes and AI answers are untrusted text (system design
// §7: raw HTML off, remote images off, https links only), so only the
// sanitizer runs: with raw gone, HTML stays inert text. Link and image
// policy is enforced by the components below, not by rehype-harden, which
// needs a fake origin to restrict prefixes.
export const safeRehypePlugins: Pluggable[] = [defaultRehypePlugins.sanitize!]

export function isSafeHref(href: unknown): href is string {
  if (typeof href !== 'string') return false
  try {
    return new URL(href).protocol === 'https:'
  } catch {
    return false
  }
}

const SafeLink: NonNullable<Components['a']> = ({
  href,
  children,
  node: _node,
  ...rest
}) => {
  if (!isSafeHref(href)) return <span>{children}</span>
  return (
    <a
      {...rest}
      href={href}
      target='_blank'
      rel='noopener noreferrer'
      className='text-brand-strong underline-offset-3 underline'
    >
      {children}
    </a>
  )
}

export const safeComponents: Components = {
  a: SafeLink,
  img: () => null
}

export const safeMarkdownProps = {
  rehypePlugins: safeRehypePlugins,
  components: safeComponents,
  urlTransform: (url: string) => (isSafeHref(url) ? url : ''),
  linkSafety: { enabled: false }
} satisfies Partial<StreamdownProps>

export function SafeMarkdown({
  children,
  className
}: {
  children: string
  className?: string
}) {
  return (
    <Streamdown {...safeMarkdownProps} controls={false} className={className}>
      {children}
    </Streamdown>
  )
}
