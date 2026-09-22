import {
  QueryClient,
  QueryClientProvider,
  useQuery
} from '@tanstack/react-query'
import { act } from 'react'
import { hydrateRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { renderToString } from 'react-dom/server'
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi
} from 'vitest'

import { AfterHydration } from '@/components/shared/after-hydration'

const KEY = ['listings']

function Listings() {
  const { data } = useQuery({
    queryKey: KEY,
    queryFn: () => Promise.resolve(['AAPL']),
    staleTime: Infinity
  })
  return <p>{data ? `${data.length} Listings` : 'Loading Listings…'}</p>
}

function App({ client, guarded }: { client: QueryClient; guarded: boolean }) {
  return (
    <QueryClientProvider client={client}>
      {guarded ? (
        <AfterHydration fallback={<p>Skeleton</p>}>
          <Listings />
        </AfterHydration>
      ) : (
        <Listings />
      )}
    </QueryClientProvider>
  )
}

const roots: Root[] = []

async function hydrateWithWarmCache(guarded: boolean) {
  const container = document.createElement('div')
  container.innerHTML = renderToString(
    <App client={new QueryClient()} guarded={guarded} />
  )
  document.body.appendChild(container)
  const warm = new QueryClient()
  warm.setQueryData(KEY, ['AAPL'])
  const onRecoverableError = vi.fn()
  await act(async () => {
    roots.push(
      hydrateRoot(container, <App client={warm} guarded={guarded} />, {
        onRecoverableError
      })
    )
  })
  return { container, onRecoverableError }
}

describe('AfterHydration', () => {
  beforeAll(() => vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true))
  afterAll(() => vi.unstubAllGlobals())
  afterEach(() => {
    act(() => roots.splice(0).forEach((root) => root.unmount()))
    document.body.innerHTML = ''
  })

  it('renders the fallback on the server', () => {
    const html = renderToString(<App client={new QueryClient()} guarded />)
    expect(html).toContain('Skeleton')
    expect(html).not.toContain('Loading Listings')
  })

  it('hydrates without a mismatch when the cache is already warm', async () => {
    const { container, onRecoverableError } = await hydrateWithWarmCache(true)
    expect(onRecoverableError).not.toHaveBeenCalled()
    expect(container.textContent).toBe('1 Listings')
  })

  it('mismatches without the guard', async () => {
    const { onRecoverableError } = await hydrateWithWarmCache(false)
    expect(onRecoverableError).toHaveBeenCalled()
  })
})
