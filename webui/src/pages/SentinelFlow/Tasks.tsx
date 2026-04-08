import { useEffect, useMemo, useState } from 'react'
import { Clock, ListTodo, RotateCcw, ShieldCheck, XCircle } from 'lucide-react'
import { fetchAuditEvents, fetchPollAlerts, fetchRuntimeSettings, handleAlertAction, type AlertActionResponse, type AlertTask } from '@/api/sentinelflow'
import JsonPreview from '@/components/sentinelflow/JsonPreview'
import Surface from '@/components/sentinelflow/Surface'
import StatusBadge from '@/components/sentinelflow/StatusBadge'
import PageHeader from '@/components/common/PageHeader'
import { withProductName } from '@/config/brand'
import { useSentinelFlowAsyncData } from '@/hooks/useSentinelFlowAsyncData'
import { readSessionValue, writeSessionValue } from '@/utils/sentinelflowLocalState'
import { publishRuntimeActivity, readRuntimeActivity, subscribeRuntimeActivity, type RuntimeActivity } from '@/utils/sentinelflowRuntimeSync'

type TaskFilter = 'all' | 'queued' | 'running' | 'succeeded' | 'completed' | 'failed'
const TASK_FILTER_KEY = 'sentinelflow:tasks:filter'

const TASK_FILTER_LABELS: Record<TaskFilter, string> = {
  all: '全部',
  queued: '排队中',
  running: '执行中',
  succeeded: '已完成',
  completed: '已完成',
  failed: '失败',
}

function getTaskStatusLabel(status: TaskFilter | AlertTask['status']) {
  if (status === 'queued') return '排队中'
  if (status === 'running') return '执行中'
  if (status === 'succeeded') return '已完成'
  if (status === 'completed') return '已被人工处置'
  if (status === 'failed') return '失败'
  return '全部'
}

function getDispositionLabel(value: string) {
  if (value === 'true_attack') return '真实攻击'
  if (value === 'business_trigger') return '业务触发'
  if (value === 'false_positive') return '误报'
  return value || '未明确'
}

function getTone(task: AlertTask): 'neutral' | 'success' | 'warn' | 'danger' {
  if (task.status === 'succeeded') return 'success'
  if (task.status === 'completed') return 'success'
  if (task.status === 'failed') return 'danger'
  if (task.status === 'running') return 'warn'
  return 'neutral'
}

export default function SentinelFlowTasksPage() {
  const { data: poll, loading, error, reload: reloadPoll } = useSentinelFlowAsyncData(fetchPollAlerts, [])
  const { data: audit, reload: reloadAudit } = useSentinelFlowAsyncData(fetchAuditEvents, [])
  const { data: settings } = useSentinelFlowAsyncData(fetchRuntimeSettings, [])
  const [activity, setActivity] = useState<RuntimeActivity | null>(() => readRuntimeActivity())
  const [bulkResult, setBulkResult] = useState<AlertActionResponse | null>(null)
  const [runningAction, setRunningAction] = useState('')
  const [filter, setFilter] = useState<TaskFilter>(() => readSessionValue<TaskFilter>(TASK_FILTER_KEY, 'all'))
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const tasks = poll?.tasks ?? []

  useEffect(() => {
    writeSessionValue(TASK_FILTER_KEY, filter)
  }, [filter])

  useEffect(() => {
    return subscribeRuntimeActivity((next) => {
      setActivity(next)
      void reloadPoll()
      void reloadAudit()
    })
  }, [reloadAudit, reloadPoll])

  useEffect(() => {
    setSelectedTaskId((current) => current ?? tasks[0]?.task_id ?? null)
  }, [tasks])

  const filteredTasks = useMemo(() => (filter === 'all' ? tasks : tasks.filter((task) => task.status === filter)), [filter, tasks])
  const failedTasks = tasks.filter((task) => task.status === 'failed')
  const selectedTask =
    filteredTasks.find((task) => task.task_id === selectedTaskId) ??
    tasks.find((task) => task.task_id === selectedTaskId) ??
    filteredTasks[0] ??
    tasks[0] ??
    null

  async function handleRunPending() {
    setRunningAction('auto_run_pending')
    try {
      const result = await handleAlertAction('auto_run_pending')
      setBulkResult(result)
      const next: RuntimeActivity = {
        type: 'alert_action',
        title: '自动执行待处理任务',
        detail: result.success ? `已执行 ${result.data.count ?? 0} 条待处理任务。` : result.error ?? '自动执行失败。',
        success: result.success,
        timestamp: new Date().toISOString(),
      }
      setActivity(next)
      publishRuntimeActivity(next)
      void reloadPoll()
      void reloadAudit()
    } finally {
      setRunningAction('')
    }
  }

  async function handleRetry(task: AlertTask) {
    setRunningAction(task.task_id)
    try {
      const result = await handleAlertAction('retry_task', task)
      setBulkResult(result)
      const next: RuntimeActivity = {
        type: 'alert_action',
        title: `${task.title} / retry`,
        detail: result.success ? '任务重试完成。' : result.error ?? '任务重试失败。',
        success: result.success,
        timestamp: new Date().toISOString(),
      }
      setActivity(next)
      publishRuntimeActivity(next)
      void reloadPoll()
      void reloadAudit()
    } finally {
      setRunningAction('')
    }
  }

  const selectedPayload = (selectedTask?.payload?.alert_data as Record<string, unknown> | undefined) ?? {}
  const workflowSelection = (selectedTask?.payload?.workflow_selection as Record<string, unknown> | undefined) ?? {}
  const selectedResult = (selectedTask?.last_result_data ?? {}) as Record<string, unknown>
  const selectedReason = String(selectedResult.reason ?? '').trim()
  const selectedDisposition = String(selectedResult.disposition ?? '').trim()
  const selectedSummary = String(selectedResult.summary ?? '').trim()
  const selectedEvidence = Array.isArray(selectedResult.evidence)
    ? selectedResult.evidence.map((item) => String(item).trim()).filter(Boolean)
    : []
  const workflowDecision = String(workflowSelection.workflow_id ?? selectedTask?.workflow_name ?? '').trim()
  const workflowDecisionReason = String(workflowSelection.reason ?? '').trim()

  return (
    <div className="sentinelflow-page-stack">
      <PageHeader
        title="任务中心"
        description="按状态查看任务流转、失败聚合、重试动作和最近审计。"
        icon={<ListTodo className="w-8 h-8" />}
        action={
          <button type="button" className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700" onClick={() => void handleRunPending()} disabled={runningAction !== ''}>
            <RotateCcw className="h-4 w-4" />
            自动执行待处理
          </button>
        }
      />

      <Surface title="任务中心" subtitle={withProductName('展示任务从排队、执行到闭环的完整生命周期。已知模式优先走 Agent Workflow，复杂或未知任务则回到主 Agent 的 Agent ReAct。')}>
        <div className="grid gap-4 md:grid-cols-4">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-gray-500">排队中</span>
              <Clock className="h-4 w-4 text-amber-500" />
            </div>
            <div className="text-3xl font-bold text-gray-900">{tasks.filter((task) => task.status === 'queued').length}</div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-gray-500">执行中</span>
              <RotateCcw className="h-4 w-4 text-sky-500" />
            </div>
            <div className="text-3xl font-bold text-gray-900">{tasks.filter((task) => task.status === 'running').length}</div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-gray-500">已完成</span>
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
            </div>
            <div className="text-3xl font-bold text-gray-900">{tasks.filter((task) => task.status === 'succeeded' || task.status === 'completed').length}</div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-gray-500">失败</span>
              <XCircle className="h-4 w-4 text-red-500" />
            </div>
            <div className="text-3xl font-bold text-gray-900">{failedTasks.length}</div>
          </div>
        </div>

        <div className="mt-4 mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-1 rounded-lg bg-gray-100 p-1">
            {(['all', 'queued', 'running', 'succeeded', 'completed', 'failed'] as TaskFilter[]).map((item) => (
              <button key={item} type="button" className={`px-4 py-2 text-sm rounded-md transition-colors ${filter === item ? 'bg-white text-slate-800 shadow-sm font-medium' : 'text-gray-600 hover:text-gray-900'}`} onClick={() => setFilter(item)}>
                {TASK_FILTER_LABELS[item]}
              </button>
            ))}
          </div>
          <div className="sentinelflow-inline-metrics">
            <span>mode: {settings?.runtime.agent_enabled ? 'Agent' : 'Basic'}</span>
            <button type="button" className="sentinelflow-ghost-button" onClick={() => void Promise.all([reloadPoll(), reloadAudit()])}>刷新任务视图</button>
          </div>
        </div>

        {activity ? (
          <div className="sentinelflow-activity-banner">
            <div className="sentinelflow-activity-banner-header">
              <StatusBadge tone={activity.success ? 'success' : 'warn'}>{activity.success ? '最新动作成功' : '最新动作失败'}</StatusBadge>
              <span>{new Date(activity.timestamp).toLocaleString()}</span>
            </div>
            <strong>{activity.title}</strong>
            <p className="sentinelflow-muted-text">{activity.detail}</p>
          </div>
        ) : null}
      </Surface>

      <Surface title="任务工作面" subtitle="支持状态筛选、失败聚合、单条详情和重试动作。">
        {loading ? <p className="sentinelflow-muted-text">正在读取任务分发结果...</p> : null}
        {error ? <div className="sentinelflow-message-block sentinelflow-message-error">{error}</div> : null}
        {!loading && !error ? (
          <>
            <div className="sentinelflow-grid-2">
              <div className="sentinelflow-detail-panel">
                <h3>筛选结果</h3>
                <div className="sentinelflow-task-list">
                  {filteredTasks.map((task) => (
                    <button key={task.task_id} type="button" className={`sentinelflow-task-tile${selectedTask?.task_id === task.task_id ? ' sentinelflow-task-tile-active' : ''}`} onClick={() => setSelectedTaskId(task.task_id)}>
                      <div className="sentinelflow-response-row">
                        <strong>{task.title}</strong>
                        <StatusBadge tone={getTone(task)}>{getTaskStatusLabel(task.status)}</StatusBadge>
                      </div>
                      <span>{task.workflow_name}</span>
                      <span>{task.event_ids}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="sentinelflow-detail-panel">
                <h3>失败任务</h3>
                {failedTasks.length === 0 ? <p className="sentinelflow-muted-text">当前没有失败任务。</p> : failedTasks.map((task) => (
                  <div key={task.task_id} className="sentinelflow-task-tile sentinelflow-task-tile-failed">
                    <div className="sentinelflow-response-row">
                      <strong>{task.title}</strong>
                      <StatusBadge tone="danger">失败</StatusBadge>
                    </div>
                    <span>{task.last_result_error || '无详细错误信息'}</span>
                    <button type="button" className="sentinelflow-ghost-button" onClick={() => void handleRetry(task)} disabled={runningAction !== ''}>
                      {runningAction === task.task_id ? '重试中...' : '重试任务'}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </>
        ) : null}
      </Surface>

      <div className="sentinelflow-grid-2">
        <Surface title="任务详情" subtitle="卡片化显示选中任务的告警上下文和最近结果。">
          {selectedTask ? (
            <div className="sentinelflow-response-stack">
              <div className="sentinelflow-response-row">
                <StatusBadge tone={getTone(selectedTask)}>{getTaskStatusLabel(selectedTask.status)}</StatusBadge>
                <span>{selectedTask.event_ids}</span>
                <span>{selectedTask.workflow_name}</span>
              </div>
              <p className="sentinelflow-muted-text">{selectedTask.description}</p>
              <div className="sentinelflow-context-grid">
                <div className="sentinelflow-context-card"><strong>告警名称</strong><span>{String(selectedPayload.alert_name ?? '未提供')}</span></div>
                <div className="sentinelflow-context-card"><strong>源 IP</strong><span>{String(selectedPayload.sip ?? '未提供')}</span></div>
                <div className="sentinelflow-context-card"><strong>目标 IP</strong><span>{String(selectedPayload.dip ?? '未提供')}</span></div>
                <div className="sentinelflow-context-card"><strong>当前研判</strong><span>{String(selectedPayload.current_judgment ?? '未提供')}</span></div>
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
              {selectedTask.last_result_error ? <div className="sentinelflow-message-block sentinelflow-message-error">{selectedTask.last_result_error}</div> : null}
              {Object.keys(selectedTask.last_result_data ?? {}).length ? <JsonPreview value={selectedTask.last_result_data} /> : <p className="sentinelflow-muted-text">当前还没有最近一次执行结果详情。</p>}
            </div>
          ) : <p className="sentinelflow-muted-text">选择一条任务后查看详情。</p>}
        </Surface>

        <Surface title="审计与批量结果" subtitle="这里收口最近审计动静与批量执行结果。">
          {bulkResult ? <JsonPreview value={bulkResult} /> : <p className="sentinelflow-muted-text">执行自动处理或重试任务后，这里会显示结构化结果。</p>}
          <div className="sentinelflow-divider" />
          <div className="sentinelflow-stack-list">
            {(audit?.events ?? []).slice(-5).reverse().map((event) => (
              <div key={`${event.event_type}-${event.created_at}`} className="sentinelflow-stack-item">
                <strong>{event.event_type}</strong>
                <span>{event.message}</span>
              </div>
            ))}
          </div>
        </Surface>
      </div>
    </div>
  )
}
