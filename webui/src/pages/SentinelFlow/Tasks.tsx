import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Clock, ListTodo, RotateCcw, ShieldCheck, XCircle } from 'lucide-react'
import {
  fetchPollAlerts,
  fetchRuntimeSettings,
  handleAlertAction,
  type AlertTask,
  type ExecutionTraceItem,
} from '@/api/sentinelflow'
import JsonPreview from '@/components/sentinelflow/JsonPreview'
import Surface from '@/components/sentinelflow/Surface'
import StatusBadge from '@/components/sentinelflow/StatusBadge'
import PageHeader from '@/components/common/PageHeader'
import { withProductName } from '@/config/brand'
import { useSentinelFlowAsyncData } from '@/hooks/useSentinelFlowAsyncData'
import { useSentinelFlowLiveRefresh } from '@/hooks/useSentinelFlowLiveRefresh'
import { readSessionValue, writeSessionValue } from '@/utils/sentinelflowLocalState'
import { publishRuntimeActivity, readRuntimeActivity, subscribeRuntimeActivity, type RuntimeActivity } from '@/utils/sentinelflowRuntimeSync'

type TaskFilter = 'all' | 'queued' | 'running' | 'succeeded' | 'completed' | 'failed'
const TASK_FILTER_KEY = 'sentinelflow:tasks:filter'

const TASK_FILTER_LABELS: Record<TaskFilter, string> = {
  all: '全部',
  queued: '排队中',
  running: '执行中',
  succeeded: '已完成',
  completed: '已被人工处置',
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

function splitAlertIps(value: unknown): string[] {
  const text = String(value ?? '').trim()
  if (!text) return []
  return text
    .split(/[,\n，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function formatIpPreview(value: unknown, limit = 4): { text: string; fullText: string } {
  const ips = splitAlertIps(value)
  if (!ips.length) {
    const fallback = String(value ?? '').trim()
    return { text: fallback || '未提供', fullText: fallback || '未提供' }
  }
  if (ips.length <= limit) {
    const joined = ips.join(',')
    return { text: joined, fullText: joined }
  }
  return {
    text: `${ips.slice(0, limit).join(',')}...共${ips.length}个`,
    fullText: ips.join(','),
  }
}

function getTone(task: AlertTask): 'neutral' | 'success' | 'warn' | 'danger' {
  if (task.status === 'succeeded' || task.status === 'completed') return 'success'
  if (task.status === 'failed') return 'danger'
  if (task.status === 'running') return 'warn'
  return 'neutral'
}

function toSortableTime(value: string | undefined) {
  const text = String(value ?? '').trim()
  if (!text) return 0
  const timestamp = Date.parse(text.replace(' ', 'T'))
  return Number.isNaN(timestamp) ? 0 : timestamp
}

function getTraceTone(item: ExecutionTraceItem): 'success' | 'danger' | 'warn' | 'info' {
  if (item.success === true) return 'success'
  if (item.success === false) return 'danger'
  if (item.phase === 'skill_runs' || item.phase === 'actions') return 'info'
  return 'warn'
}

function buildFallbackTrace(task: AlertTask | null): ExecutionTraceItem[] {
  if (!task) return []
  const payload = (task.payload?.alert_data as Record<string, unknown> | undefined) ?? {}
  const workflowSelection = (task.payload?.workflow_selection as Record<string, unknown> | undefined) ?? {}
  const trace: ExecutionTraceItem[] = [
    {
      phase: 'alert_received',
      title: '接收告警',
      summary: '已接收任务告警上下文。',
      success: true,
      data: {
        eventIds: task.event_ids,
        alert_name: String(payload.alert_name ?? task.title ?? '').trim(),
        sip: payload.sip ?? '',
        dip: payload.dip ?? '',
        alert_time: payload.alert_time ?? task.alert_time ?? '',
        current_judgment: payload.current_judgment ?? '',
        history_judgment: payload.history_judgment ?? '',
        payload: payload.payload ?? '',
      },
    },
  ]
  if (Object.keys(workflowSelection).length) {
    trace.push({
      phase: 'workflow_selection',
      title: 'Workflow 记录',
      summary: String(workflowSelection.reason ?? workflowSelection.workflow_id ?? '存在历史 Workflow 记录。').trim(),
      success: true,
      data: workflowSelection,
    })
  }
  if (task.status === 'queued') {
    trace.push({
      phase: 'final_status',
      title: '当前执行状态',
      summary: '任务已进入排队中，等待自动执行或人工处置。',
      success: null,
      data: {
        status: 'queued',
        success: null,
      },
    })
  } else if (task.status === 'running') {
    trace.push({
      phase: 'final_status',
      title: '当前执行状态',
      summary: '任务正在执行中，请等待最新结果刷新。',
      success: null,
      data: {
        status: 'running',
        success: null,
      },
    })
  }
  return trace
}

function normalizeWorkflowRuns(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
}

function getTaskFlowLabel(task: AlertTask): string {
  const result = (task.last_result_data ?? {}) as Record<string, unknown>
  const workflowRuns = normalizeWorkflowRuns(result.workflow_runs)
  const workflowRun = workflowRuns[0] ?? null
  if (workflowRun) {
    return `Workflow / ${String(workflowRun.workflow_name ?? workflowRun.workflow_id ?? '未命名流程').trim() || '未命名流程'}`
  }
  const workflowName = String(task.workflow_name ?? '').trim()
  if (!workflowName || workflowName === 'agent_react') return '主 Agent'
  return workflowName
}

function ProcessTrace({ trace, traceOwnerId }: { trace: ExecutionTraceItem[]; traceOwnerId: string }) {
  const [openKeys, setOpenKeys] = useState<Record<string, boolean>>({})

  useEffect(() => {
    setOpenKeys({})
  }, [traceOwnerId])

  if (!trace.length) {
    return <p className="sentinelflow-muted-text">该任务生成于旧版本，暂无完整处置全流程明细。</p>
  }

  return (
    <div className="space-y-3">
      {trace.map((item, index) => {
        const detailKey = `${item.phase}-${index}`
        const open = Boolean(openKeys[detailKey])
        const data = item.data && Object.keys(item.data).length ? item.data : null
        return (
          <div key={detailKey} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">步骤 {index + 1}</span>
                  <StatusBadge tone={getTraceTone(item)}>{item.title}</StatusBadge>
                </div>
                {item.summary ? <p className="text-sm text-gray-700">{item.summary}</p> : null}
              </div>
              {data ? (
                <button
                  type="button"
                  className="sentinelflow-ghost-button shrink-0"
                  onClick={() => setOpenKeys((current) => ({ ...current, [detailKey]: !open }))}
                >
                  {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  {open ? '收起详情' : '展开详情'}
                </button>
              ) : null}
            </div>
            {open && data ? (
              <div className="mt-3">
                <JsonPreview value={data} />
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

export default function SentinelFlowTasksPage() {
  const { data: poll, loading, error, reload: reloadPoll, setData: setPollData } = useSentinelFlowAsyncData(fetchPollAlerts, [])
  const { data: settings } = useSentinelFlowAsyncData(fetchRuntimeSettings, [])
  const [activity, setActivity] = useState<RuntimeActivity | null>(() => readRuntimeActivity())
  const [runningAction, setRunningAction] = useState('')
  const [filter, setFilter] = useState<TaskFilter>(() => readSessionValue<TaskFilter>(TASK_FILTER_KEY, 'all'))
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [processExpanded, setProcessExpanded] = useState(false)
  const taskListPanelRef = useRef<HTMLDivElement | null>(null)
  const detailPanelRef = useRef<HTMLDivElement | null>(null)
  const [taskListPanelHeight, setTaskListPanelHeight] = useState<number | null>(null)
  const [taskListMaxHeight, setTaskListMaxHeight] = useState<number | null>(null)
  const tasks = poll?.tasks ?? []
  const autoExecuteEnabled = Boolean(poll?.auto_execute_enabled)
  const autoExecuteRunning = Boolean(poll?.auto_execute_running)

  useEffect(() => {
    writeSessionValue(TASK_FILTER_KEY, filter)
  }, [filter])

  useEffect(() => {
    return subscribeRuntimeActivity((next) => {
      setActivity(next)
      void reloadPoll()
    })
  }, [reloadPoll])

  const filteredTasks = useMemo(() => {
    const base = filter === 'all' ? tasks : tasks.filter((task) => task.status === filter)
    return [...base].sort((left, right) => toSortableTime(right.alert_time) - toSortableTime(left.alert_time))
  }, [filter, tasks])

  useEffect(() => {
    setSelectedTaskId((current) => {
      if (!filteredTasks.length) return null
      if (current && filteredTasks.some((task) => task.task_id === current)) return current
      return filteredTasks[0]?.task_id ?? null
    })
  }, [filteredTasks])

  useEffect(() => {
    setProcessExpanded(false)
  }, [selectedTaskId])

  const selectedTask =
    filteredTasks.find((task) => task.task_id === selectedTaskId) ??
    filteredTasks[0] ??
    null

  useEffect(() => {
    const detailNode = detailPanelRef.current
    const listPanelNode = taskListPanelRef.current
    if (!detailNode || !listPanelNode || typeof ResizeObserver === 'undefined') return

    const syncHeight = () => {
      try {
        const detailHeight = Math.max(0, Math.round(detailNode.getBoundingClientRect().height))
        const scrollNode = listPanelNode.querySelector('.sentinelflow-task-list-scroll') as HTMLDivElement | null
        const scrollHeight = scrollNode?.clientHeight ?? 0
        const chromeHeight = Math.max(
          0,
          Math.round(listPanelNode.scrollHeight - scrollHeight),
        )
        const nextHeight = Math.max(0, detailHeight - chromeHeight)
        setTaskListPanelHeight(detailHeight || null)
        setTaskListMaxHeight(nextHeight || null)
      } catch {
        setTaskListPanelHeight(null)
        setTaskListMaxHeight(null)
      }
    }

    try {
      syncHeight()
      const observer = new ResizeObserver(() => syncHeight())
      observer.observe(detailNode)
      observer.observe(listPanelNode)
      return () => observer.disconnect()
    } catch {
      setTaskListPanelHeight(null)
      setTaskListMaxHeight(null)
      return
    }
  }, [selectedTaskId, processExpanded, filteredTasks.length, selectedTask?.task_id, selectedTask?.status])

  const refreshTasks = useCallback(() => {
    void fetchPollAlerts().then((next) => {
      setPollData(next)
    })
  }, [setPollData])

  useSentinelFlowLiveRefresh(refreshTasks, {
    intervalMs: autoExecuteEnabled || tasks.some((task) => task.status === 'running') ? 2000 : 5000,
  })

  async function handleAutoExecuteToggle() {
    const action = autoExecuteEnabled ? 'auto_execute_stop' : 'auto_execute_start'
    setRunningAction(action)
    try {
      const result = await handleAlertAction(action)
      const next: RuntimeActivity = {
        type: 'alert_action',
        title: autoExecuteEnabled ? '停止自动执行' : '开始自动执行',
        detail: result.success ? (autoExecuteEnabled ? '后台自动执行已停止。' : '后台自动执行已开启。') : result.error ?? '自动执行失败。',
        success: result.success,
        timestamp: new Date().toISOString(),
      }
      setActivity(next)
      publishRuntimeActivity(next)
      void reloadPoll()
    } finally {
      setRunningAction('')
    }
  }

  async function handleRetry(task: AlertTask) {
    setRunningAction(task.task_id)
    try {
      const result = await handleAlertAction('retry_task', task)
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
    } finally {
      setRunningAction('')
    }
  }

  const selectedPayload = (selectedTask?.payload?.alert_data as Record<string, unknown> | undefined) ?? {}
  const selectedResult = selectedTask?.last_result_data ?? {}
  const selectedWorkflowRuns = normalizeWorkflowRuns(selectedResult.workflow_runs)
  const selectedWorkflowRun = selectedWorkflowRuns[0] ?? null
  const selectedWorkflowSelection =
    (selectedResult.workflow_selection as Record<string, unknown> | undefined) ??
    (selectedTask?.payload?.workflow_selection as Record<string, unknown> | undefined) ??
    {}
  const selectedClosureStep = (
    (selectedResult.effective_closure_step as Record<string, unknown> | undefined)
    ?? (selectedResult.closure_step as Record<string, unknown> | undefined)
  ) ?? {}
  const selectedReason = String(selectedResult.reason ?? '').trim()
  const selectedDisposition = String(selectedResult.disposition ?? '').trim()
  const selectedSummary = String(selectedResult.summary ?? '').trim()
  const selectedEvidence = Array.isArray(selectedResult.evidence)
    ? selectedResult.evidence.map((item) => String(item).trim()).filter(Boolean)
    : []
  const hideTaskError = Boolean(selectedClosureStep.attempted) && Boolean(selectedClosureStep.success)
  const selectedTrace = Array.isArray(selectedResult.execution_trace) && selectedResult.execution_trace.length
    ? (selectedResult.execution_trace as ExecutionTraceItem[])
    : buildFallbackTrace(selectedTask)
  const dipPreview = formatIpPreview(selectedPayload.dip, 4)
  const workflowDecision = String(
    selectedWorkflowRun?.workflow_name ?? selectedWorkflowRun?.workflow_id ?? selectedTask?.workflow_name ?? '',
  ).trim()
  const workflowDecisionReason = String(
    selectedWorkflowRun?.summary ?? selectedWorkflowRun?.reason ?? selectedWorkflowSelection.reason ?? '',
  ).trim()

  return (
    <div className="sentinelflow-page-stack">
      <PageHeader
        title="任务中心"
        description="按状态查看任务流转、执行细节和完整处置链路。"
        icon={<ListTodo className="w-8 h-8" />}
        action={
          <button
            type="button"
            className={`flex items-center gap-2 rounded-lg px-4 py-2 transition-colors ${autoExecuteEnabled ? 'border border-red-200 bg-white text-red-600 hover:bg-red-50' : 'bg-red-600 text-white hover:bg-red-700'}`}
            onClick={() => void handleAutoExecuteToggle()}
            disabled={runningAction !== ''}
          >
            <RotateCcw className="h-4 w-4" />
            {autoExecuteEnabled ? (autoExecuteRunning ? '自动执行中' : '停止自动执行') : '开始自动执行'}
          </button>
        }
      />

      <Surface title="任务中心" subtitle={withProductName('展示任务从排队、执行到闭环的完整生命周期。当前由主 Agent 统一统筹，可按需调用子 Agent、Workflow 与技能。')}>
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
            <div className="text-3xl font-bold text-gray-900">{tasks.filter((task) => task.status === 'failed').length}</div>
          </div>
        </div>

        <div className="mb-4 mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-1 rounded-lg bg-gray-100 p-1">
            {(['all', 'queued', 'running', 'succeeded', 'completed', 'failed'] as TaskFilter[]).map((item) => (
              <button key={item} type="button" className={`rounded-md px-4 py-2 text-sm transition-colors ${filter === item ? 'bg-white font-medium text-slate-800 shadow-sm' : 'text-gray-600 hover:text-gray-900'}`} onClick={() => setFilter(item)}>
                {TASK_FILTER_LABELS[item]}
              </button>
            ))}
          </div>
          <div className="sentinelflow-inline-metrics">
            <span>mode: {settings?.runtime.agent_enabled ? 'Agent' : 'Basic'}</span>
            <span>自动执行: {autoExecuteEnabled ? (autoExecuteRunning ? '自动执行中' : '已开启') : '未开启'}</span>
            <button type="button" className="sentinelflow-ghost-button" onClick={() => void reloadPoll()}>刷新任务视图</button>
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

      <Surface title="任务工作面" subtitle="左侧选择任务，右侧查看详情与完整处置全流程。">
        {loading ? <p className="sentinelflow-muted-text">正在读取任务分发结果...</p> : null}
        {error ? <div className="sentinelflow-message-block sentinelflow-message-error">{error}</div> : null}
        {!loading && !error ? (
          <div className="sentinelflow-grid-2">
            <div
              ref={taskListPanelRef}
              className="sentinelflow-detail-panel overflow-hidden"
              style={taskListPanelHeight ? { height: `${taskListPanelHeight}px` } : undefined}
            >
              <h3>筛选结果</h3>
              <div
                className="sentinelflow-task-list-scroll"
                style={taskListMaxHeight ? { maxHeight: `${taskListMaxHeight}px` } : undefined}
              >
                <div className="sentinelflow-task-list">
                  {filteredTasks.length ? filteredTasks.map((task) => (
                    <button key={task.task_id} type="button" className={`sentinelflow-task-tile${selectedTask?.task_id === task.task_id ? ' sentinelflow-task-tile-active' : ''}`} onClick={() => setSelectedTaskId(task.task_id)}>
                      <div className="sentinelflow-response-row">
                        <strong>{task.title}</strong>
                        <StatusBadge tone={getTone(task)}>{getTaskStatusLabel(task.status)}</StatusBadge>
                      </div>
                      <span>{task.alert_time || '未提供告警时间'}</span>
                      <span>{getTaskFlowLabel(task)}</span>
                    </button>
                  )) : <p className="sentinelflow-muted-text">当前筛选条件下没有任务。</p>}
                </div>
              </div>
            </div>

            <div ref={detailPanelRef} className="sentinelflow-detail-panel">
              <h3>任务详情</h3>
              {selectedTask ? (
                <div className="sentinelflow-response-stack">
                  <div className="sentinelflow-response-row">
                    <StatusBadge tone={getTone(selectedTask)}>{getTaskStatusLabel(selectedTask.status)}</StatusBadge>
                    <span>{selectedTask.alert_time || '未提供告警时间'}</span>
                    <span>{getTaskFlowLabel(selectedTask)}</span>
                  </div>
                  <p className="sentinelflow-muted-text">{selectedTask.description}</p>

                  <div className="sentinelflow-context-grid">
                    <div className="sentinelflow-context-card"><strong>告警名称</strong><span>{String(selectedPayload.alert_name ?? '未提供')}</span></div>
                    <div className="sentinelflow-context-card"><strong>事件号</strong><span>{selectedTask.event_ids || '未提供'}</span></div>
                    <div className="sentinelflow-context-card"><strong>源 IP</strong><span>{String(selectedPayload.sip ?? '未提供')}</span></div>
                    <div className="sentinelflow-context-card"><strong>目标 IP</strong><span title={dipPreview.fullText}>{dipPreview.text}</span></div>
                    <div className="sentinelflow-context-card"><strong>告警时间</strong><span>{String(selectedPayload.alert_time ?? selectedTask.alert_time ?? '未提供')}</span></div>
                    <div className="sentinelflow-context-card"><strong>当前研判</strong><span>{String(selectedPayload.current_judgment ?? '未提供')}</span></div>
                  </div>

                  {selectedWorkflowRun && workflowDecision ? (
                    <div className="rounded-xl border border-amber-100 bg-amber-50 p-4">
                      <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Workflow 调用</div>
                      <div className="mt-2 text-sm font-semibold text-amber-950">
                        {`主 Agent 调用了流程：${workflowDecision}`}
                      </div>
                      {workflowDecisionReason ? (
                        <div className="mt-2 text-sm text-amber-900">
                          {`Workflow 返回：${workflowDecisionReason}`}
                        </div>
                      ) : (
                        <div className="mt-2 text-sm text-amber-900">
                          该 Workflow 已作为主 Agent 的一个中间能力被调用。
                        </div>
                      )}
                    </div>
                  ) : null}

                  {selectedDisposition || selectedReason || selectedSummary ? (
                    <div className="rounded-xl border border-blue-100 bg-blue-50 p-4">
                      <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">最终研判</div>
                      <div className="mt-2 text-sm font-semibold text-blue-950">{`分类：${getDispositionLabel(selectedDisposition)}`}</div>
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

                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">处置全流程</div>
                        <p className="mt-1 text-sm text-gray-600">展开后可查看从接收告警、主 Agent 研判、技能调用到结单结果的完整细节。</p>
                      </div>
                      <button type="button" className="sentinelflow-ghost-button" onClick={() => setProcessExpanded((current) => !current)}>
                        {processExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        {processExpanded ? '收起处置全流程' : '展开处置全流程'}
                      </button>
                    </div>
                    {processExpanded ? <div className="mt-4"><ProcessTrace trace={selectedTrace} traceOwnerId={selectedTask.task_id} /></div> : null}
                  </div>

                  {selectedTask.status === 'failed' ? (
                    <div className="flex justify-end">
                      <button type="button" className="sentinelflow-ghost-button" onClick={() => void handleRetry(selectedTask)} disabled={runningAction !== ''}>
                        {runningAction === selectedTask.task_id ? '重试中...' : '重试任务'}
                      </button>
                    </div>
                  ) : null}
                </div>
              ) : <p className="sentinelflow-muted-text">选择一条任务后查看详情。</p>}
            </div>
          </div>
        ) : null}
      </Surface>
    </div>
  )
}
