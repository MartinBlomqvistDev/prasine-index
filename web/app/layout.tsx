import type { Metadata } from 'next'
import { IBM_Plex_Mono, Source_Sans_3, Source_Serif_4 } from 'next/font/google'
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
  metadataBase: new URL('https://prasineindex.com'),
  title: 'Prasine Index | EU Greenwashing Intelligence',
  description:
    'AI-verified analysis of EU corporate sustainability claims. Every assertion cited. Every data gap disclosed.',
  openGraph: {
    title: 'Prasine Index',
    description: 'EU corporate greenwashing monitoring. Every finding cites a verifiable primary source.',
    siteName: 'Prasine Index',
    url: 'https://prasineindex.com',
    type: 'website',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  )
}
