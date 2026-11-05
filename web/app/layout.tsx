import { Analytics } from '@vercel/analytics/next'
import type { Metadata } from 'next'
import { IBM_Plex_Mono, Source_Sans_3, Source_Serif_4 } from 'next/font/google'
import { SITE_URL } from '../lib/site'
import './globals.css'

const serif = Source_Serif_4({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-serif',
  display: 'swap',
  axes: ['opsz'],
})

const sans = Source_Sans_3({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-sans',
  display: 'swap',
})

const mono = IBM_Plex_Mono({
  subsets: ['latin', 'latin-ext'],
  weight: ['400', '600'],
  variable: '--font-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: 'Prasine Index | EU Greenwashing Intelligence',
  description:
    'Open-data checks of EU corporate sustainability claims.',
  openGraph: {
    title: 'Prasine Index',
    description: 'EU corporate greenwashing monitoring.',
    siteName: 'Prasine Index',
    url: SITE_URL,
    type: 'website',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <body>
        {children}
        <Analytics />
      </body>
    </html>
  )
}
