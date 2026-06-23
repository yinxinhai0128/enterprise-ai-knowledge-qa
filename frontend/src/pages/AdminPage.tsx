import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, HelpCircle, AlertTriangle, CheckCircle2, Clock, User, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import { Progress } from '@/components/ui/progress'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { NavBar } from '@/components/NavBar'
import { getStats, getRefused, getHumanTasks, claimTask, completeTask } from '@/api/admin'
import type { HumanTaskOut } from '@/types/api'
import { toast } from '@/hooks/use-toast'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/stores/auth'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

type TaskFilter = 'all' | 'pending' | 'claimed' | 'completed'

const FILTER_LABELS: Record<TaskFilter, string> = {
  all: '全部',
  pending: '待处理',
  claimed: '已领取',
  completed: '已完成',
}

function TaskStatusBadge({ status }: { status: HumanTaskOut['status'] }) {
  if (status === 'pending') return <Badge variant="warning">待处理</Badge>
  if (status === 'claimed') return <Badge variant="info">已领取</Badge>
  return <Badge variant="success">已完成</Badge>
}

export default function AdminPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [taskFilter, setTaskFilter] = useState<TaskFilter>('pending')
  const [completeTaskId, setCompleteTaskId] = useState<number | null>(null)
  const [resolution, setResolution] = useState('')

  if (!auth.isAdmin) {
    navigate('/chat')
    toast({ variant: 'destructive', title: '无管理员权限' })
    return null
  }

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['admin-stats'],
    queryFn: getStats,
    refetchInterval: 30000,
  })

  const { data: refused = [], isLoading: refusedLoading } = useQuery({
    queryKey: ['admin-refused'],
    queryFn: getRefused,
    refetchInterval: 30000,
  })

  const { data: tasks = [], isLoading: tasksLoading, refetch: refetchTasks } = useQuery({
    queryKey: ['admin-tasks', taskFilter],
    queryFn: () => getHumanTasks(taskFilter === 'all' ? undefined : taskFilter),
  })

  const claimMutation = useMutation({
    mutationFn: claimTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-tasks'] })
      toast({ title: '已领取任务' })
    },
  })

  const completeMutation = useMutation({
    mutationFn: ({ id, res }: { id: number; res: string }) => completeTask(id, res),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-tasks'] })
      setCompleteTaskId(null)
      setResolution('')
      toast({ variant: 'success', title: '任务已完成' })
    },
  })

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <NavBar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Header */}
        <div className="h-14 flex items-center px-6 border-b border-gray-200 bg-white">
          <span className="font-medium text-gray-800">管理员面板</span>
        </div>

        <div className="flex-1 overflow-y-auto p-6 scrollbar-thin">
          <Tabs defaultValue="stats">
            <TabsList className="mb-6">
              <TabsTrigger value="stats">统计概览</TabsTrigger>
              <TabsTrigger value="tasks">人工任务</TabsTrigger>
              <TabsTrigger value="audit">审计记录</TabsTrigger>
            </TabsList>

            {/* Tab 1: Stats */}
            <TabsContent value="stats">
              {statsLoading ? (
                <div className="grid grid-cols-3 gap-4 mb-6">
                  {[0, 1, 2].map(i => <Skeleton key={i} className="h-28 rounded-xl" />)}
                </div>
              ) : stats ? (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm text-gray-500">文档总数</CardTitle></CardHeader>
                    <CardContent>
                      <p className="text-3xl font-bold text-gray-900">{stats.documents.total}</p>
                      <div className="flex gap-2 mt-2">
                        <Badge variant="success">已索引 {stats.documents.indexed}</Badge>
                        {stats.documents.failed > 0 && <Badge variant="destructive">失败 {stats.documents.failed}</Badge>}
                      </div>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm text-gray-500">问答总数</CardTitle></CardHeader>
                    <CardContent>
                      <p className="text-3xl font-bold text-gray-900">{stats.qa.total}</p>
                      <p className="text-xs text-gray-400 mt-2">累计问答记录</p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm text-gray-500">质量指标</CardTitle></CardHeader>
                    <CardContent className="space-y-3">
                      <div>
                        <div className="flex justify-between text-xs text-gray-500 mb-1">
                          <span>拒答率</span>
                          <span>{(stats.qa.refused_rate * 100).toFixed(1)}%</span>
                        </div>
                        <Progress value={stats.qa.refused_rate * 100} className="h-1.5 [&>div]:bg-orange-400" />
                      </div>
                      <div>
                        <div className="flex justify-between text-xs text-gray-500 mb-1">
                          <span>转人工率</span>
                          <span>{(stats.qa.human_rate * 100).toFixed(1)}%</span>
                        </div>
                        <Progress value={stats.qa.human_rate * 100} className="h-1.5 [&>div]:bg-yellow-400" />
                      </div>
                    </CardContent>
                  </Card>
                </div>
              ) : null}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <HelpCircle className="w-4 h-4 text-gray-400" />
                      最近拒答记录
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {refusedLoading ? <Skeleton className="h-32" /> : refused.length === 0 ? (
                      <p className="text-sm text-gray-400 text-center py-6">暂无拒答记录 🎉</p>
                    ) : (
                      <div className="space-y-2">
                        {refused.slice(0, 8).map(r => (
                          <div key={r.id} className="flex items-start gap-2 py-2 border-b border-gray-50 last:border-0">
                            <HelpCircle className="w-3.5 h-3.5 text-gray-300 mt-0.5 shrink-0" />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm text-gray-700 truncate">{r.question}</p>
                              <p className="text-xs text-gray-400">{dayjs(r.created_at).fromNow()}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-yellow-500" />
                      最近转人工记录
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {tasksLoading ? <Skeleton className="h-32" /> : tasks.length === 0 ? (
                      <p className="text-sm text-gray-400 text-center py-6">暂无待处理任务</p>
                    ) : (
                      <div className="space-y-2">
                        {tasks.filter(t => t.status === 'pending').slice(0, 8).map(t => (
                          <div key={t.id} className="flex items-start gap-2 py-2 border-b border-gray-50 last:border-0">
                            <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 mt-0.5 shrink-0" />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm text-gray-700 truncate">{t.reason}</p>
                              <div className="flex items-center gap-2 mt-0.5">
                                <Badge variant="destructive" className="text-xs">{t.category}</Badge>
                                <span className="text-xs text-gray-400">{dayjs(t.created_at).fromNow()}</span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            {/* Tab 2: Human tasks */}
            <TabsContent value="tasks">
              <div className="flex items-center justify-between mb-4">
                <div className="flex gap-2">
                  {(Object.keys(FILTER_LABELS) as TaskFilter[]).map(f => (
                    <Button
                      key={f}
                      variant={taskFilter === f ? 'default' : 'outline'}
                      size="sm"
                      style={taskFilter === f ? { backgroundColor: '#3B4FCC' } : undefined}
                      onClick={() => setTaskFilter(f)}
                    >
                      {FILTER_LABELS[f]}
                    </Button>
                  ))}
                </div>
                <Button variant="ghost" size="sm" onClick={() => refetchTasks()}>
                  <RefreshCw className="w-4 h-4" />
                </Button>
              </div>

              {tasksLoading ? (
                <div className="space-y-3">
                  {[0, 1, 2].map(i => <Skeleton key={i} className="h-32 rounded-xl" />)}
                </div>
              ) : tasks.length === 0 ? (
                <div className="text-center py-16 text-gray-400">
                  <CheckCircle2 className="w-10 h-10 mx-auto mb-3 text-gray-200" />
                  <p>暂无{taskFilter !== 'all' ? FILTER_LABELS[taskFilter] : ''}任务</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {tasks.map(t => (
                    <Card key={t.id}>
                      <CardContent className="pt-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-2 flex-wrap">
                              <Badge variant="destructive">{t.category}</Badge>
                              <TaskStatusBadge status={t.status} />
                              <span className="text-xs text-gray-400">#{t.id}</span>
                              <span className="text-xs text-gray-400 flex items-center gap-1">
                                <Clock className="w-3 h-3" />{dayjs(t.created_at).fromNow()}
                              </span>
                            </div>
                            <div className="bg-gray-50 rounded-lg p-3 mb-2">
                              <p className="text-sm text-gray-700">{t.reason}</p>
                            </div>
                            {t.status === 'completed' && t.resolution && (
                              <div className="flex items-start gap-1.5 text-xs text-green-700 bg-green-50 rounded-lg p-2">
                                <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                                {t.resolution}
                              </div>
                            )}
                            {t.assigned_to && (
                              <p className="text-xs text-gray-400 mt-1 flex items-center gap-1">
                                <User className="w-3 h-3" /> {t.assigned_to}
                              </p>
                            )}
                          </div>
                          <div className="flex flex-col gap-2 shrink-0">
                            {t.status === 'pending' && (
                              <Button size="sm" style={{ backgroundColor: '#3B4FCC' }}
                                disabled={claimMutation.isPending}
                                onClick={() => claimMutation.mutate(t.id)}>
                                {claimMutation.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : '领取任务'}
                              </Button>
                            )}
                            {t.status === 'claimed' && (
                              <Button size="sm" variant="outline" className="text-green-700 border-green-200 hover:bg-green-50"
                                onClick={() => { setCompleteTaskId(t.id); setResolution('') }}>
                                标记完成
                              </Button>
                            )}
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </TabsContent>

            {/* Tab 3: Audit */}
            <TabsContent value="audit">
              {refusedLoading ? <Skeleton className="h-64" /> : (
                <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-100 bg-gray-50">
                        <th className="text-left px-4 py-2.5 text-gray-500 font-medium">时间</th>
                        <th className="text-left px-4 py-2.5 text-gray-500 font-medium">用户</th>
                        <th className="text-left px-4 py-2.5 text-gray-500 font-medium">问题</th>
                        <th className="text-left px-4 py-2.5 text-gray-500 font-medium">来源</th>
                        <th className="text-left px-4 py-2.5 text-gray-500 font-medium">拒答</th>
                        <th className="text-left px-4 py-2.5 text-gray-500 font-medium">Token</th>
                        <th className="text-left px-4 py-2.5 text-gray-500 font-medium">延迟(ms)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {refused.map(r => (
                        <tr key={r.id} className="hover:bg-gray-50">
                          <td className="px-4 py-2.5 text-gray-400">{dayjs(r.created_at).fromNow()}</td>
                          <td className="px-4 py-2.5 text-gray-600 max-w-[80px] truncate">{r.user_id}</td>
                          <td className="px-4 py-2.5 text-gray-700 max-w-[200px] truncate">{r.question}</td>
                          <td className="px-4 py-2.5">
                            {r.has_source ? <span className="text-green-600">✓</span> : <span className="text-gray-300">—</span>}
                          </td>
                          <td className="px-4 py-2.5">
                            {r.refused ? <Badge variant="warning" className="text-[10px] px-1.5">拒答</Badge> : null}
                          </td>
                          <td className="px-4 py-2.5 text-gray-500">{r.total_tokens}</td>
                          <td className="px-4 py-2.5 text-gray-500">{Math.round(r.latency_ms)}</td>
                        </tr>
                      ))}
                      {refused.length === 0 && (
                        <tr>
                          <td colSpan={7} className="px-4 py-8 text-center text-gray-400">暂无审计记录</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </div>

      {/* Complete task dialog */}
      <Dialog open={completeTaskId !== null} onOpenChange={o => { if (!o) setCompleteTaskId(null) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>完成任务</DialogTitle>
            <DialogDescription>请填写处理意见（至少 10 个字符）</DialogDescription>
          </DialogHeader>
          <Textarea
            value={resolution}
            onChange={e => setResolution(e.target.value)}
            placeholder="请描述处理结果、判断依据或采取的行动…"
            rows={4}
          />
          <p className="text-xs text-gray-400">{resolution.length} / 4000</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCompleteTaskId(null)}>取消</Button>
            <Button
              disabled={resolution.trim().length < 10 || completeMutation.isPending}
              onClick={() => {
                if (completeTaskId !== null) {
                  completeMutation.mutate({ id: completeTaskId, res: resolution.trim() })
                }
              }}
              style={{ backgroundColor: '#3B4FCC' }}
            >
              {completeMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : '提交'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
