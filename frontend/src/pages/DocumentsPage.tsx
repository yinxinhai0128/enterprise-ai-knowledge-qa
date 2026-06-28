import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, FileText, FileSpreadsheet, File, Trash2, RefreshCw, RotateCcw, X, FolderOpen, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { NavBar } from '@/components/NavBar'
import { listDocuments, uploadDocument, deleteDocument, retryDocument, reindexDocument, cancelDocument } from '@/api/documents'
import type { DocumentOut } from '@/types/api'
import { toast } from '@/hooks/use-toast'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const ALLOWED_TYPES = ['.pdf', '.docx', '.xlsx', '.txt', '.md']
const MAX_SIZE_MB = 50

function fileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase()
  if (ext === 'pdf') return <FileText className="w-4 h-4 text-red-500" />
  if (ext === 'docx' || ext === 'doc') return <FileText className="w-4 h-4 text-blue-500" />
  if (ext === 'xlsx' || ext === 'xls') return <FileSpreadsheet className="w-4 h-4 text-green-600" />
  return <File className="w-4 h-4 text-gray-400" />
}

function StatusBadge({ status, errorMsg }: { status: DocumentOut['status']; errorMsg?: string | null }) {
  if (status === 'indexed') return <Badge variant="success">已索引</Badge>
  if (status === 'failed') {
    return (
      <span title={errorMsg ?? undefined}>
        <Badge variant="destructive" className="cursor-help">失败 ⓘ</Badge>
      </span>
    )
  }
  return (
    <Badge variant="info" className="flex items-center gap-1">
      <Loader2 className="w-3 h-3 animate-spin" />
      处理中
    </Badge>
  )
}

function UploadZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function validate(file: File): string | null {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!ALLOWED_TYPES.includes(ext)) return `不支持的格式：${ext}`
    if (file.size > MAX_SIZE_MB * 1024 * 1024) return `文件过大，最大 ${MAX_SIZE_MB}MB`
    return null
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const files = Array.from(e.dataTransfer.files)
    const valid = files.filter(f => {
      const err = validate(f)
      if (err) { toast({ variant: 'destructive', title: '文件不符合要求', description: err }); return false }
      return true
    })
    if (valid.length) onFiles(valid)
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    const valid = files.filter(f => {
      const err = validate(f)
      if (err) { toast({ variant: 'destructive', title: '文件不符合要求', description: err }); return false }
      return true
    })
    if (valid.length) onFiles(valid)
    e.target.value = ''
  }

  return (
    <div
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={`border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer transition-all ${
        dragging
          ? 'border-blue-400 bg-[#EEF2FF]'
          : 'border-gray-200 hover:border-blue-300 hover:bg-gray-50/80'
      }`}
    >
      <input ref={inputRef} type="file" multiple accept={ALLOWED_TYPES.join(',')} onChange={handleChange} className="hidden" />
      <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-sm"
        style={{ background: dragging ? 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' : 'linear-gradient(135deg, #EEF2FF 0%, #C7D2FE 100%)' }}>
        <Upload className={`w-6 h-6 ${dragging ? 'text-white' : 'text-[#3B4FCC]'}`} />
      </div>
      <p className="text-sm text-gray-600 font-medium">
        拖拽文件到此处，或{' '}
        <span className="underline" style={{ color: '#3B4FCC' }}>点击选择文件</span>
      </p>
      <p className="text-xs text-gray-400 mt-2">支持 PDF · DOCX · XLSX · TXT · MD，单文件最大 {MAX_SIZE_MB} MB</p>
    </div>
  )
}

export default function DocumentsPage() {
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadingFile, setUploadingFile] = useState('')
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const queryClient = useQueryClient()

  const hasProcessing = (docs: DocumentOut[]) =>
    docs.some(d => d.status === 'uploading' || d.status === 'parsing')

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: listDocuments,
    refetchInterval: (query) => {
      const data = query.state.data ?? []
      return hasProcessing(data) ? 3000 : false
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      toast({ variant: 'success', title: '文档已删除' })
    },
  })

  const retryMutation = useMutation({
    mutationFn: retryDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      toast({ title: '已重新提交处理' })
    },
  })

  const reindexMutation = useMutation({
    mutationFn: reindexDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      toast({ title: '已触发重新索引' })
    },
  })

  const cancelMutation = useMutation({
    mutationFn: cancelDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      toast({ title: '已取消处理' })
    },
  })

  const handleFiles = useCallback(async (files: File[]) => {
    for (const file of files) {
      setUploadingFile(file.name)
      setUploadProgress(0)
      setUploading(true)
      try {
        await uploadDocument(file, setUploadProgress)
        queryClient.invalidateQueries({ queryKey: ['documents'] })
        toast({ variant: 'success', title: '上传成功', description: `${file.name} 正在处理中…` })
      } catch {
        // error toast handled by interceptor
      }
    }
    setUploading(false)
    setUploadOpen(false)
  }, [queryClient])

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <NavBar />
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="h-14 flex items-center justify-between px-6 border-b border-gray-100 bg-white shadow-sm">
          <div className="flex items-center gap-3">
            <span className="font-medium text-gray-700 text-sm">知识库文档</span>
            <Badge variant="secondary">{docs.length} 个</Badge>
          </div>
          <Button
            onClick={() => setUploadOpen(true)}
            className="text-white text-sm"
            style={{ background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }}
          >
            <Upload className="w-4 h-4" /> 上传文档
          </Button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 scrollbar-thin">
          {isLoading ? (
            <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
              {[0, 1, 2].map(i => (
                <div key={i} className="flex items-center gap-4 px-4 py-3 border-b border-gray-50">
                  <Skeleton className="w-4 h-4 rounded" />
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-6 w-16 rounded-full ml-auto" />
                  <Skeleton className="h-4 w-20" />
                  <Skeleton className="h-8 w-20 rounded-md" />
                </div>
              ))}
            </div>
          ) : docs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center py-20">
              <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-5 shadow-sm"
                style={{ background: 'linear-gradient(135deg, #EEF2FF 0%, #C7D2FE 100%)' }}>
                <FolderOpen className="w-8 h-8" style={{ color: '#3B4FCC' }} />
              </div>
              <h3 className="text-base font-semibold text-gray-700 mb-2">知识库暂无文档</h3>
              <p className="text-sm text-gray-400 mb-6">支持 PDF · DOCX · XLSX · TXT · MD，上传后自动索引</p>
              <Button
                onClick={() => setUploadOpen(true)}
                className="text-white"
                style={{ background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }}
              >
                <Upload className="w-4 h-4" /> 上传文档
              </Button>
            </div>
          ) : (
            <>
              {/* Desktop table */}
              <div className="hidden md:block bg-white rounded-xl border border-gray-100 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50">
                      <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">文件名</th>
                      <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">状态</th>
                      <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">分块数</th>
                      <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">上传时间</th>
                      <th className="text-right px-4 py-3 text-xs font-medium text-gray-500">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {docs.map(doc => (
                      <tr key={doc.id} className={`transition-colors ${
                        doc.status === 'uploading' || doc.status === 'parsing' ? 'bg-blue-50/50'
                        : doc.status === 'failed' ? 'bg-red-50/50' : 'hover:bg-gray-50'
                      }`}>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            {fileIcon(doc.filename)}
                            <span className="font-medium text-gray-800 max-w-xs truncate" title={doc.filename}>{doc.filename}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3"><StatusBadge status={doc.status} errorMsg={doc.error_msg} /></td>
                        <td className="px-4 py-3 text-gray-500">{doc.status === 'failed' ? '—' : doc.chunk_count || '—'}</td>
                        <td className="px-4 py-3 text-gray-400 text-xs">{dayjs(doc.created_at).fromNow()}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            {doc.status === 'indexed' && (
                              <Button variant="outline" size="sm" className="h-8 px-2" onClick={() => reindexMutation.mutate(doc.id)}>
                                <RotateCcw className="w-3.5 h-3.5" />
                              </Button>
                            )}
                            {doc.status === 'failed' && (
                              <Button size="sm" className="h-8 px-3" style={{ backgroundColor: '#3B4FCC' }} onClick={() => retryMutation.mutate(doc.id)}>
                                <RefreshCw className="w-3.5 h-3.5" /> 重试
                              </Button>
                            )}
                            {(doc.status === 'uploading' || doc.status === 'parsing') && (
                              <Button variant="outline" size="sm" className="h-8 px-2" onClick={() => cancelMutation.mutate(doc.id)}>
                                <X className="w-3.5 h-3.5" />
                              </Button>
                            )}
                            <Button variant="ghost" size="sm" className="h-8 px-2 text-red-400 hover:text-red-600 hover:bg-red-50" onClick={() => setDeleteId(doc.id)}>
                              <Trash2 className="w-3.5 h-3.5" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile card list */}
              <div className="md:hidden space-y-3 pb-20">
                {docs.map(doc => (
                  <div key={doc.id} className={`bg-white rounded-xl border p-4 ${
                    doc.status === 'uploading' || doc.status === 'parsing' ? 'border-blue-200 bg-blue-50/30'
                    : doc.status === 'failed' ? 'border-red-200 bg-red-50/30' : 'border-gray-100'
                  }`}>
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div className="flex items-center gap-2 min-w-0">
                        {fileIcon(doc.filename)}
                        <span className="text-sm font-medium text-gray-800 truncate">{doc.filename}</span>
                      </div>
                      <StatusBadge status={doc.status} errorMsg={doc.error_msg} />
                    </div>
                    <div className="flex items-center justify-between text-xs text-gray-400">
                      <span>{doc.status === 'failed' ? '处理失败' : `${doc.chunk_count || 0} 个分块`}</span>
                      <span>{dayjs(doc.created_at).fromNow()}</span>
                    </div>
                    <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-100">
                      {doc.status === 'indexed' && (
                        <Button variant="outline" size="sm" className="h-8 px-3 flex-1" onClick={() => reindexMutation.mutate(doc.id)}>
                          <RotateCcw className="w-3.5 h-3.5 mr-1" /> 重新索引
                        </Button>
                      )}
                      {doc.status === 'failed' && (
                        <Button size="sm" className="h-8 px-3 flex-1" style={{ backgroundColor: '#3B4FCC' }} onClick={() => retryMutation.mutate(doc.id)}>
                          <RefreshCw className="w-3.5 h-3.5 mr-1" /> 重试
                        </Button>
                      )}
                      {(doc.status === 'uploading' || doc.status === 'parsing') && (
                        <Button variant="outline" size="sm" className="h-8 px-3 flex-1" onClick={() => cancelMutation.mutate(doc.id)}>
                          <X className="w-3.5 h-3.5 mr-1" /> 取消
                        </Button>
                      )}
                      <Button variant="ghost" size="sm" className="h-8 px-3 text-red-400 hover:text-red-600 hover:bg-red-50" onClick={() => setDeleteId(doc.id)}>
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Upload dialog */}
      <Dialog open={uploadOpen} onOpenChange={o => { if (!uploading) setUploadOpen(o) }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>上传文档</DialogTitle>
            <DialogDescription>将文件添加到知识库，支持 PDF、DOCX、XLSX、TXT、MD</DialogDescription>
          </DialogHeader>
          {uploading ? (
            <div className="py-8 space-y-4">
              <div className="flex items-center gap-3">
                <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
                <span className="text-sm text-gray-700 truncate">{uploadingFile}</span>
              </div>
              <Progress value={uploadProgress} className="h-2" />
              <p className="text-xs text-gray-400">{uploadProgress}% 上传完成</p>
            </div>
          ) : (
            <UploadZone onFiles={handleFiles} />
          )}
        </DialogContent>
      </Dialog>

      {/* Delete confirm dialog */}
      <Dialog open={deleteId !== null} onOpenChange={o => { if (!o) setDeleteId(null) }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>此操作不可逆，文档及其所有向量数据将被永久删除。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteId(null)}>取消</Button>
            <Button variant="destructive" onClick={() => {
              if (deleteId !== null) { deleteMutation.mutate(deleteId); setDeleteId(null) }
            }}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
