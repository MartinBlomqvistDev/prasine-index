import { ImageResponse } from 'next/og'

export const runtime = 'edge'
export const alt = 'Prasine Index · EU corporate greenwashing monitor'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: '#f6f5f0',
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '64px 80px',
          border: '14px solid #163820',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            fontSize: 20,
            fontWeight: 700,
            letterSpacing: '0.14em',
            color: '#1a4024',
            marginBottom: 20,
          }}
        >
          <div style={{ width: 36, height: 3, background: '#1a4024', display: 'flex' }} />
          PRASINE INDEX · EU GREENWASHING MONITOR
        </div>

        <div
          style={{
            fontSize: 64,
            fontWeight: 700,
            color: '#1a160d',
            lineHeight: 1.08,
            letterSpacing: '-0.02em',
            marginBottom: 40,
            display: 'flex',
          }}
        >
          Climate claims, checked against public records.
        </div>

        <div
          style={{
            fontSize: 22,
            color: '#6b5f4e',
            display: 'flex',
          }}
        >
          prasineindex.com
        </div>
      </div>
    ),
    { ...size },
  )
}
