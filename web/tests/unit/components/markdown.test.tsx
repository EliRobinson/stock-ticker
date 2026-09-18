import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { SafeMarkdown } from '@/components/shared/markdown'

describe('SafeMarkdown', () => {
  afterEach(cleanup)

  it('renders raw HTML as inert text, never as elements', () => {
    const { container } = render(
      <SafeMarkdown>
        {
          'Hello <b>bold</b> <div id="x">block</div> <script>alert(1)</script> **real**'
        }
      </SafeMarkdown>
    )
    expect(container.querySelector('b')).toBeNull()
    expect(container.querySelector('#x')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container).toHaveTextContent('<b>bold</b>')
    expect(
      container.querySelector('[data-streamdown="strong"]')
    ).toHaveTextContent('real')
  })

  it('renders https links as real anchors that open safely', () => {
    render(<SafeMarkdown>{'[docs](https://example.com/a)'}</SafeMarkdown>)
    const link = screen.getByRole('link', { name: 'docs' })
    expect(link).toHaveAttribute('href', 'https://example.com/a')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('drops non-https links and all images', () => {
    const { container } = render(
      <SafeMarkdown>
        {
          '[a](http://example.com) [b](javascript:alert(1)) ![c](https://example.com/c.png)'
        }
      </SafeMarkdown>
    )
    expect(screen.queryByRole('link')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container).toHaveTextContent('a b')
  })
})
