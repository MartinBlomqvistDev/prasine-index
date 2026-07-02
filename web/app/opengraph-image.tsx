import { ImageResponse } from 'next/og'

export const runtime = 'edge'
export const alt = 'Prasine Index — EU corporate greenwashing monitor. Ryanair 86/100, Glencore 86/100, BP 81/100.'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

const VERDICTS = [
  { company: 'Ryanair', score: 86, label: 'CONFIRMED GREENWASHING', color: '#8b1c1c' },
  { company: 'Glencore', score: 86, label: 'CONFIRMED GREENWASHING', color: '#8b1c1c' },
  { company: 'BP', score: 81, label: 'CONFIRMED GREENWASHING', color: '#8b1c1c' },
]

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: '#f5f0e6',
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
          Every green claim. Verified against reality.
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {VERDICTS.map((v) => (
            <div key={v.company} style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
              <div
                style={{
                  width: 190,
                  fontSize: 30,
                  fontWeight: 700,
                  color: '#1a160d',
                  display: 'flex',
                }}
              >
                {v.company}
              </div>
              <div
                style={{
                  flex: 1,
                  height: 14,
                  background: '#d0c8b8',
                  display: 'flex',
                }}
              >
                <div
                  style={{
                    width: `${v.score}%`,
                    height: '100%',
                    background: v.color,
                    display: 'flex',
                  }}
                />
              </div>
              <div
                style={{
                  width: 130,
                  fontSize: 30,
                  fontWeight: 700,
                  color: v.color,
                  display: 'flex',
                  justifyContent: 'flex-end',
                }}
              >
                {v.score}/100
              </div>
              <div
                style={{
                  width: 330,
                  fontSize: 17,
                  fontWeight: 700,
                  letterSpacing: '0.06em',
                  color: v.color,
                  display: 'flex',
                }}
              >
                {v.label}
              </div>
            </div>
          ))}
        </div>

        <div
          style={{
            marginTop: 44,
            fontSize: 22,
            color: '#6b5f4e',
            display: 'flex',
          }}
        >
          22 EU data sources · every finding cites a verifiable primary source · prasineindex.com
        </div>
      </div>
    ),
    { ...size },
  )
}
