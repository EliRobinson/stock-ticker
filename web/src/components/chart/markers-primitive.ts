import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time
} from 'lightweight-charts'

import type { PlacedMarker } from '@/lib/chart-data'

import type { ChartColors } from './chart-theme'

type Target = Parameters<IPrimitivePaneRenderer['draw']>[0]

interface State {
  markers: PlacedMarker[]
  values: Map<string, number>
  highlightedId: string | null
  selection: { from: number; to: number } | null
  colors: ChartColors
}

// Built-in series markers have no outlined diamond, and the design keeps
// Notes (filled circle) and Events (outlined diamond) visually distinct, so the
// markers, Note range shading and the drag selection are drawn here.
export class MarkersPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null
  private series: ISeriesApi<SeriesType> | null = null
  private requestUpdate: (() => void) | null = null
  private views: readonly IPrimitivePaneView[]

  constructor(private state: State) {
    const bg: IPrimitivePaneView = {
      zOrder: () => 'bottom',
      renderer: () => ({ draw: (t) => this.drawBackground(t) })
    }
    const fg: IPrimitivePaneView = {
      zOrder: () => 'top',
      renderer: () => ({ draw: (t) => this.drawMarkers(t) })
    }
    this.views = [bg, fg]
  }

  attached(param: SeriesAttachedParameter<Time>) {
    this.chart = param.chart as IChartApi
    this.series = param.series
    this.requestUpdate = param.requestUpdate
  }

  detached() {
    this.chart = null
    this.series = null
    this.requestUpdate = null
  }

  paneViews() {
    return this.views
  }

  update(next: Partial<State>) {
    this.state = { ...this.state, ...next }
    this.requestUpdate?.()
  }

  private x(date: string) {
    return this.chart?.timeScale().timeToCoordinate(date as Time) ?? null
  }

  private drawBackground(target: Target) {
    const { markers, selection, colors } = this.state
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.fillStyle = colors.range
      for (const m of markers) {
        if (m.kind !== 'note' || m.start === m.end) continue
        const x1 = this.x(m.start)
        const x2 = this.x(m.end)
        if (x1 == null || x2 == null) continue
        context.fillRect(
          Math.min(x1, x2),
          0,
          Math.abs(x2 - x1),
          mediaSize.height
        )
      }
      if (selection) {
        context.fillStyle = colors.range
        context.fillRect(
          Math.min(selection.from, selection.to),
          0,
          Math.abs(selection.to - selection.from),
          mediaSize.height
        )
        context.strokeStyle = colors.ring
        context.lineWidth = 1
        context.strokeRect(
          Math.min(selection.from, selection.to) + 0.5,
          0.5,
          Math.abs(selection.to - selection.from),
          mediaSize.height - 1
        )
      }
    })
  }

  private drawMarkers(target: Target) {
    const { markers, values, highlightedId, colors } = this.state
    const series = this.series
    if (!series) return
    target.useMediaCoordinateSpace(({ context }) => {
      for (const m of markers) {
        const x = this.x(m.barDate)
        const value = values.get(m.barDate)
        if (x == null || value == null) continue
        const y = series.priceToCoordinate(value)
        if (y == null) continue
        if (m.id === highlightedId) {
          context.beginPath()
          context.strokeStyle = colors.ring
          context.lineWidth = 2
          context.arc(x, y, 9, 0, Math.PI * 2)
          context.stroke()
        }
        context.beginPath()
        if (m.kind === 'note') {
          context.fillStyle = colors.note
          context.arc(x, y, 4.5, 0, Math.PI * 2)
          context.fill()
        } else {
          context.strokeStyle = colors.event
          context.lineWidth = 1.5
          context.moveTo(x, y - 5.5)
          context.lineTo(x + 5.5, y)
          context.lineTo(x, y + 5.5)
          context.lineTo(x - 5.5, y)
          context.closePath()
          context.stroke()
        }
      }
    })
  }
}
