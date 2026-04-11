import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, GitBranch, Plus, Radar, RefreshCw, Save, ShieldCheck, Trash2, Workflow as WorkflowIcon, X } from 'lucide-react'
import { createWorkflow, deleteWorkflow, fetchAgents, fetchPollAlerts, fetchRuntimeSettings, fetchWorkflowDetail, fetchWorkflows, saveWorkflow, type AgentSummary, type WorkflowDetail } from '@/api/sentinelflow'
import Surface from '@/components/sentinelflow/Surface'
import StatusBadge from '@/components/sentinelflow/StatusBadge'
import PageHeader from '@/components/common/PageHeader'
import { brand, withProductName } from '@/config/brand'
import { useSentinelFlowAsyncData } from '@/hooks/useSentinelFlowAsyncData'
import { useSentinelFlowLiveRefresh } from '@/hooks/useSentinelFlowLiveRefresh'

type WorkflowCard = {
  id: string
  name: string
  description: string
  enabled: boolean
  scenarios: string[]
  recommended_action: string
  steps_count: number
  step_agents: string[]
  final_handler_type: string
  final_handler_action: string
  location: string
  tone?: 'neutral' | 'success' | 'warn' | 'danger'
}

type WorkflowDraft = {
  name: string
  description: string
  recommendedAction: string
  enabled: boolean
  selectionKeywords: string
  stepAgents: string[]
}

const EMPTY_DRAFT: WorkflowDraft = {
  name: '',
  description: '',
  recommendedAction: 'triage_close',
  enabled: true,
  selectionKeywords: '',
  stepAgents: [],
}

function detailToDraft(detail: WorkflowDetail): WorkflowDraft {
  return {
    name: detail.name,
    description: detail.description,
    recommendedAction: detail.recommended_action,
    enabled: detail.enabled,
    selectionKeywords: (detail.selection_keywords ?? []).join(', '),
    stepAgents: (detail.steps ?? []).map((step) => step.agent),
  }
}

function draftToPayload(draft: WorkflowDraft) {
  const stepAgents = draft.stepAgents.filter(Boolean)
  const steps = stepAgents.map((agent, index) => ({
    id: `step-${index + 1}`,
    name: `${index + 1}. ${agent}`,
    agent,
  }))
  const recommendedAction = draft.recommendedAction === 'triage_dispose' ? 'triage_dispose' : 'triage_close'
  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    template: recommendedAction === 'triage_dispose' ? 'dispose' : 'close',
    workflow: {
      name: draft.name.trim(),
      description: draft.description.trim(),
      enabled: draft.enabled,
      scenarios: ['alert', 'task'],
      selection_keywords: draft.selectionKeywords.split(',').map((item) => item.trim()).filter(Boolean),
      recommended_action: recommendedAction,
      steps,
      final_handler: {
        type: 'primary',
        action: recommendedAction,
      },
    },
  }
}

export default function SentinelFlowWorkflowsPage() {
  const { data: settings, reload: reloadSettings } = useSentinelFlowAsyncData(fetchRuntimeSettings, [])
  const { data: poll, reload: reloadPoll } = useSentinelFlowAsyncData(fetchPollAlerts, [])
  const { data: workflowsData, reload: reloadWorkflows } = useSentinelFlowAsyncData(fetchWorkflows, [])
  const { data: agentsData, reload: reloadAgents } = useSentinelFlowAsyncData(fetchAgents, [])
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null)
  const [detail, setDetail] = useState<WorkflowDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState<WorkflowDraft>(EMPTY_DRAFT)
  const [submitting, setSubmitting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [formError, setFormError] = useState('')
  const preservedScrollPositionsRef = useRef<Array<{ element: Element; top: number }>>([])

  const workflows: WorkflowCard[] = workflowsData?.workflows?.length
    ? workflowsData.workflows.map((workflow) => ({
        ...workflow,
        tone: workflow.id.includes('dispose') ? 'warn' : 'success',
      }))
    : []

  const workerAgents = useMemo(
    () => (agentsData?.agents ?? []).filter((agent: AgentSummary) => agent.role === 'worker' && agent.enabled !== false),
    [agentsData],
  )

  useEffect(() => {
    if (selectedWorkflowId || workflows.length === 0) return
    setSelectedWorkflowId(workflows[0].id)
  }, [selectedWorkflowId, workflows])

  useEffect(() => {
    if (!selectedWorkflowId) return
    let cancelled = false
    setLoadingDetail(true)
    setDetailError(null)
    fetchWorkflowDetail(selectedWorkflowId)
      .then((result) => {
        if (!cancelled) {
          setDetail(result)
          setDetailError(null)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setDetailError(error instanceof Error ? error.message : '工作流详情加载失败。')
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedWorkflowId])

  useLayoutEffect(() => {
    if (preservedScrollPositionsRef.current.length === 0) return
    const restore = () => {
      for (const item of preservedScrollPositionsRef.current) {
        if ('scrollTop' in item.element) {
          ;(item.element as HTMLElement).scrollTop = item.top
        }
      }
    }
    restore()
    window.requestAnimationFrame(() => {
      restore()
      window.requestAnimationFrame(() => {
        restore()
        preservedScrollPositionsRef.current = []
      })
    })
  }, [selectedWorkflowId, detail, loadingDetail])

  function collectScrollableElements(start: HTMLElement | null) {
    const elements: Array<{ element: Element; top: number }> = []
    const scrollingElement = document.scrollingElement
    if (scrollingElement) {
      elements.push({ element: scrollingElement, top: scrollingElement.scrollTop })
    }
    let current: HTMLElement | null = start
    while (current) {
      const style = window.getComputedStyle(current)
      const overflowY = style.overflowY
      if ((overflowY === 'auto' || overflowY === 'scroll') && current.scrollHeight > current.clientHeight) {
        elements.push({ element: current, top: current.scrollTop })
      }
      current = current.parentElement
    }
    return elements
  }

  function handleSelectWorkflow(id: string, trigger: HTMLElement | null) {
    preservedScrollPositionsRef.current = collectScrollableElements(trigger)
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur()
    }
    setSelectedWorkflowId(id)
  }

  const taskCountByWorkflow = new Map<string, number>()
  for (const task of poll?.tasks ?? []) {
    taskCountByWorkflow.set(task.workflow_name, (taskCountByWorkflow.get(task.workflow_name) ?? 0) + 1)
  }

  const refreshWorkflowRuntime = useCallback(() => {
    void reloadPoll()
  }, [reloadPoll])

  useSentinelFlowLiveRefresh(refreshWorkflowRuntime, { intervalMs: 5000 })

  function startCreate() {
    setEditingId('__new__')
    setDraft(EMPTY_DRAFT)
    setFormError('')
  }

  function startEdit() {
    if (!detail) return
    setEditingId(detail.id)
    setDraft(detailToDraft(detail))
    setFormError('')
  }

  function cancelEdit() {
    setEditingId(null)
    setDraft(EMPTY_DRAFT)
    setFormError('')
  }

  function moveStep(index: number, direction: -1 | 1) {
    setDraft((current) => {
      const next = [...current.stepAgents]
      const target = index + direction
      if (target < 0 || target >= next.length) return current
      const temp = next[index]
      next[index] = next[target]
      next[target] = temp
      return { ...current, stepAgents: next }
    })
  }

  async function submitDraft() {
    if (!draft.name.trim()) return
    setSubmitting(true)
    setFormError('')
    try {
      const payload = draftToPayload(draft)
      const result = editingId === '__new__'
        ? await createWorkflow(payload)
        : await saveWorkflow(editingId ?? draft.name.trim(), payload)
      const workflowResult = result as WorkflowDetail
      await Promise.all([reloadWorkflows(), reloadPoll(), reloadAgents()])
      setSelectedWorkflowId(workflowResult.id)
      setDetail(workflowResult)
      setEditingId(null)
      setDraft(EMPTY_DRAFT)
    } catch (error) {
      setFormError(error instanceof Error ? error.message : '保存工作流失败。')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete() {
    if (!detail || deleting) return
    const confirmed = window.confirm(`确认删除工作流“${detail.name}”吗？这不会删除任何 Agent，只会删除这条 Agent Workflow。`)
    if (!confirmed) return
    setDeleting(true)
    try {
      await deleteWorkflow(detail.id)
      await Promise.all([reloadWorkflows(), reloadPoll()])
      const remaining = workflows.filter((item) => item.id !== detail.id)
      setSelectedWorkflowId(remaining[0]?.id ?? null)
      setDetail(null)
      setEditingId(null)
      setDraft(EMPTY_DRAFT)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="sentinelflow-page-stack">
      <PageHeader
        title="工作流"
        description="专门编排任务/告警场景下的 Agent Workflow。"
        icon={<WorkflowIcon className="w-8 h-8" />}
        action={(
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void Promise.all([reloadSettings(), reloadPoll(), reloadWorkflows(), reloadAgents()])}
              className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-gray-700 transition-colors hover:bg-gray-50"
            >
              <RefreshCw className="w-4 h-4" />
              刷新视图
            </button>
            <button
              type="button"
              onClick={startCreate}
              className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700"
            >
              <Plus className="w-4 h-4" />
              新建流程
            </button>
          </div>
        )}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900">
            <GitBranch className="h-4 w-4 text-sky-500" />
            Workflow 总数
          </div>
          <div className="text-3xl font-bold text-gray-900">{workflows.length}</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900">
            <Radar className="h-4 w-4 text-amber-500" />
            关联任务
          </div>
          <div className="text-3xl font-bold text-gray-900">{(poll?.tasks ?? []).length}</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900">
            <ShieldCheck className="h-4 w-4 text-emerald-500" />
            当前引擎
          </div>
          <div className="text-base font-semibold text-gray-900">{settings?.runtime.workflow_engine ?? brand.workflowEngineLabel}</div>
        </div>
      </div>

      <Surface title="Agent Workflow 目录" subtitle="工作流页只编排子 Agent 调用顺序。子 Agent 自己做什么、能调用什么 Skill，仍然在 Agents 页面配置。">
        <div className="grid min-w-0 items-start gap-6 xl:grid-cols-[minmax(340px,420px)_minmax(0,1fr)]">
          <div className="sticky top-6 grid max-h-[calc(100vh-8rem)] auto-rows-max content-start gap-3 self-start overflow-y-auto p-1 pr-3" style={{ overflowAnchor: 'none' }}>
            {workflows.map((workflow, index) => {
              const palettes = [
                'bg-slate-50 border-slate-200',
                'bg-red-50 border-red-200',
                'bg-emerald-50 border-emerald-200',
                'bg-amber-50 border-amber-200',
              ]
              const palette = palettes[index % palettes.length]
              return (
                <button
                  key={workflow.id}
                  type="button"
                  onPointerDown={(event) => event.preventDefault()}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={(event) => handleSelectWorkflow(workflow.id, event.currentTarget)}
                  className={`min-h-[176px] rounded-xl border p-4 text-left shadow-sm transition-all ${palette} ${selectedWorkflowId === workflow.id ? 'border-sky-500 bg-sky-100 shadow-[0_0_0_2px_rgba(14,165,233,0.35),0_10px_30px_rgba(14,165,233,0.12)]' : 'hover:bg-white hover:border-slate-300'}`}
                >
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <strong className="block truncate text-sm font-semibold text-gray-900">{workflow.name}</strong>
                      <div className="mt-1 text-[11px] text-gray-500">{workflow.id}</div>
                    </div>
                    <StatusBadge tone={workflow.tone ?? 'neutral'}>
                      {workflow.enabled ? (taskCountByWorkflow.get(workflow.id) ? '运行中' : '已启用') : '已停用'}
                    </StatusBadge>
                  </div>
                  <p className="min-h-[72px] text-xs leading-6 text-gray-600">{workflow.description}</p>
                  <div className="mt-4 grid grid-cols-3 gap-2 border-t border-gray-200/70 pt-3 text-xs">
                    <div>
                      <div className="font-semibold text-gray-900">{workflow.steps_count}</div>
                      <div className="text-gray-500">步骤</div>
                    </div>
                    <div>
                      <div className="font-semibold text-gray-900">{workflow.scenarios.length}</div>
                      <div className="text-gray-500">场景</div>
                    </div>
                    <div>
                      <div className="font-semibold text-gray-900">{taskCountByWorkflow.get(workflow.id) ?? 0}</div>
                      <div className="text-gray-500">任务</div>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>

          <div className="grid gap-4">
            <Surface
              title={editingId ? (editingId === '__new__' ? '新建 Agent Workflow' : '编辑 Agent Workflow') : (detail?.name ?? 'Agent Workflow 详情')}
              subtitle={editingId ? '这里只编排固定顺序和命中条件；子 Agent 的提示词、Skill 权限和模型都在 Agents 页面管理。' : (detail?.description ?? '选择左侧工作流后，可查看固定步骤、最终处理方式和校验状态。')}
            >
              {editingId ? (
                <div className="grid gap-4">
                  {formError ? <div className="sentinelflow-message-block sentinelflow-message-error">{formError}</div> : null}
                  <div className="grid gap-3 md:grid-cols-2">
                    <input className="sentinelflow-settings-input" placeholder="流程名称，如 研判并封禁" value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
                    <select className="sentinelflow-settings-input" value={draft.recommendedAction} onChange={(event) => setDraft((current) => ({ ...current, recommendedAction: event.target.value }))}>
                      <option value="triage_close">最终研判并结单</option>
                      <option value="triage_dispose">最终研判并处置</option>
                    </select>
                  </div>

                  <textarea className="sentinelflow-command-input" rows={4} placeholder="流程描述" value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} />

                  <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                    <input className="sentinelflow-settings-input" placeholder="明显已知模式的命中关键词，用逗号分隔，如 攻击, 恶意, 封禁" value={draft.selectionKeywords} onChange={(event) => setDraft((current) => ({ ...current, selectionKeywords: event.target.value }))} />
                    <select className="sentinelflow-settings-input" value={draft.enabled ? 'enabled' : 'disabled'} onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.value === 'enabled' }))}>
                      <option value="enabled">已启用</option>
                      <option value="disabled">已停用</option>
                    </select>
                  </div>

                  <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-gray-900">子 Agent 调用顺序</div>
                        <div className="mt-1 text-xs leading-5 text-gray-500">这里只决定谁先被调用、谁后被调用。复杂或未知任务不会强行命中这里的流程，而是回到主 Agent 的自由 ReAct 模式。</div>
                      </div>
                      <button
                        type="button"
                        className="sentinelflow-ghost-button inline-flex flex-nowrap items-center justify-center gap-2 whitespace-nowrap"
                        onClick={() => setDraft((current) => ({ ...current, stepAgents: [...current.stepAgents, workerAgents[0]?.name ?? ''] }))}
                        disabled={workerAgents.length === 0}
                      >
                        <Plus className="h-4 w-4" />
                        添加步骤
                      </button>
                    </div>

                    <div className="grid gap-3">
                      {draft.stepAgents.length === 0 ? <div className="text-sm text-gray-500">当前还没有步骤，请至少加入一个子 Agent。</div> : null}
                      {draft.stepAgents.map((agentName, index) => (
                        <div key={`draft-step-${index}`} className="rounded-lg border border-gray-200 bg-white p-4">
                          <div className="flex flex-wrap items-center gap-3">
                            <div className="min-w-[72px] text-sm font-semibold text-gray-900">{`步骤 ${index + 1}`}</div>
                            <select
                              className="sentinelflow-settings-input flex-1"
                              value={agentName}
                              onChange={(event) => setDraft((current) => ({
                                ...current,
                                stepAgents: current.stepAgents.map((item, itemIndex) => itemIndex === index ? event.target.value : item),
                              }))}
                            >
                              {workerAgents.map((agent) => (
                                <option key={agent.name} value={agent.name}>{agent.name}</option>
                              ))}
                            </select>
                            <button type="button" className="sentinelflow-ghost-button" onClick={() => moveStep(index, -1)} disabled={index === 0}>
                              <ArrowUp className="h-4 w-4" />
                            </button>
                            <button type="button" className="sentinelflow-ghost-button" onClick={() => moveStep(index, 1)} disabled={index === draft.stepAgents.length - 1}>
                              <ArrowDown className="h-4 w-4" />
                            </button>
                            <button
                              type="button"
                              className="sentinelflow-ghost-button"
                              onClick={() => setDraft((current) => ({ ...current, stepAgents: current.stepAgents.filter((_, itemIndex) => itemIndex !== index) }))}
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-3">
                    <button type="button" className="sentinelflow-primary-button inline-flex flex-nowrap items-center justify-center gap-2 whitespace-nowrap" onClick={() => void submitDraft()} disabled={submitting || !draft.name.trim() || draft.stepAgents.filter(Boolean).length === 0}>
                      <Save className="h-4 w-4" />
                      {submitting ? '保存中...' : '保存流程'}
                    </button>
                    <button type="button" className="sentinelflow-ghost-button inline-flex flex-nowrap items-center justify-center gap-2 whitespace-nowrap" onClick={cancelEdit} disabled={submitting}>取消</button>
                  </div>
                </div>
              ) : loadingDetail && !detail ? (
                <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-sm text-gray-500">正在加载工作流详情...</div>
              ) : detail ? (
                <div className="grid gap-4">
                  {loadingDetail ? <div className="rounded-lg border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-700">正在切换工作流详情...</div> : null}
                  {detailError ? <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{detailError}</div> : null}
                  <div className="flex justify-end gap-3">
                    <button type="button" className="sentinelflow-ghost-button" onClick={startEdit} disabled={deleting}>编辑流程</button>
                    <button type="button" className="sentinelflow-ghost-button text-red-600" onClick={() => void handleDelete()} disabled={deleting}>
                      <Trash2 className="h-4 w-4" />
                      {deleting ? '删除中...' : '删除流程'}
                    </button>
                  </div>

                  <div className="grid gap-3 md:grid-cols-4">
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">固定步骤</div>
                      <div className="mt-2 text-2xl font-semibold text-gray-900">{detail.steps_count}</div>
                    </div>
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">适用场景</div>
                      <div className="mt-2 text-base font-semibold text-gray-900">{(detail.scenarios ?? []).join(' / ') || '未设置'}</div>
                    </div>
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">关联任务</div>
                      <div className="mt-2 text-2xl font-semibold text-gray-900">{taskCountByWorkflow.get(detail.id) ?? 0}</div>
                    </div>
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">流程校验</div>
                      <div className="mt-2">
                        <StatusBadge tone={detail.validation?.valid ? 'success' : 'warn'}>
                          {detail.validation?.valid ? '通过' : '需要关注'}
                        </StatusBadge>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-lg border border-gray-200 bg-white p-4">
                    <div className="mb-3 text-sm font-semibold text-gray-900">固定步骤</div>
                    <div className="grid gap-3">
                      {(detail.steps ?? []).map((step, index) => (
                        <div key={step.id} className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-gray-900">{`${index + 1}. ${step.agent}`}</div>
                              <div className="mt-1 text-xs text-gray-500">{step.id}</div>
                            </div>
                            <StatusBadge tone="neutral">{step.agent}</StatusBadge>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">推荐动作</div>
                      <div className="mt-2 text-base font-semibold text-gray-900">{detail.recommended_action}</div>
                    </div>
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">最终处理</div>
                      <div className="mt-2 text-base font-semibold text-gray-900">{`${detail.final_handler?.type ?? detail.final_handler_type} / ${detail.final_handler?.action ?? detail.final_handler_action}`}</div>
                    </div>
                  </div>

                  {detail.selection_keywords?.length ? (
                    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                      <div className="mb-2 text-sm font-semibold text-gray-900">明显已知模式关键词</div>
                      <div className="flex flex-wrap gap-2">
                        {detail.selection_keywords.map((item: string) => (
                          <span key={item} className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs text-gray-700">{item}</span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {detail.validation?.errors?.length ? (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                      <div className="mb-2 text-sm font-semibold text-amber-900">校验提示</div>
                      <ul className="space-y-1 text-xs leading-6 text-amber-900">
                        {detail.validation.errors.map((error: string) => (
                          <li key={error}>- {error}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-sm text-gray-500">当前还没有可展示的工作流详情。</div>
              )}
            </Surface>
          </div>
        </div>
      </Surface>
    </div>
  )
}
