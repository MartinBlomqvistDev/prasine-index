import { ImageResponse } from 'next/og'

export const runtime = 'edge'
export const alt = 'Prasine Index — EU Greenwashing Intelligence'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: '#0f1a10',
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '80px',
        }}
      >
        <div
          style={{
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: '0.15em',
            color: '#4ade80',
            textTransform: 'uppercase',
            marginBottom: 24,
          }}
        >
          prasineindex.com
        </div>
        <div
          style={{
            fontSize: 72,
            fontWeight: 700,
            color: '#f0fdf4',
            lineHeight: 1.1,
            marginBottom: 28,
          }}
        >
          Prasine Index
        </div>
        <div
          style={{
            fontSize: 30,
            color: '#86efac',
            lineHeight: 1.4,
            maxWidth: 700,
          }}
        >
          AI-verified analysis of EU corporate sustainability claims.
          Every assertion cited. Every data gap disclosed.
        </div>
        <div
          style={{
            marginTop: 48,
            display: 'flex',
            gap: 32,
          }}
        >
          {['EmpCo Directive', 'Green Claims Directive', 'CSRD'].map((label) => (
            <div
              key={label}
              style={{
                background: '#14532d',
                color: '#4ade80',
                fontSize: 16,
                fontWeight: 600,
                padding: '8px 20px',
                borderRadius: 6,
                letterSpacing: '0.05em',
              }}
            >
              {label}
            </div>
          ))}
        </div>
      </div>
    ),
    { ...size },
  )
}
