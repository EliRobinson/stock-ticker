import { NextResponse, type NextRequest } from 'next/server'

// Only active while sharing: scripts/share.sh sets SHARE_PASSWORD. Local use stays open.
export function proxy(request: NextRequest) {
  const password = process.env.SHARE_PASSWORD
  if (!password) return NextResponse.next()

  const header = request.headers.get('authorization') ?? ''
  const [scheme, encoded] = header.split(' ')
  if (scheme === 'Basic' && encoded) {
    const supplied = atob(encoded).split(':').slice(1).join(':')
    if (supplied === password) return NextResponse.next()
  }

  return new NextResponse('Password required.', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="Stock Ticker"' }
  })
}

export const config = {
  matcher: '/((?!_next/static|_next/image|favicon.ico).*)'
}
