import { useEffect, useMemo, useRef, useState } from 'react'
import { MessageSquareText, Plus, RotateCcw, Send, Square, Trash2 } from 'lucide-react'
import type { CommandDispatchResponse } from '@/api/sentinelflow'
import JsonPreview from '@/components/sentinelflow/JsonPreview'
import MarkdownContent from '@/components/sentinelflow/MarkdownContent'
import StatusBadge from '@/components/sentinelflow/StatusBadge'
import Surface from '@/components/sentinelflow/Surface'
import PageHeader from '@/components/common/PageHeader'
import {
  type CommandHistoryItem,
  createConversationSession,
  clearActiveConversation,
  deleteActiveConversation,
  getConversationRuntimeState,
  resolveConversationApproval,
  sanitizeDisplayText,
  setConversationActiveSession,
  setConversationDraft,
  startConversationRun,
  stopConversationRun,
  subscribeConversationRuntime,
  summarizeAssistantReply,
} from '@/utils/sentinelflowConversationStore'

type ToolCallLike = {
  name?: string
  args?: unknown
}

type WorkerStepLike = {
  step?: number
  worker_agent?: string
  task_prompt?: string
  delegation_reason?: string
  tool_calls?: ToolCallLike[]
  final_response?: string
}

type CommandDataLike = {
  final_response?: string
  tool_calls?: ToolCallLike[]
  primary_agent?: string
  worker_agent?: string
  delegation_reason?: string
  worker_results?: WorkerStepLike[]
  worker_result?: {
    tool_calls?: ToolCallLike[]
    agent_name?: string
  }
}

function formatToolArguments(args: unknown): string {
  if (!args || typeof args !== 'object') return '无参数'
  const entries = Object.entries(args as Record<string, unknown>).slice(0, 3)
  if (!entries.length) return '无参数'
  return entries
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join(' | ')
}

function extractCommandData(data: unknown): CommandDataLike {
  if (!data || typeof data !== 'object') return {}
  return data as CommandDataLike
}

export default function SentinelFlowConversationPage() {
  const streamRef = useRef<HTMLDivElement | null>(null)
  const [runtimeState, setRuntimeState] = useState(() => getConversationRuntimeState())
  const [pendingCommand, setPendingCommand] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const { sessions, activeSessionId, running, runningSessionId, streamingReply, streamingStatus } = runtimeState

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? sessions[0],
    [activeSessionId, sessions],
  )
  const commandText = activeSession?.draft ?? ''
  const history = activeSession?.history ?? []
  const orderedHistory = useMemo(() => [...history].reverse(), [history])
  const isActiveSessionRunning = running && runningSessionId === activeSession?.id
  const hasConversation = orderedHistory.length > 0 || isActiveSessionRunning
  const runningAgentStatus = streamingStatus.includes('子 Agent') ? streamingStatus : ''

  useEffect(() => {
    const element = streamRef.current
    if (!element) return
    element.scrollTop = element.scrollHeight
  }, [history, isActiveSessionRunning, streamingReply, streamingStatus])

  useEffect(() => subscribeConversationRuntime(setRuntimeState), [])

  function createNewSession() {
    createConversationSession()
    setExpandedId(null)
  }

  function handleClearConversation() {
    clearActiveConversation()
    setExpandedId(null)
  }

  function handleDeleteCurrentSession() {
    deleteActiveConversation()
    setExpandedId(null)
  }

  async function handleStopCurrentRun() {
    await stopConversationRun()
  }

  async function handleRun() {
    await startConversationRun()
    setExpandedId(null)
  }

  return (
    <div className="sentinelflow-page-stack">
      <PageHeader
        title="对话指挥台"
        description="通过自然语言调用主 Agent 进行查询、分析和协同处理。"
        icon={<MessageSquareText className="w-8 h-8" />}
        action={
          <div className="sentinelflow-response-row">
            <button
              type="button"
              className="sentinelflow-ghost-button sentinelflow-inline-button"
              onClick={createNewSession}
              disabled={running}
            >
              <Plus className="h-4 w-4" />
              新建会话
            </button>
            {hasConversation ? (
              <button
                type="button"
                className="sentinelflow-ghost-button sentinelflow-inline-button"
                onClick={handleClearConversation}
                disabled={running}
              >
                <RotateCcw className="h-4 w-4" />
                清空会话
              </button>
            ) : null}
          </div>
        }
      />

      <Surface title="">
        <div className="sentinelflow-conversation-layout">
          <div className="sentinelflow-session-strip">
            {sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                className={`sentinelflow-session-chip${session.id === activeSession.id ? ' sentinelflow-session-chip-active' : ''}`}
                onClick={() => {
                  setConversationActiveSession(session.id)
                  setExpandedId(null)
                }}
              >
                <span>{session.title}</span>
              </button>
            ))}
            {sessions.length > 1 ? (
              <button
                type="button"
                className="sentinelflow-ghost-button sentinelflow-inline-button"
                onClick={handleDeleteCurrentSession}
                disabled={running}
              >
                <Trash2 className="h-4 w-4" />
                删除当前
              </button>
            ) : null}
          </div>

          <div className={`sentinelflow-chat-panel ${hasConversation ? '' : 'sentinelflow-chat-panel-empty'}`}>
            {hasConversation ? (
              <div ref={streamRef} className="sentinelflow-chat-stream">
                {orderedHistory.map((item) => {
                const assistantReply = summarizeAssistantReply(item.response)
                const isExpanded = expandedId === item.id
                const commandData = extractCommandData(item.response.data)
                const toolCalls = Array.isArray(commandData.tool_calls) ? commandData.tool_calls as ToolCallLike[] : []
                const workerToolCalls = Array.isArray(commandData.worker_result?.tool_calls) ? commandData.worker_result.tool_calls as ToolCallLike[] : []
                const workerResults = Array.isArray(commandData.worker_results) ? commandData.worker_results as WorkerStepLike[] : []
                const primaryAgent = typeof commandData.primary_agent === 'string' ? commandData.primary_agent : ''
                const workerAgent = typeof commandData.worker_agent === 'string' ? commandData.worker_agent : (typeof commandData.worker_result?.agent_name === 'string' ? commandData.worker_result.agent_name : '')
                const delegationReason = typeof commandData.delegation_reason === 'string' ? commandData.delegation_reason : ''
                const approvalRequest = commandData.approval_request as { approval_id?: string; skill_name?: string; arguments_summary?: string; message?: string } | undefined

                return (
                  <div key={item.id} className="sentinelflow-chat-turn">
                    <div className="sentinelflow-chat-meta">
                      <span>{new Date(item.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>

                    <div className="sentinelflow-chat-bubble sentinelflow-chat-bubble-user">
                      <MarkdownContent content={item.command} inverted />
                    </div>

                    <div className="sentinelflow-chat-bubble sentinelflow-chat-bubble-assistant">
                      <div className="sentinelflow-response-row">
                        <strong>SentinelFlow</strong>
                      </div>
                      {(primaryAgent || workerAgent) ? (
                        <div className="sentinelflow-tool-call-summary">
                          {primaryAgent ? `主 Agent：${primaryAgent}` : ''}
                          {primaryAgent && workerAgent ? '  ·  ' : ''}
                          {workerAgent ? `子 Agent：${workerAgent}` : ''}
                        </div>
                      ) : null}
                      {delegationReason ? (
                        <div className="sentinelflow-tool-call-summary">
                          分派原因：{delegationReason}
                        </div>
                      ) : null}
                      {item.response.route === 'approval_required' && approvalRequest?.approval_id ? (
                        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                          <div className="font-semibold">等待 Skill 审批</div>
                          <div className="mt-1">{approvalRequest.message || `Skill「${approvalRequest.skill_name || '未命名 Skill'}」需要审批。`}</div>
                          <div className="mt-1 text-xs text-amber-800">参数：{approvalRequest.arguments_summary || '无参数'}</div>
                          <div className="mt-3 flex gap-2">
                            <button
                              type="button"
                              className="sentinelflow-primary-button"
                              onClick={() => void resolveConversationApproval(item.id, approvalRequest.approval_id || '', 'approve')}
                              disabled={running}
                            >
                              批准并继续
                            </button>
                            <button
                              type="button"
                              className="sentinelflow-ghost-button"
                              onClick={() => void resolveConversationApproval(item.id, approvalRequest.approval_id || '', 'reject')}
                              disabled={running}
                            >
                              拒绝并继续
                            </button>
                          </div>
                        </div>
                      ) : null}
                      <MarkdownContent content={assistantReply} />
                      {toolCalls.length ? (
                        <div className="sentinelflow-tool-call-summary">调用技能 {toolCalls.length} 次</div>
                      ) : null}
                      {toolCalls.length ? (
                        <div className="sentinelflow-tool-call-list">
                          {toolCalls.map((toolCall, index) => (
                            <div key={`${item.id}-tool-${index}`} className="sentinelflow-tool-call-card">
                              <div className="sentinelflow-response-row">
                                <StatusBadge tone="neutral">tool</StatusBadge>
                                <strong>{toolCall.name || `tool-${index + 1}`}</strong>
                              </div>
                              <span>{formatToolArguments(toolCall.args)}</span>
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {workerToolCalls.length ? (
                        <>
                          <div className="sentinelflow-tool-call-summary">
                            {workerAgent ? `${workerAgent} 调用了 ${workerToolCalls.length} 次技能` : `子 Agent 调用了 ${workerToolCalls.length} 次技能`}
                          </div>
                          <div className="sentinelflow-tool-call-list">
                            {workerToolCalls.map((toolCall, index) => (
                              <div key={`${item.id}-worker-tool-${index}`} className="sentinelflow-tool-call-card">
                                <div className="sentinelflow-response-row">
                                  <StatusBadge tone="warn">子 Agent tool</StatusBadge>
                                  <strong>{toolCall.name || `tool-${index + 1}`}</strong>
                                </div>
                                <span>{formatToolArguments(toolCall.args)}</span>
                              </div>
                            ))}
                          </div>
                        </>
                      ) : null}
                      {workerResults.length > 1 ? (
                        <div className="sentinelflow-chat-details">
                          <div className="sentinelflow-tool-call-summary">子 Agent 串联步骤</div>
                          <div className="sentinelflow-tool-call-list">
                            {workerResults.map((step, index) => (
                              <div key={`${item.id}-worker-step-${index}`} className="sentinelflow-tool-call-card">
                                <div className="sentinelflow-response-row">
                                  <StatusBadge tone="warn">{`步骤 ${step.step ?? index + 1}`}</StatusBadge>
                                  <strong>{step.worker_agent || `worker-${index + 1}`}</strong>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {item.response.error ? <div className="sentinelflow-message-block sentinelflow-message-error">{item.response.error}</div> : null}
                      <div className="sentinelflow-chat-actions">
                        <StatusBadge tone={item.response.success ? 'success' : 'warn'}>{item.response.success ? '已完成' : '失败'}</StatusBadge>
                        <button type="button" className="sentinelflow-ghost-button" onClick={() => setExpandedId((current) => current === item.id ? null : item.id)}>
                          {isExpanded ? '收起详情' : '查看详情'}
                        </button>
                      </div>
                      {isExpanded ? (
                        <div className="sentinelflow-chat-details">
                          <div className="sentinelflow-response-row">
                            <StatusBadge tone={item.response.success ? 'success' : 'warn'}>{item.response.success ? 'success' : 'error'}</StatusBadge>
                            <span>route: {item.response.route}</span>
                          </div>
                          <JsonPreview value={item.response.data} />
                        </div>
                      ) : null}
                    </div>
                  </div>
                )
                })}

                {isActiveSessionRunning ? (
                  <div className="sentinelflow-chat-turn">
                  <div className="sentinelflow-chat-bubble sentinelflow-chat-bubble-user">
                    <MarkdownContent content={runtimeState.pendingCommand} inverted />
                  </div>
                  <div className="sentinelflow-chat-bubble sentinelflow-chat-bubble-assistant">
                    <div className="sentinelflow-response-row">
                      <strong>SentinelFlow</strong>
                    </div>
                    <MarkdownContent content={sanitizeDisplayText(streamingReply) || (runningAgentStatus ? '正在协同处理，请稍候…' : streamingStatus)} />
                    {runningAgentStatus ? (
                      <div className="sentinelflow-tool-call-summary">{runningAgentStatus}</div>
                    ) : null}
                  </div>
                </div>
                ) : null}
              </div>
            ) : (
              <div className="sentinelflow-chat-empty-state">
                <h2 className="sentinelflow-chat-empty-title">有什么可以帮你处理的？</h2>
              </div>
            )}

            <div className={`sentinelflow-chat-composer ${hasConversation ? '' : 'sentinelflow-chat-composer-home'}`}>
              <textarea
                id="sentinelflow-command-input"
                className="sentinelflow-command-input"
                placeholder="给 SentinelFlow 发送消息"
                value={commandText}
                onChange={(event) => setConversationDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.nativeEvent.isComposing) {
                    return
                  }
                  if (event.key === 'Enter' && !event.shiftKey && !isActiveSessionRunning) {
                    event.preventDefault()
                    void handleRun()
                  }
                }}
                rows={4}
              />
              <div className="sentinelflow-chat-composer-actions">
                <button
                  type="button"
                  className="sentinelflow-chat-send-button"
                  onClick={isActiveSessionRunning ? () => void handleStopCurrentRun() : () => void handleRun()}
                  disabled={!isActiveSessionRunning && !commandText.trim()}
                  aria-label={isActiveSessionRunning ? '停止当前任务' : '发送命令'}
                >
                  {isActiveSessionRunning ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
                </button>
              </div>
            </div>
          </div>
        </div>
      </Surface>
    </div>
  )
}
