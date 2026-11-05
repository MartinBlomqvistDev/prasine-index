import type { MetadataRoute } from 'next'
import { PUBLISHED_SLUGS, SITE_URL, WITHDRAWN } from '../lib/site'

export default function sitemap(): MetadataRoute.Sitemap {
  const pages = ['', '/methodology', '/about'].map(path => ({ url: `${SITE_URL}${path}` }))
  // Withdrawn report URLs are listed so that search engines replace the old
  // content with the withdrawal notice.
  const reports = [...PUBLISHED_SLUGS, ...Object.keys(WITHDRAWN)].map(slug => ({
    url: `${SITE_URL}/reports/${slug}`,
  }))
  return [...pages, ...reports]
}
