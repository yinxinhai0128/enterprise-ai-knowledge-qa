import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, HelpCircle, AlertTriangle, CheckCircle2, Clock, User, Loader2, FileText, MessageSquare, BarChart2, Shield, Users, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import { Progress } from '@/components/ui/progress'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { NavBar } from '@/components/NavBar'
import { getStats, getRefused, getHumanTasks, claimTask, completeTask, getFeedbackStats, getUsageReport, getRecentRecords, getUsers, createUser, toggleUserActive } from '@/api/admin'
import type { HumanTaskOut } from '@/types/api'
import { toast } from '@/hooks/use-toast'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/stores/auth'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

type TaskFilter = 'all' | 'pending' | 'claimed' | 'completed' | 'cancelled'

const FILTER_LABELS: Record<TaskFilter, string> = {
  all: '全部',
  pending: '待处理',
  claimed: '已领取',
  completed: '已完成',
  cancelled: '已取消',
}

function TaskStatusBadge({ status }: { status: HumanTaskOut['status'] }) {
  if (status === 'pending') return <Badge variant="warning">待处理</Badge>
  if (status === 'claimed') return <Badge variant="info">已领取</Badge>
  if (status === 'cancelled') return <Badge variant="secondary">已取消</Badge>
  return <Badge variant="success">已完成</Badge>
}

function StatCard({
  title, value, sub, icon: Icon, iconColor, iconBg,
}: {
  title: string
  value: string | number
  sub?: React.ReactNode
  icon: React.ElementType
  iconColor: string
  iconBg: string
}) {
  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
      <div className="flex items-start justify-between mb-4">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: iconBg }}>
          <Icon className="w-5 h-5" style={{ color: iconColor }} />
        </div>
        <span className="text-xs text-gray-400 mt-1">{title}</span>
      </div>
      <p className="text-3xl font-bold text-gray-900 tabular-nums">{value}</p>
      {sub && <div className="mt-2">{sub}</div>}
    </div>
  )
}

function MiniBarChart({ data }: { data: Array<{ date: string; total: number }> }) {
  const max = Math.max(...data.map(d => d.total), 1)
  return (
    <div className="flex items-end gap-1 h-20">
      {data.map(d => (
        <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
          <div
            className="w-full rounded-t"
            style={{
              height: `${Math.max((d.total / max) * 64, d.total ? 4 : 0)}px`,
              background: 'linear-gradient(180deg, #5B72F5 0%, #3B4FCC 100%)',
            }}
          />
          <span className="text-[9px] text-gray-400 truncate w-full text-center">
            {d.date.slice(5)}
          </span>
        </div>
      ))}
    </div>
  )
}

function UsersTab({ currentUser }: { currentUser: string }) {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState<'user' | 'admin'>('user')

  const { data: users = [], isLoading } = useQuery({
    queryKey: ['admin-users'],
    queryFn: getUsers,
    refetchInterval: 30000,
  })

  const createMutation = useMutation({
    mutationFn: () => createUser({ username: newUsername.trim(), password: newPassword, roles: [newRole] }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      setShowCreate(false)
      setNewUsername('')
      setNewPassword('')
      setNewRole('user')
      toast({ variant: 'success', title: '用户已创建' })
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast({ variant: 'destructive', title: '创建失败', description: typeof detail === 'string' ? detail : '请重试' })
    },
  })

  const toggleMutation = useMutation({
    mutationFn: (username: string) => toggleUserActive(username),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
    },
    onError: () => toast({ variant: 'destructive', title: '操作失败' }),
  })

  const canSubmit = newUsername.trim().length > 0 && newPassword.length >= 8

  return (
    <>
      <div className="flex items-center justify-between mb-5">
        <p className="text-sm text-gray-500">共 {users.length} 个账号</p>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm text-white font-medium transition-all hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }}
        >
          <UserPlus className="w-4 h-4" />
          创建用户
        </button>
      </div>

      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-14 rounded-2xl" />)}</div>
      ) : (
        <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/80">
                <th className="text-left px-4 py-3 text-gray-500 font-medium">用户名</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">角色</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">状态</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">创建时间</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {users.map(u => (
                <tr key={u.id} className="hover:bg-gray-50/60 transition-colors">
                  <td className="px-4 py-3 font-mono text-gray-800 flex items-center gap-2">
                    <User className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                    {u.username}
                    {u.username === currentUser && <span className="text-[10px] text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded-full">我</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1 flex-wrap">
                      {u.roles.map(r => (
                        <Badge key={r} variant={r === 'admin' ? 'warning' : 'secondary'} className="text-[10px]">{r}</Badge>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active
                      ? <Badge variant="success">启用</Badge>
                      : <Badge variant="secondary">禁用</Badge>}
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap" title={dayjs(u.created_at).format('YYYY-MM-DD HH:mm:ss')}>
                    {dayjs(u.created_at).fromNow()}
                  </td>
                  <td className="px-4 py-3">
                    {u.username !== currentUser && (
                      <button
                        onClick={() => toggleMutation.mutate(u.username)}
                        disabled={toggleMutation.isPending}
                        className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                          u.is_active
                            ? 'text-red-600 border-red-200 hover:bg-red-50'
                            : 'text-green-600 border-green-200 hover:bg-green-50'
                        }`}
                      >
                        {u.is_active ? '禁用' : '启用'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center text-gray-400">暂无用户</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={showCreate} onOpenChange={o => { if (!o) setShowCreate(false) }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>创建用户</DialogTitle>
            <DialogDescription>新用户将加入当前租户，密码至少 8 位</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-700 block mb-1">用户名</label>
              <Input
                value={newUsername}
                onChange={e => setNewUsername(e.target.value)}
                placeholder="只允许字母、数字及 . _ @ -"
                autoComplete="off"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 block mb-1">密码</label>
              <Input
                type="password"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                placeholder="至少 8 位"
                autoComplete="new-password"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 block mb-1">角色</label>
              <div className="flex gap-2">
                {(['user', 'admin'] as const).map(r => (
                  <button
                    key={r}
                    onClick={() => setNewRole(r)}
                    className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-all ${
                      newRole === r
                        ? 'text-white border-transparent'
                        : 'text-gray-500 border-gray-200 hover:border-gray-300'
                    }`}
                    style={newRole === r ? { background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' } : undefined}
                  >
                    {r === 'user' ? '普通员工' : '管理员'}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter className="mt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>取消</Button>
            <Button
              disabled={!canSubmit || createMutation.isPending}
              onClick={() => createMutation.mutate()}
              style={{ background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }}
              className="text-white"
            >
              {createMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function ReportsTab() {
  const { data: report, isLoading } = useQuery({
    queryKey: ['usage-report'],
    queryFn: () => getUsageReport(7),
  })
  const { data: fbStats } = useQuery({
    queryKey: ['feedback-stats'],
    queryFn: getFeedbackStats,
  })

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 rounded-2xl" />
        ))}
      </div>
    )
  }
  if (!report) return null

  const approvalRate = fbStats ? Math.round(fbStats.approval_rate * 100) : null

  return (
    <div className="space-y-4">
      {/* 概览卡片 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
          <p className="text-xs text-gray-400 mb-1">总问答数</p>
          <p className="text-2xl font-bold text-gray-900">{report.total}</p>
        </div>
        <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
          <p className="text-xs text-gray-400 mb-1">今日问答</p>
          <p className="text-2xl font-bold text-gray-900">{report.today}</p>
        </div>
        <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
          <p className="text-xs text-gray-400 mb-1">拒答率</p>
          <p className="text-2xl font-bold text-gray-900">
            {(report.refused_rate * 100).toFixed(1)}%
          </p>
        </div>
        <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
          <p className="text-xs text-gray-400 mb-1">好评率</p>
          <p className="text-2xl font-bold text-gray-900">
            {approvalRate !== null ? `${approvalRate}%` : '—'}
          </p>
        </div>
      </div>

      {/* 每日趋势 */}
      <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
        <p className="text-sm font-medium text-gray-700 mb-3">过去 {report.days} 天问答量</p>
        <MiniBarChart data={report.daily} />
      </div>

      {/* 热门文档 + 活跃用户 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <p className="text-sm font-medium text-gray-700 mb-3">热门文档 Top 5</p>
          {report.top_docs.length === 0 ? (
            <p className="text-xs text-gray-400">暂无数据</p>
          ) : (
            <ol className="space-y-2">
              {report.top_docs.map((d, i) => (
                <li key={d.doc_name} className="flex items-center justify-between text-sm">
                  <span className="text-gray-500 mr-2 w-4 text-right">{i + 1}.</span>
                  <span className="flex-1 truncate text-gray-700">{d.doc_name}</span>
                  <span className="text-xs text-gray-400 ml-2">{d.cite_count} 次</span>
                </li>
              ))}
            </ol>
          )}
        </div>
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
          <p className="text-sm font-medium text-gray-700 mb-3">活跃用户 Top 10</p>
          {report.top_users.length === 0 ? (
            <p className="text-xs text-gray-400">暂无数据</p>
          ) : (
            <ol className="space-y-2">
              {report.top_users.map((u, i) => (
                <li key={u.user_id + i} className="flex items-center justify-between text-sm">
                  <span className="text-gray-500 mr-2 w-4 text-right">{i + 1}.</span>
                  <span className="flex-1 text-gray-700 font-mono">{u.user_id}</span>
                  <span className="text-xs text-gray-400 ml-2">{u.count} 条</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </div>
  )
}

export default function AdminPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [taskFilter, setTaskFilter] = useState<TaskFilter>('pending')
  const [completeTaskId, setCompleteTaskId] = useState<number | null>(null)
  const [resolution, setResolution] = useState('')

  useEffect(() => {
    if (!auth.isAdmin) {
      toast({ variant: 'destructive', title: '无管理员权限' })
      navigate('/chat')
    }
  }, [auth.isAdmin, navigate])

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['admin-stats'],
    queryFn: getStats,
    refetchInterval: 30000,
    enabled: auth.isAdmin,
  })

  const { data: refused = [], isLoading: refusedLoading } = useQuery({
    queryKey: ['admin-refused'],
    queryFn: getRefused,
    refetchInterval: 30000,
    enabled: auth.isAdmin,
  })

  const { data: auditRecords = [], isLoading: auditLoading } = useQuery({
    queryKey: ['admin-records'],
    queryFn: () => getRecentRecords(50),
    refetchInterval: 30000,
    enabled: auth.isAdmin,
  })

  const { data: tasks = [], isLoading: tasksLoading, refetch: refetchTasks } = useQuery({
    queryKey: ['admin-tasks', taskFilter],
    queryFn: () => getHumanTasks(taskFilter === 'all' ? undefined : taskFilter),
    enabled: auth.isAdmin,
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

  if (!auth.isAdmin) return null

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <NavBar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Header */}
        <div className="h-14 flex items-center gap-3 px-6 border-b border-gray-100 bg-white shadow-sm">
          <Shield className="w-4 h-4 text-gray-400" />
          <span className="font-medium text-gray-700 text-sm">管理员面板</span>
        </div>

        <div className="flex-1 overflow-y-auto p-6 scrollbar-thin">
          <Tabs defaultValue="stats">
            <TabsList className="mb-6 bg-gray-100 p-1 rounded-xl">
              <TabsTrigger value="stats" className="rounded-lg text-sm">统计概览</TabsTrigger>
              <TabsTrigger value="tasks" className="rounded-lg text-sm">人工任务</TabsTrigger>
              <TabsTrigger value="audit" className="rounded-lg text-sm">审计记录</TabsTrigger>
              <TabsTrigger value="reports" className="rounded-lg text-sm">使用报表</TabsTrigger>
              <TabsTrigger value="users" className="rounded-lg text-sm flex items-center gap-1">
                <Users className="w-3.5 h-3.5" />用户管理
              </TabsTrigger>
            </TabsList>

            {/* Tab 1: Stats */}
            <TabsContent value="stats" className="animate-fade-in">
              {statsLoading ? (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                  {[0, 1, 2].map(i => <Skeleton key={i} className="h-32 rounded-2xl" />)}
                </div>
              ) : stats ? (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                  <StatCard
                    title="文档总数"
                    value={stats.documents.total}
                    icon={FileText}
                    iconColor="#3B4FCC"
                    iconBg="linear-gradient(135deg, #EEF2FF 0%, #C7D2FE 100%)"
                    sub={
                      <div className="flex gap-2">
                        <Badge variant="success">已索引 {stats.documents.indexed}</Badge>
                        {stats.documents.failed > 0 && <Badge variant="destructive">失败 {stats.documents.failed}</Badge>}
                      </div>
                    }
                  />
                  <StatCard
                    title="问答总数"
                    value={stats.qa.total}
                    icon={MessageSquare}
                    iconColor="#059669"
                    iconBg="linear-gradient(135deg, #ECFDF5 0%, #A7F3D0 100%)"
                    sub={<p className="text-xs text-gray-400">累计问答记录</p>}
                  />
                  <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
                    <div className="flex items-start justify-between mb-4">
                      <div className="w-10 h-10 rounded-xl flex items-center justify-center"
                        style={{ background: 'linear-gradient(135deg, #FFF7ED 0%, #FED7AA 100%)' }}>
                        <BarChart2 className="w-5 h-5 text-orange-500" />
                      </div>
                      <span className="text-xs text-gray-400 mt-1">质量指标</span>
                    </div>
                    <div className="space-y-3">
                      <div>
                        <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                          <span>拒答率</span>
                          <span className="font-medium">{(stats.qa.refused_rate * 100).toFixed(1)}%</span>
                        </div>
                        <Progress value={stats.qa.refused_rate * 100} className="h-1.5 [&>div]:bg-orange-400" />
                      </div>
                      <div>
                        <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                          <span>转人工率</span>
                          <span className="font-medium">{(stats.qa.human_rate * 100).toFixed(1)}%</span>
                        </div>
                        <Progress value={stats.qa.human_rate * 100} className="h-1.5 [&>div]:bg-yellow-400" />
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Recent refused */}
                <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
                  <div className="flex items-center gap-2 mb-4">
                    <div className="w-7 h-7 rounded-lg bg-red-50 flex items-center justify-center">
                      <HelpCircle className="w-4 h-4 text-red-400" />
                    </div>
                    <h3 className="text-sm font-medium text-gray-700">最近拒答记录</h3>
                  </div>
                  {refusedLoading ? <Skeleton className="h-32" /> : refused.length === 0 ? (
                    <div className="text-center py-8">
                      <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-green-300" />
                      <p className="text-sm text-gray-400">暂无拒答记录</p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {refused.slice(0, 8).map(r => (
                        <div key={r.id} className="flex items-start gap-2.5 py-2.5 border-b border-gray-50 last:border-0">
                          <span className="w-1.5 h-1.5 rounded-full bg-red-300 mt-1.5 shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-gray-700 truncate">{r.question}</p>
                            <p className="text-xs text-gray-400 mt-0.5">{dayjs(r.created_at).fromNow()}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Recent human tasks */}
                <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
                  <div className="flex items-center gap-2 mb-4">
                    <div className="w-7 h-7 rounded-lg bg-yellow-50 flex items-center justify-center">
                      <AlertTriangle className="w-4 h-4 text-yellow-500" />
                    </div>
                    <h3 className="text-sm font-medium text-gray-700">最近转人工记录</h3>
                  </div>
                  {tasksLoading ? <Skeleton className="h-32" /> : tasks.filter(t => t.status === 'pending').length === 0 ? (
                    <div className="text-center py-8">
                      <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-green-300" />
                      <p className="text-sm text-gray-400">暂无待处理任务</p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {tasks.filter(t => t.status === 'pending').slice(0, 8).map(t => (
                        <div key={t.id} className="flex items-start gap-2.5 py-2.5 border-b border-gray-50 last:border-0">
                          <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 mt-1.5 shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-gray-700 truncate">{t.reason}</p>
                            <div className="flex items-center gap-2 mt-0.5">
                              <Badge variant="destructive" className="text-[10px]">{t.category}</Badge>
                              <span className="text-xs text-gray-400">{dayjs(t.created_at).fromNow()}</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </TabsContent>

            {/* Tab 2: Human tasks */}
            <TabsContent value="tasks" className="animate-fade-in">
              <div className="flex items-center justify-between mb-5">
                <div className="flex gap-1.5">
                  {(Object.keys(FILTER_LABELS) as TaskFilter[]).map(f => (
                    <button
                      key={f}
                      onClick={() => setTaskFilter(f)}
                      className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all ${
                        taskFilter === f
                          ? 'text-white shadow-sm'
                          : 'text-gray-500 bg-gray-100 hover:bg-gray-200'
                      }`}
                      style={taskFilter === f
                        ? { background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }
                        : undefined}
                    >
                      {FILTER_LABELS[f]}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => refetchTasks()}
                  className="p-2 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </div>

              {tasksLoading ? (
                <div className="space-y-3">
                  {[0, 1, 2].map(i => <Skeleton key={i} className="h-32 rounded-2xl" />)}
                </div>
              ) : tasks.length === 0 ? (
                <div className="text-center py-20">
                  <div className="w-14 h-14 rounded-2xl bg-gray-100 flex items-center justify-center mx-auto mb-4">
                    <CheckCircle2 className="w-7 h-7 text-gray-300" />
                  </div>
                  <p className="text-sm text-gray-400">
                    暂无{taskFilter !== 'all' ? FILTER_LABELS[taskFilter] : ''}任务
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {tasks.map(t => (
                    <div key={t.id} className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-3 flex-wrap">
                            <Badge variant="destructive">{t.category}</Badge>
                            <TaskStatusBadge status={t.status} />
                            <span className="text-xs text-gray-400">#{t.id}</span>
                            <span className="text-xs text-gray-400 flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {dayjs(t.created_at).fromNow()}
                            </span>
                          </div>
                          <div className="bg-gray-50 rounded-xl px-4 py-3 mb-3 border border-gray-100">
                            <p className="text-sm text-gray-700 leading-relaxed">{t.reason}</p>
                          </div>
                          {t.status === 'completed' && t.resolution && (
                            <div className="flex items-start gap-2 text-xs text-green-700 bg-green-50 rounded-xl px-3 py-2.5 border border-green-100">
                              <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                              <span>{t.resolution}</span>
                            </div>
                          )}
                          {t.assigned_to && (
                            <p className="text-xs text-gray-400 mt-2 flex items-center gap-1">
                              <User className="w-3 h-3" /> {t.assigned_to}
                            </p>
                          )}
                        </div>
                        <div className="flex flex-col gap-2 shrink-0">
                          {t.status === 'pending' && (
                            <button
                              className="px-4 py-2 rounded-xl text-sm text-white font-medium transition-all hover:opacity-90 disabled:opacity-50"
                              style={{ background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }}
                              disabled={claimMutation.isPending}
                              onClick={() => claimMutation.mutate(t.id)}
                            >
                              {claimMutation.isPending
                                ? <Loader2 className="w-4 h-4 animate-spin" />
                                : '领取任务'}
                            </button>
                          )}
                          {t.status === 'claimed' && (
                            <button
                              className="px-4 py-2 rounded-xl text-sm text-green-700 font-medium border border-green-200 hover:bg-green-50 transition-colors"
                              onClick={() => { setCompleteTaskId(t.id); setResolution('') }}
                            >
                              标记完成
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>

            {/* Tab 4: Reports */}
            <TabsContent value="reports" className="animate-fade-in">
              <ReportsTab />
            </TabsContent>

            {/* Tab 5: Users */}
            <TabsContent value="users" className="animate-fade-in">
              <UsersTab currentUser={auth.userId ?? ''} />
            </TabsContent>

            {/* Tab 3: Audit */}
            <TabsContent value="audit" className="animate-fade-in">
              {auditLoading ? <Skeleton className="h-64 rounded-2xl" /> : (
                <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-sm">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-100 bg-gray-50/80">
                        <th className="text-left px-4 py-3 text-gray-500 font-medium">时间</th>
                        <th className="text-left px-4 py-3 text-gray-500 font-medium">用户</th>
                        <th className="text-left px-4 py-3 text-gray-500 font-medium">问题</th>
                        <th className="text-left px-4 py-3 text-gray-500 font-medium">来源</th>
                        <th className="text-left px-4 py-3 text-gray-500 font-medium">拒答</th>
                        <th className="text-left px-4 py-3 text-gray-500 font-medium">Token</th>
                        <th className="text-left px-4 py-3 text-gray-500 font-medium">延迟(ms)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {auditRecords.map(r => (
                        <tr key={r.id} className="hover:bg-gray-50/60 transition-colors">
                          <td className="px-4 py-2.5 text-gray-400 whitespace-nowrap" title={dayjs(r.created_at).format('YYYY-MM-DD HH:mm:ss')}>{dayjs(r.created_at).fromNow()}</td>
                          <td className="px-4 py-2.5 text-gray-600 max-w-[80px] truncate font-mono">{r.user_id}</td>
                          <td className="px-4 py-2.5 text-gray-700 max-w-[200px] truncate">{r.question}</td>
                          <td className="px-4 py-2.5">
                            {r.has_source
                              ? <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
                              : <span className="text-gray-200">—</span>}
                          </td>
                          <td className="px-4 py-2.5">
                            {r.refused ? <Badge variant="warning" className="text-[10px] px-1.5">拒答</Badge> : <span className="text-gray-200">—</span>}
                          </td>
                          <td className="px-4 py-2.5 text-gray-500 tabular-nums">{r.total_tokens}</td>
                          <td className="px-4 py-2.5 text-gray-500 tabular-nums">{Math.round(r.latency_ms)}</td>
                        </tr>
                      ))}
                      {auditRecords.length === 0 && (
                        <tr>
                          <td colSpan={7} className="px-4 py-12 text-center text-gray-400">暂无审计记录</td>
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
            className="rounded-xl"
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
              style={{ background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }}
              className="text-white"
            >
              {completeMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : '提交'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
