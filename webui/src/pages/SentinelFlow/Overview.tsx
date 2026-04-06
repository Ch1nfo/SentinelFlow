import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BarChart3, BookOpen, ChevronRight, LayoutDashboard, ListTodo, MessageSquareText, ShieldAlert, Siren } from 'lucide-react'
import { fetchAuditEvents, fetchDashboardSummary, fetchHealth, fetchPollAlerts, fetchSkills } from '@/api/sentinelflow'
import Surface from '@/components/sentinelflow/Surface'
import StatusBadge from '@/components/sentinelflow/StatusBadge'
import PageHeader from '@/components/common/PageHeader'
import { brand, withProductName } from '@/config/brand'
import { useSentinelFlowAsyncData } from '@/hooks/useSentinelFlowAsyncData'
import { readRuntimeActivity, subscribeRuntimeActivity, type RuntimeActivity } from '@/utils/sentinelflowRuntimeSync'

export default function SentinelFlowOverviewPage() {
  const { data: health, reload: reloadHealth } = useSentinelFlowAsyncData(fetchHealth, [])
  const { data: poll, reload: reloadPoll } = useSentinelFlowAsyncData(fetchPollAlerts, [])
  const { data: skills, reload: reloadSkills } = useSentinelFlowAsyncData(fetchSkills, [])
  const { data: audit, reload: reloadAudit } = useSentinelFlowAsyncData(fetchAuditEvents, [])
  const { data: summary, reload: reloadSummary } = useSentinelFlowAsyncData(fetchDashboardSummary, [])
  const [activity, setActivity] = useState<RuntimeActivity | null>(() => readRuntimeActivity())

  useEffect(() => {
    return subscribeRuntimeActivity((next) => {
      setActivity(next)
      void Promise.all([reloadHealth(), reloadPoll(), reloadSkills(), reloadAudit(), reloadSummary()])
    })
  }, [reloadAudit, reloadHealth, reloadPoll, reloadSkills, reloadSummary])

  const tasks = poll?.tasks ?? []
  const skillCount = skills?.skills?.length ?? 0
  const auditCount = audit?.events?.length ?? 0
  const runningCount = tasks.filter((task) => task.status === 'running').length
  const failedCount = tasks.filter((task) => task.status === 'failed').length

  return (
    <div className="sentinelflow-page-stack">
      <PageHeader
        title={`${brand.productName} 总览`}
        description={withProductName('查看平台当前运行状态、任务概览和最近动作。')}
        icon={<LayoutDashboard className="w-8 h-8" />}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Link
          to="/alerts"
          className="group flex items-center gap-4 rounded-xl border border-gray-200 bg-white p-5 transition-all hover:border-sky-200 hover:shadow-md"
        >
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-50 text-red-500">
            <Siren className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-gray-900">告警工作台</h3>
            <p className="mt-1 text-xs text-gray-500">进入研判、处置、通知和单条闭环操作入口。</p>
          </div>
          <ChevronRight className="h-4 w-4 text-gray-300 transition-colors group-hover:text-sky-500" />
        </Link>

        <Link
          to="/tasks"
          className="group flex items-center gap-4 rounded-xl border border-gray-200 bg-white p-5 transition-all hover:border-violet-200 hover:shadow-md"
        >
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-50 text-violet-500">
            <ListTodo className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-gray-900">任务中心</h3>
            <p className="mt-1 text-xs text-gray-500">查看 queued / running / failed / succeeded 生命周期。</p>
          </div>
          <ChevronRight className="h-4 w-4 text-gray-300 transition-colors group-hover:text-violet-500" />
        </Link>

        <Link
          to="/conversation"
          className="group flex items-center gap-4 rounded-xl border border-gray-200 bg-white p-5 transition-all hover:border-emerald-200 hover:shadow-md"
        >
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-50 text-emerald-500">
            <MessageSquareText className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-gray-900">对话指挥台</h3>
            <p className="mt-1 text-xs text-gray-500">{withProductName('通过自然语言调度 SentinelFlow 的核心能力。')}</p>
          </div>
          <ChevronRight className="h-4 w-4 text-gray-300 transition-colors group-hover:text-emerald-500" />
        </Link>
      </div>

      <Surface title="平台总览" subtitle="优先展示值班最关心的运行态势、任务密度与能力可用性。">
        <div className="sentinelflow-stat-grid">
          <div className="sentinelflow-stat-card"><span>当前轮询拉取</span><strong>{poll?.fetched_count ?? 0}</strong><em>最新一次拉取结果</em></div>
          <div className="sentinelflow-stat-card"><span>待处理任务</span><strong>{poll?.queued_count ?? 0}</strong><em>待值班处理队列</em></div>
          <div className="sentinelflow-stat-card"><span>可用 Skills</span><strong>{skillCount}</strong><em>doc / exec / hybrid</em></div>
          <div className="sentinelflow-stat-card"><span>审计事件</span><strong>{auditCount}</strong><em>本地运行时审计</em></div>
          <div className="sentinelflow-stat-card"><span>业务触发</span><strong>{summary?.judgment.business_trigger ?? 0}</strong><em>已识别业务/测试触发</em></div>
          <div className="sentinelflow-stat-card"><span>误报</span><strong>{summary?.judgment.false_positive ?? 0}</strong><em>已识别规则误报</em></div>
          <div className="sentinelflow-stat-card"><span>真实攻击</span><strong>{summary?.judgment.true_attack ?? 0}</strong><em>已识别真实攻击</em></div>
          <div className="sentinelflow-stat-card"><span>封禁 IP</span><strong>{summary?.operations.banned_ip_count ?? 0}</strong><em>已执行封禁动作</em></div>
        </div>
      </Surface>

      <div className="sentinelflow-grid-2">
        <Surface title="运行健康度" subtitle="聚焦 Runtime、轮询、任务生命周期和演示模式。">
          <div className="sentinelflow-stack-list">
            <div className="sentinelflow-stack-item">
              <strong>{brand.productName} API</strong>
              <div className="sentinelflow-inline-status">
                <StatusBadge tone={health?.status === 'ok' ? 'success' : 'danger'}>{health?.status ?? 'unknown'}</StatusBadge>
                {health?.demo_mode ? <StatusBadge tone="warn">演示模式</StatusBadge> : null}
              </div>
            </div>
            <div className="sentinelflow-stack-item">
              <strong>轮询与分发</strong>
              <div className="sentinelflow-inline-status">
                <span>拉取 {poll?.fetched_count ?? 0}</span>
                <span>排队 {poll?.queued_count ?? 0}</span>
                <span>失败 {poll?.failed_count ?? 0}</span>
              </div>
            </div>
            <div className="sentinelflow-stack-item">
              <strong>任务生命周期</strong>
              <div className="sentinelflow-inline-status">
                <span>running {runningCount}</span>
                <span>failed {failedCount}</span>
              </div>
            </div>
            <div className="sentinelflow-stack-item">
              <strong>平台能力视图</strong>
              <div className="sentinelflow-inline-status">
                <BarChart3 className="h-4 w-4 text-gray-400" />
                <span>总览、告警、任务、Agent 和 Skills 已统一到同一平台入口。</span>
              </div>
            </div>
          </div>
        </Surface>

        <Surface title="最近平台动作" subtitle="记录最近一次跨页面操作，方便值班快速确认当前处理对象。">
          {activity ? (
            <div className="sentinelflow-activity-banner">
              <div className="sentinelflow-response-row">
                <StatusBadge tone={activity.success ? 'success' : 'warn'}>
                  {activity.success ? '最新动作成功' : '最新动作失败'}
                </StatusBadge>
                <span>{new Date(activity.timestamp).toLocaleString()}</span>
              </div>
              <strong>{activity.title}</strong>
              <p className="sentinelflow-muted-text">{activity.detail}</p>
            </div>
          ) : (
            <p className="sentinelflow-muted-text">当前还没有新的平台动作记录。</p>
          )}
        </Surface>
      </div>

      <Surface title="能力地图" subtitle={withProductName('以平台化信息架构概览 SentinelFlow 当前已落地的核心能力。')}>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <ShieldAlert className="h-4 w-4 text-red-500" />
              告警闭环
            </div>
            <p className="text-sm leading-6 text-gray-500">支持轮询拉取、研判结单、处置结单与通知值班。</p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <BookOpen className="h-4 w-4 text-emerald-500" />
              技能运行时
            </div>
            <p className="text-sm leading-6 text-gray-500">{withProductName('统一支持文档型和可执行型 Skills。')}</p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <MessageSquareText className="h-4 w-4 text-sky-500" />
              自然语言调度
            </div>
            <p className="text-sm leading-6 text-gray-500">支持自然语言查询、封禁、通知和处理最新告警等指令。</p>
          </div>
        </div>
      </Surface>

      <Surface title="研判与处置摘要" subtitle="把业务触发、误报、真实攻击和封禁 IP 显示到首页，方便值班直接看分布情况。">
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h3 className="mb-3 text-sm font-semibold text-gray-900">研判结果分布</h3>
            <div className="sentinelflow-stack-list">
              <div className="sentinelflow-stack-item"><strong>业务触发 / 测试</strong><span>{summary?.judgment.business_trigger ?? 0} 条</span></div>
              <div className="sentinelflow-stack-item"><strong>误报</strong><span>{summary?.judgment.false_positive ?? 0} 条</span></div>
              <div className="sentinelflow-stack-item"><strong>真实攻击</strong><span>{summary?.judgment.true_attack ?? 0} 条</span></div>
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h3 className="mb-3 text-sm font-semibold text-gray-900">处置结果</h3>
            <div className="sentinelflow-stack-list">
              <div className="sentinelflow-stack-item"><strong>成功结单</strong><span>{summary?.operations.closed_success ?? 0} 条</span></div>
              <div className="sentinelflow-stack-item"><strong>成功处置</strong><span>{summary?.operations.disposed_success ?? 0} 条</span></div>
              <div className="sentinelflow-stack-item"><strong>封禁 IP</strong><span>{(summary?.operations.banned_ips ?? []).join('、') || '暂无'}</span></div>
            </div>
          </div>
        </div>
      </Surface>
    </div>
  )
}
