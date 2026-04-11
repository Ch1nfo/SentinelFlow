import { type ComponentType, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import {
  Bot,
  BellRing,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  LayoutDashboard,
  ListTodo,
  MessageSquareText,
  Radar,
  Settings,
  Shield,
  Siren,
} from 'lucide-react'
import { brand, withProductName } from '@/config/brand'
import { fetchPollAlerts } from '@/api/sentinelflow'
import { useSentinelFlowLiveRefresh } from '@/hooks/useSentinelFlowLiveRefresh'

type NavItem = {
  name: string
  href: string
  icon: ComponentType<{ className?: string }>
  description: string
}

type NavSection = {
  name: string
  items: NavItem[]
}

export default function Layout() {
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [newAlertNotice, setNewAlertNotice] = useState<{ count: number; timestamp: string } | null>(null)
  const knownTaskIdsRef = useRef<Set<string> | null>(null)

  const navigation = useMemo<NavSection[]>(
    () => [
      {
        name: '平台总览',
        items: [
          { name: '态势总览', href: '/', icon: LayoutDashboard, description: '查看平台健康度、运行摘要和近期动作。' },
        ],
      },
      {
        name: '值班工作面',
        items: [
          { name: '告警工作台', href: '/alerts', icon: Siren, description: '查看轮询结果并处理单条告警。' },
          { name: '任务中心', href: '/tasks', icon: ListTodo, description: '查看任务状态、结果和重试动作。' },
          { name: '对话指挥台', href: '/conversation', icon: MessageSquareText, description: '通过自然语言调用主 Agent 处理问题。' },
        ],
      },
      {
        name: '平台能力',
        items: [
          { name: 'Skills', href: '/skills', icon: BookOpen, description: '管理平台可读取和可执行的 Skills。' },
          { name: 'Agents', href: '/agents', icon: Bot, description: withProductName('管理主 Agent、子 Agent 和技能权限。') },
          { name: '工作流', href: '/workflows', icon: Radar, description: withProductName('编排任务和告警场景下的 Agent Workflow。') },
          { name: '平台设置', href: '/settings', icon: Settings, description: '配置平台参数、告警接入和解析规则。' },
        ],
      },
    ],
    [],
  )

  const refreshAlertNotice = useMemo(
    () => async () => {
      const result = await fetchPollAlerts()
      const currentTaskIds = new Set((result.tasks ?? []).map((task) => task.task_id).filter(Boolean))
      if (knownTaskIdsRef.current === null) {
        knownTaskIdsRef.current = currentTaskIds
        return
      }
      const previous = knownTaskIdsRef.current
      let addedCount = 0
      for (const taskId of currentTaskIds) {
        if (!previous.has(taskId)) {
          addedCount += 1
        }
      }
      knownTaskIdsRef.current = currentTaskIds
      if (addedCount > 0) {
        setNewAlertNotice({ count: addedCount, timestamp: new Date().toISOString() })
      }
    },
    [],
  )

  useSentinelFlowLiveRefresh(refreshAlertNotice, { intervalMs: 5000 })

  useEffect(() => {
    if (!newAlertNotice) return
    const timer = window.setTimeout(() => {
      setNewAlertNotice(null)
    }, 8000)
    return () => window.clearTimeout(timer)
  }, [newAlertNotice])

  return (
    <div className="min-h-screen bg-gray-50">
      {newAlertNotice ? (
        <div className="fixed right-6 top-6 z-50 max-w-sm rounded-2xl border border-red-200 bg-white px-4 py-4 shadow-lg">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-xl bg-red-50 text-red-500">
              <BellRing className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-slate-900">发现新告警</div>
              <div className="mt-1 text-sm leading-6 text-slate-600">
                新刷入 {newAlertNotice.count} 条告警，不用手动刷新页面了。
              </div>
              <div className="mt-3 flex items-center gap-3">
                <Link to="/alerts" className="text-sm font-semibold text-sky-700 hover:text-sky-600">
                  前往告警工作台
                </Link>
                <button type="button" className="text-sm text-slate-500 hover:text-slate-700" onClick={() => setNewAlertNotice(null)}>
                  关闭
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <aside
        className={`fixed inset-y-0 left-0 z-40 border-r border-gray-200 bg-white transition-all duration-300 ${
          collapsed ? 'w-20' : 'w-72'
        }`}
      >
        <div className="flex h-full flex-col overflow-hidden">
          <div className={`flex h-16 items-center border-b border-gray-200 ${collapsed ? 'justify-center px-2' : 'px-5'}`}>
            {collapsed ? (
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-sky-600 to-emerald-500 text-white shadow-sm">
                <Shield className="h-5 w-5" />
              </div>
            ) : (
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-sky-600 to-emerald-500 text-white shadow-sm">
                    <Shield className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-lg font-bold text-gray-900">{brand.productName}</div>
                    <div className="truncate text-xs text-gray-500">{brand.platformTagline}</div>
                  </div>
                </div>
              </div>
            )}
            {!collapsed && (
              <button
                type="button"
                onClick={() => setCollapsed(true)}
                className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
                aria-label="Collapse sidebar"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            )}
          </div>

          <nav className={`flex-1 overflow-y-auto py-5 ${collapsed ? 'px-2' : 'px-4'}`}>
            {navigation.map((section) => (
              <div key={section.name} className="mb-7">
                {!collapsed && (
                  <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
                    {section.name}
                  </div>
                )}
                <div className="space-y-1.5">
                  {section.items.map((item) => {
                    const active = location.pathname === item.href
                    return (
                      <Link
                        key={item.href}
                        to={item.href}
                        title={collapsed ? item.name : undefined}
                        className={`flex rounded-2xl border transition-all ${
                          collapsed
                            ? 'justify-center px-2 py-3'
                            : 'items-center gap-3 px-3 py-3'
                        } ${
                          active
                            ? 'border-sky-200 bg-gradient-to-r from-sky-50 to-emerald-50 text-slate-900 shadow-sm'
                            : 'border-transparent text-gray-600 hover:border-gray-200 hover:bg-gray-50 hover:text-gray-900'
                        }`}
                      >
                        <item.icon className={`h-5 w-5 flex-shrink-0 ${active ? 'text-sky-700' : 'text-gray-400'}`} />
                        {!collapsed && (
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold">{item.name}</div>
                          </div>
                        )}
                      </Link>
                    )
                  })}
                </div>
              </div>
            ))}
          </nav>

          <div className={`border-t border-gray-200 ${collapsed ? 'p-2' : 'p-4'}`}>
            {collapsed ? (
              <button
                type="button"
                onClick={() => setCollapsed(false)}
                className="flex w-full items-center justify-center rounded-xl border border-gray-200 bg-gray-50 p-2 text-gray-600 transition-colors hover:bg-gray-100"
                aria-label="Expand sidebar"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            ) : (
              <div className="rounded-2xl border border-emerald-100 bg-gradient-to-r from-emerald-50 to-sky-50 p-4">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <BellRing className="h-4 w-4 text-emerald-600" />
                  {brand.productName} 平台入口
                </div>
                <p className="mt-2 text-xs leading-5 text-gray-600">
                  {withProductName('统一承载告警接入、任务闭环、Agent Workflow、Skills 和对话指挥能力。')}
                </p>
              </div>
            )}
          </div>
        </div>
      </aside>

      <main className={`${collapsed ? 'lg:pl-20' : 'lg:pl-72'} min-h-screen transition-all duration-300`}>
        <div className="mx-auto max-w-[1800px] px-4 py-8 lg:px-6 xl:px-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
