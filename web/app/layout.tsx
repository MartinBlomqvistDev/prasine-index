import type { Metadata } from 'next'
import { Fraunces, Outfit } from 'next/font/google'
import './globals.css'

const fraunces = Fraunces({
  subsets: ['latin'],
  variable: '--font-fraunces',
  display: 'swap',
  axes: ['opsz'],
})

const outfit = Outfit({
  subsets: ['latin'],
  variable: '--font-outfit',
  display: 'swap',
})

export const metadata: Metadata = {
  metadataBase: new URL('https://prasineindex.com'),
  title: 'Prasine Index — EU Greenwashing Intelligence',
  description:
    'AI-verified analysis of EU corporate sustainability claims. Every assertion cited. Every data gap disclosed.',
  openGraph: {
    title: 'Prasine Index',
    description: 'EU corporate greenwashing monitoring — every finding cites a verifiable primary source.',
    siteName: 'Prasine Index',
    url: 'https://prasineindex.com',
    type: 'website',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${fraunces.variable} ${outfit.variable}`}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Space+Mono&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  )
}
