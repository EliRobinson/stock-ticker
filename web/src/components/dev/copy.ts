// Labels on the dev-only states board (/dev/states). Frame ids match the
// Claude Design board, so "M6" means the same frame in both places.

export const boardCopy = {
  title: 'Stock Ticker',
  kicker: 'State board · dev only',
  intro:
    'Every screen and state in the design brief, rendered from fixtures in both themes. Frame ids match the Claude Design board.',
  light: 'Light',
  dark: 'Dark',
  groups: {
    G: [
      'G · Global layout',
      'Shell: sidebar, main, Ask panel. Top bar carries the breadcrumb, ⌘K and the theme menu.'
    ],
    M: [
      'M · Market',
      'The Constituent List and every state of its header strip.'
    ],
    C: [
      'C · Company',
      'Adjusted close, synced volume, and Notes and Events as markers.'
    ],
    N: [
      'N · Notes',
      'All Notes. The same dialog as the Company chart, without the pre-fill.'
    ],
    A: [
      'A · Ask',
      'The Ask panel at its docked width. Answers reuse the Market table and Company chart.'
    ],
    S: [
      'S · Shared components',
      'One definition each, used the same way on every screen.'
    ]
  } as Record<string, [string, string]>,
  frames: {
    G1: 'Market · sidebar expanded · Ask closed',
    G2: 'Sidebar collapsed to icons',
    G3: 'Ask docked beside Market',
    G4: 'Ask docked beside Notes',
    M0: 'Touch phone · list rows',
    M1: 'Loading · first paint',
    M2: 'Empty · first run, no data yet',
    M3: 'Empty · search has no matches',
    M4: 'Error · Alpaca connection down, last-known prices shown',
    M5: 'Error · missing Alpaca key',
    M6: 'Stale Quotes',
    M8: 'Market closed · last close, not an error',
    M9: 'Backfill in progress',
    M10: 'Partial data · hover a dash for the reason',
    M11: 'Narrow · 400px',
    C1: 'Company · line, Notes tab',
    C2: 'Candles, Events tab, two Listings',
    C3: 'Loading · blocks sized to the final layout',
    C4: 'Empty · no Notes, no Events',
    C5: 'Error · price history unavailable',
    C6: 'Stale Quote in the stat row',
    C7: 'Backfill in progress · presets beyond the data disabled',
    C8: 'Partial data · history starts after 2018, no filing for Market Cap',
    C9: 'Long text · truncated name, clamped Note',
    C9b: 'Note form · opened from a dragged range',
    C10: 'Narrow · 400px',
    N1: 'Default list',
    N2: 'Loading',
    N3: 'Empty · no Notes at all',
    N3b: 'Empty · no Notes for these filters',
    N4: 'Error · database unavailable, create disabled',
    N5: 'Delete with undo',
    N7: 'Narrow · 400px',
    A1: 'Empty · suggestions',
    A2: 'Streaming · query steps, partial answer',
    A3: 'Answer with a table · SQL open',
    A4: 'Answer with a chart',
    A5: 'Error · AI service unreachable',
    A5b: 'Error · missing AI key',
    A5c: 'Error · query failed',
    A5d: 'AI spend limit reached',
    A6: 'Narrow · 400px',
    S1: 'Quote cell · fresh, stale, last close',
    S2: 'Change cell · sign, arrow and color',
    S3: 'Market status pill · all four',
    S4: 'Ingest health pill · all three',
    S5: 'Marker legend',
    S6: 'Command palette · ⌘K open',
    S7: 'AI spend readout'
  } as Record<string, string>,
  quoteFresh: 'fresh · full emphasis',
  quoteStale: 'stale · emphasis dropped, age inline',
  quoteClosed: 'last close · time since close',
  staleVariant: 'stale variant'
} as const
