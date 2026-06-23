import { apiClient } from './client'
import type { DocumentOut, IngestJobOut } from '@/types/api'

export async function uploadDocument(
  file: File,
  onProgress?: (pct: number) => void
): Promise<DocumentOut> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post<DocumentOut>('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: e => {
      if (e.total && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    },
  })
  return data
}

export async function listDocuments(): Promise<DocumentOut[]> {
  const { data } = await apiClient.get<DocumentOut[]>('/documents')
  return data
}

export async function getDocument(id: number): Promise<DocumentOut> {
  const { data } = await apiClient.get<DocumentOut>(`/documents/${id}`)
  return data
}

export async function deleteDocument(id: number): Promise<void> {
  await apiClient.delete(`/documents/${id}`)
}

export async function retryDocument(id: number): Promise<IngestJobOut> {
  const { data } = await apiClient.post<IngestJobOut>(`/documents/${id}/retry`)
  return data
}

export async function reindexDocument(id: number): Promise<IngestJobOut> {
  const { data } = await apiClient.post<IngestJobOut>(`/documents/${id}/reindex`)
  return data
}

export async function cancelDocument(id: number): Promise<IngestJobOut> {
  const { data } = await apiClient.post<IngestJobOut>(`/documents/${id}/cancel`)
  return data
}
