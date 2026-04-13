import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Siren } from 'lucide-react'
import {
  fetchDashboardSummary,
  fetchPollAlerts,
  handleAlertAction,
  type AlertActionResponse,
  type AlertTask,
  type PollAlertsResponse,
} from '@/api/sentinelflow'
import JsonPreview from '@/components/sentinelflow/JsonPreview'
import StatusBadge from '@/components/sentinelflow/StatusBadge'
import Surface from '@/components/sentinelflow/Surface'
import PageHeader from '@/components/common/PageHeader'
import { withProductName } from '@/config/brand'
import { publishRuntimeActivity } from '@/utils/sentinelflowRuntimeSync'
import { useSentinelFlowLiveRefresh } from '@/hooks/useSentinelFlowLiveRefresh'

function getDispositionLabel(value: string) {
  if (value === 'true_attack') return '真实攻击'
  if (value === 'business_trigger') return '业务触发'
  if (value === 'false_positive') return '误报'
  return value || '未明确'
}

function getTaskTone(task: AlertTask): 'neutral' | 'success' | 'warn' | 'danger' | 'info' {
  if (task.status === 'running') return 'info'
  if (task.status === 'queued') return 'warn'
  if (task.status === 'failed') return 'danger'
  if (task.status === 'succeeded' || task.status === 'completed') return 'success'
  return 'neutral'
}

function splitAlertIps(value: unknown): string[] {
  const text = String(value ?? '').trim()
  if (!text) return []
  return text
    .split(/[,\n，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function formatIpPreview(value: unknown): { text: string; fullText: string } {
  const ips = splitAlertIps(value)
  if (!ips.length) {
    const fallback = String(value ?? '').trim()
    return { text: fallback || '未提供', fullText: fallback || '未提供' }
  }
  if (ips.length <= 3) {
    const joined = ips.join(',')
    return { text: joined, fullText: joined }
  }
  return {
    text: `${ips.slice(0, 3).join(',')}...共${ips.length}个`,
    fullText: ips.join(','),
  }
}

function getTaskStatusClass(task: AlertTask): string {
  if (task.status === 'running') return 'running'
  if (task.status === 'queued') return 'queued'
  if (task.status === 'failed') return 'danger'
  if (task.status === 'succeeded' || task.status === 'completed') return 'success'
  return 'neutral'
}

function getTaskStatusLabel(task: AlertTask): string {
  if (task.status === 'queued') return '排队中'
  if (task.status === 'running') return '执行中'
  if (task.status === 'completed') return '已被人工处置'
  if (task.status === 'succeeded') return '已完成'
  if (task.status === 'failed') return '失败'
  return task.status
}

function toSortableTime(value: string | undefined): number {
  const text = String(value ?? '').trim()
  if (!text) return 0
  const normalized = text.includes('T') ? text : text.replace(' ', 'T')
  const timestamp = Date.parse(normalized)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

function formatAlertTime(value: string | undefined): string {
  const text = String(value ?? '').trim()
  return text || '未提供'
}

function getSelectedAlertPayload(task: AlertTask | null): Record<string, unknown> {
  return (task?.payload?.alert_data as Record<string, unknown> | undefined) ?? {}
}

export default function SentinelFlowAlertsPage() {
  const [data, setData] = useState<PollAlertsResponse | null>(null)
  const [summary, setSummary] = useState<{
    judgment: {
      business_trigger: number
      false_positive: number
      true_attack: number
      unknown: number
    }
    operations: {
      closed_success: number
      disposed_success: number
      manual_completed: number
      banned_ip_count: number
      banned_ips: string[]
    }
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [actionState, setActionState] = useState<{ action: string; running: boolean }>({ action: '', running: false })
  const [actionResult, setActionResult] = useState<AlertActionResponse | null>(null)
  const autoExecuteEnabled = Boolean(data?.auto_execute_enabled)
  const autoExecuteRunning = Boolean(data?.auto_execute_running)
  const liveRefreshing = autoExecuteEnabled || actionState.running || (data?.tasks ?? []).some((task) => task.status === 'running')

  const loadTasks = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false
    if (!silent) {
      setLoading(true)
      setError(null)
    }
    try {
      const result = await fetchPollAlerts()
      setData(result)
      if (!silent) {
        setLoading(false)
      }
      void fetchDashboardSummary()
        .then((dashboard) => {
          setSummary({
            judgment: dashboard.judgment,
            operations: dashboard.operations,
          })
        })
        .catch(() => {
          // Keep the queue responsive even if the summary request is slower.
        })
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unknown error')
      if (!silent) {
        setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    void loadTasks()
  }, [])

  useSentinelFlowLiveRefresh(
    () => loadTasks({ silent: true }),
    { intervalMs: liveRefreshing ? 2000 : 5000 },
  )

  const tasks = [...(data?.tasks ?? [])].sort((left, right) => toSortableTime(right.alert_time) - toSortableTime(left.alert_time))

  useEffect(() => {
    setSelectedTaskId((current) => {
      if (!tasks.length) return null
      if (current && tasks.some((task) => task.task_id === current)) return current
      return tasks[0]?.task_id ?? null
    })
  }, [tasks])

  const selectedTask = tasks.find((task) => task.task_id === selectedTaskId) ?? tasks[0] ?? null
  const selectedPayload = getSelectedAlertPayload(selectedTask)
  const workflowSelection = (selectedTask?.payload?.workflow_selection as Record<string, unknown> | undefined) ?? {}
  const selectedResult = (selectedTask?.last_result_data ?? {}) as Record<string, unknown>
  const selectedClosureStep = (selectedResult.closure_step as Record<string, unknown> | undefined) ?? {}
  const selectedReason = String(selectedResult.reason ?? '').trim()
  const selectedDisposition = String(selectedResult.disposition ?? '').trim()
  const selectedSummary = String(selectedResult.summary ?? '').trim()
  const selectedEvidence = Array.isArray(selectedResult.evidence)
    ? selectedResult.evidence.map((item) => String(item).trim()).filter(Boolean)
    : []
  const hideTaskError = Boolean(selectedClosureStep.attempted) && Boolean(selectedClosureStep.success)
  const dipPreview = formatIpPreview(selectedPayload.dip)
  const workflowDecision = String(workflowSelection.workflow_id ?? selectedTask?.workflow_name ?? '').trim()
  const workflowDecisionReason = String(workflowSelection.reason ?? '').trim()

  async function runAction(action: string) {
    setActionState({ action, running: true })
    void loadTasks({ silent: true })
    try {
      const result = action === 'refresh_poll' || action === 'auto_run_pending' || action === 'auto_execute_start' || action === 'auto_execute_stop'
        ? await handleAlertAction(action)
        : selectedTask
          ? await handleAlertAction(action, selectedTask)
          : null
      if (!result) return
      setActionResult(result)
      publishRuntimeActivity({
        type: 'alert_action',
        title: selectedTask ? `${selectedTask.title} / ${action}` : action,
        detail: result.success ? '动作执行完成。' : result.error ?? '动作执行失败。',
        success: result.success,
        timestamp: new Date().toISOString(),
      })
      await loadTasks()
    } catch (runError) {
      setActionResult({
        action,
        success: false,
        task_id: selectedTask?.task_id ?? '',
        event_ids: selectedTask?.event_ids ?? '',
        data: {},
        error: runError instanceof Error ? runError.message : 'Unknown error',
      })
    } finally {
      setActionState({ action: '', running: false })
    }
  }

  return (
    <div className="sentinelflow-page-stack">
      <PageHeader
        title="告警工作台"
        description="查看轮询结果并执行单条告警的研判、处置和闭环动作。"
        icon={<Siren className="w-8 h-8" />}
        action={
          <button type="button" className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700" onClick={() => void runAction('refresh_poll')} disabled={actionState.running}>
            <RefreshCw className="h-4 w-4" />
            重新轮询
          </button>
        }
      />

      <Surface title="告警工作台" subtitle={withProductName('这里直接承载 SentinelFlow 的轮询结果、单条动作和人工复核操作。')}>
        <div className="mb-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
            <div className="mb-2 text-sm font-semibold text-amber-900">业务触发</div>
            <div className="text-3xl font-bold text-amber-950">{summary?.judgment.business_trigger ?? 0}</div>
            <div className="mt-2 text-xs text-amber-800">已判定为业务原因触发的告警数量</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-5">
            <div className="mb-2 text-sm font-semibold text-slate-900">误报</div>
            <div className="text-3xl font-bold text-slate-950">{summary?.judgment.false_positive ?? 0}</div>
            <div className="mt-2 text-xs text-slate-700">已归类为误报的告警数量</div>
          </div>
          <div className="rounded-xl border border-red-200 bg-red-50 p-5">
            <div className="mb-2 text-sm font-semibold text-red-900">真实攻击</div>
            <div className="text-3xl font-bold text-red-950">{summary?.judgment.true_attack ?? 0}</div>
            <div className="mt-2 text-xs text-red-800">已识别为真实攻击的告警数量</div>
          </div>
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5">
            <div className="mb-2 text-sm font-semibold text-emerald-900">封禁 IP</div>
            <div className="text-3xl font-bold text-emerald-950">{summary?.operations.banned_ip_count ?? 0}</div>
            <div className="mt-2 text-xs text-emerald-800">已执行封禁动作并记录的 IP 数量</div>
          </div>
        </div>

        <div className="sentinelflow-toolbar-row mb-4">
          <div className="sentinelflow-inline-metrics">
            <span>拉取：{data?.fetched_count ?? 0}</span>
            <span>排队：{data?.queued_count ?? 0}</span>
            <span>更新：{data?.updated_count ?? 0}</span>
            <span>完成：{data?.completed_count ?? 0}</span>
            <span>跳过：{data?.skipped_count ?? 0}</span>
            <span>失败：{data?.failed_count ?? 0}</span>
            <span>自动执行：{autoExecuteEnabled ? (autoExecuteRunning ? '自动执行中' : '已开启') : '未开启'}</span>
            <span>已结单：{summary?.operations.closed_success ?? 0}</span>
            <span>已处置：{summary?.operations.disposed_success ?? 0}</span>
            <span>人工处置：{summary?.operations.manual_completed ?? 0}</span>
          </div>
          <button type="button" className="sentinelflow-ghost-button" onClick={() => void runAction('refresh_poll')} disabled={actionState.running}>重新轮询</button>
          <button
            type="button"
            className={autoExecuteEnabled ? 'sentinelflow-ghost-button' : 'sentinelflow-primary-button'}
            onClick={() => void runAction(autoExecuteEnabled ? 'auto_execute_stop' : 'auto_execute_start')}
            disabled={actionState.running}
          >
            {autoExecuteEnabled ? (autoExecuteRunning ? '自动执行中' : '停止自动执行') : '开始自动执行'}
          </button>
        </div>

        <div className="sentinelflow-grid-2">
          <div className="sentinelflow-detail-panel">
            <h3>告警队列</h3>
            <div className="sentinelflow-alert-queue-scroll">
              <table className="sentinelflow-data-table">
                <thead>
                  <tr><th>告警</th><th>告警时间</th><th>状态</th><th>流转</th></tr>
                </thead>
                <tbody>
                  {loading ? <tr><td colSpan={4}>正在加载...</td></tr> : null}
                  {error ? <tr><td colSpan={4}>加载失败：{error}</td></tr> : null}
                  {!loading && !error && tasks.length === 0 ? <tr><td colSpan={4}>当前没有新的待处理告警任务。</td></tr> : null}
                  {!loading && !error ? tasks.map((task) => (
                    <tr
                      key={task.task_id}
                      className={[
                        selectedTask?.task_id === task.task_id ? 'sentinelflow-table-row-active' : '',
                        `sentinelflow-table-row-${getTaskStatusClass(task)}`,
                      ].filter(Boolean).join(' ')}
                      onClick={() => setSelectedTaskId(task.task_id)}
                    >
                      <td>{task.title || '未命名告警'}</td>
                      <td>{formatAlertTime(task.alert_time)}</td>
                      <td><StatusBadge tone={getTaskTone(task)}>{getTaskStatusLabel(task)}</StatusBadge></td>
                      <td>{task.workflow_name}</td>
                    </tr>
                  )) : null}
                </tbody>
              </table>
            </div>
          </div>

          <div className={`sentinelflow-detail-panel sentinelflow-detail-panel-${selectedTask ? getTaskStatusClass(selectedTask) : 'neutral'}`}>
            <h3>当前选中告警</h3>
            {selectedTask ? (
              <div className="sentinelflow-response-stack">
                <div className="sentinelflow-response-row">
                  <StatusBadge tone={getTaskTone(selectedTask)}>{getTaskStatusLabel(selectedTask)}</StatusBadge>
                  <span>{formatAlertTime(selectedTask.alert_time)}</span>
                  <span>{selectedTask.workflow_name}</span>
                </div>
                <p className="sentinelflow-muted-text">{selectedTask.description}</p>
                <div className="sentinelflow-context-grid">
                  <div className="sentinelflow-context-card"><strong>告警名称</strong><span>{String(selectedPayload.alert_name ?? selectedTask.title ?? '未提供')}</span></div>
                  <div className="sentinelflow-context-card"><strong>告警时间</strong><span>{formatAlertTime(selectedTask.alert_time)}</span></div>
                  <div className="sentinelflow-context-card"><strong>事件号</strong><span>{selectedTask.event_ids || '未提供'}</span></div>
                  <div className="sentinelflow-context-card"><strong>来源</strong><span>{String(selectedPayload.alert_source ?? '未提供')}</span></div>
                  <div className="sentinelflow-context-card"><strong>源 IP</strong><span>{String(selectedPayload.sip ?? '未提供')}</span></div>
                  <div className="sentinelflow-context-card"><strong>目的 IP</strong><span title={dipPreview.fullText}>{dipPreview.text}</span></div>
                  <div className="sentinelflow-context-card"><strong>当前研判</strong><span>{String(selectedPayload.current_judgment ?? '未提供')}</span></div>
                  <div className="sentinelflow-context-card"><strong>历史研判</strong><span>{String(selectedPayload.history_judgment ?? '未提供')}</span></div>
                </div>
                {String(selectedPayload.payload ?? '').trim() ? (
                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                    <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">告警 Payload</div>
                    <pre className="overflow-x-auto whitespace-pre-wrap text-xs leading-6 text-slate-700">{String(selectedPayload.payload ?? '')}</pre>
                  </div>
                ) : null}
                <div className="sentinelflow-action-bar">
                  <button type="button" className="sentinelflow-primary-button" onClick={() => void runAction('triage_dispose')} disabled={actionState.running}>处置当前告警</button>
                  {selectedTask.status === 'failed' ? (
                    <button type="button" className="sentinelflow-ghost-button" onClick={() => void runAction('retry_task')} disabled={actionState.running}>重试任务</button>
                  ) : null}
                </div>
                {workflowDecision ? (
                  <div className="rounded-xl border border-amber-100 bg-amber-50 p-4">
                    <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Workflow 决策</div>
                    <div className="mt-2 text-sm font-semibold text-amber-950">命中流程：{workflowDecision}</div>
                    {workflowDecisionReason ? <div className="mt-2 text-sm text-amber-900">主 Agent 理由：{workflowDecisionReason}</div> : null}
                  </div>
                ) : null}
                {selectedDisposition || selectedReason || selectedSummary ? (
                  <div className="rounded-xl border border-blue-100 bg-blue-50 p-4">
                    <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">最终研判</div>
                    <div className="mt-2 text-sm font-semibold text-blue-950">
                      {`分类：${getDispositionLabel(selectedDisposition)}`}
                    </div>
                    {selectedSummary ? <div className="mt-2 text-sm text-blue-900">结论：{selectedSummary}</div> : null}
                    {selectedReason ? <div className="mt-2 text-sm text-blue-900">理由：{selectedReason}</div> : null}
                    {selectedEvidence.length ? (
                      <div className="mt-3">
                        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">关键依据</div>
                        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-blue-900">
                          {selectedEvidence.map((item, index) => (
                            <li key={`${selectedTask.task_id}-evidence-${index}`}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {selectedTask.last_result_error && !hideTaskError ? <div className="sentinelflow-message-block sentinelflow-message-error">{selectedTask.last_result_error}</div> : null}
              </div>
            ) : (
              <p className="sentinelflow-muted-text">选择一条告警后查看详情。</p>
            )}
          </div>
        </div>
      </Surface>

      <Surface title="研判与封禁摘要" subtitle="把业务触发、误报、真实攻击和封禁结果直接展示到告警工作台，便于值班时快速判断当前态势。">
        <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-3 text-sm font-semibold text-gray-900">研判结果概览</div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                <div className="text-xs text-amber-800">业务触发</div>
                <div className="mt-1 text-2xl font-bold text-amber-950">{summary?.judgment.business_trigger ?? 0}</div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="text-xs text-slate-700">误报</div>
                <div className="mt-1 text-2xl font-bold text-slate-950">{summary?.judgment.false_positive ?? 0}</div>
              </div>
              <div className="rounded-lg border border-red-200 bg-red-50 p-4">
                <div className="text-xs text-red-800">真实攻击</div>
                <div className="mt-1 text-2xl font-bold text-red-950">{summary?.judgment.true_attack ?? 0}</div>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                <div className="text-xs text-gray-700">未明确分类</div>
                <div className="mt-1 text-2xl font-bold text-gray-950">{summary?.judgment.unknown ?? 0}</div>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-3 text-sm font-semibold text-gray-900">封禁与处置</div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
                <div className="text-xs text-emerald-800">封禁 IP 数</div>
                <div className="mt-1 text-2xl font-bold text-emerald-950">{summary?.operations.banned_ip_count ?? 0}</div>
              </div>
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                <div className="text-xs text-blue-800">成功处置</div>
                <div className="mt-1 text-2xl font-bold text-blue-950">{summary?.operations.disposed_success ?? 0}</div>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                <div className="text-xs text-amber-800">人工处置</div>
                <div className="mt-1 text-2xl font-bold text-amber-950">{summary?.operations.manual_completed ?? 0}</div>
              </div>
            </div>
            <div className="mt-4">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">已封禁 IP</div>
              <div className="sentinelflow-quick-actions">
                {(summary?.operations.banned_ips ?? []).length > 0 ? (
                  (summary?.operations.banned_ips ?? []).map((ip) => (
                    <span key={ip} className="sentinelflow-chip-button sentinelflow-chip-button-active">{ip}</span>
                  ))
                ) : (
                  <span className="sentinelflow-muted-text">当前还没有封禁记录。</span>
                )}
              </div>
            </div>
          </div>
        </div>
      </Surface>

      <Surface title="动作结果" subtitle="保留结构化回执，便于在值班场景里快速确认执行状态。">
        {actionResult ? <JsonPreview value={actionResult} /> : <p className="sentinelflow-muted-text">执行动作后，这里会显示结构化回执。</p>}
      </Surface>
    </div>
  )
}
