import client from './client'

/**
 * Fetch a file through the authenticated API client and trigger a browser download.
 */
export async function downloadFile(url: string, filename: string): Promise<void> {
  const response = await client.get(url, { responseType: 'blob' })
  const blobUrl = URL.createObjectURL(response.data)
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(blobUrl)
}
