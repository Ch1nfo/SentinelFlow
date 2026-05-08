import { stopStreamingCommand, streamApprovalDecision, streamCommand, type CommandDispatchResponse, type CommandStreamEvent, type ConversationHistoryMessage } from '@/api/sentinelflow'
import { readLocalValue, removeLocalValue, writeLocalValue } from '@/utils/sentinelflowLocalState'
import { publishRuntimeActivity } from '@/utils/sentinelflowRuntimeSync'

export type CommandHistoryItem = {
  id: string
  command: string
  response: CommandDispatchResponse
  createdAt: string
}

export type ConversationSession = {
  id: string
  title: string
  updatedAt: string
  history: CommandHistoryItem[]
  draft: string
}

export type ConversationRuntimeState = {
  sessions: ConversationSession[]
  activeSessionId: string
  pendingCommand: string
  running: boolean
  runningSessionId: string
  streamingReply: string
  streamingRoute: string
  streamingSuccess: boolean
  streamingStatus: string
  activeRequestId: string
}

function isCommandWaitingApproval(response: CommandDispatchResponse): boolean {
  const approvalStatus = String(response.approval?.status || response.data?.approval_request?.status || '').trim().toLowerCase()
  return response.route === 'approval_required' || approvalStatus === 'pending'
}

const CONVERSATION_HISTORY_KEY = 'sentinelflow:conversation:history'
const CONVERSATION_DRAFT_KEY = 'sentinelflow:conversation:draft'
const CONVERSATION_SESSIONS_KEY = 'sentinelflow:conversation:sessions'
const CONVERSATION_ACTIVE_SESSION_KEY = 'sentinelflow:conversation:active'

function createSession(title = '新会话'): ConversationSession {
  return {
    id: `session-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    title,
    updatedAt: new Date().toISOString(),
    history: [],
    draft: '',
  }
}

function buildInitialSessions(): ConversationSession[] {
  const sessions = readLocalValue<ConversationSession[]>(CONVERSATION_SESSIONS_KEY, [])
  if (sessions.length) return sessions

  const legacyHistory = readLocalValue<CommandHistoryItem[]>(CONVERSATION_HISTORY_KEY, [])
  const legacyDraft = readLocalValue<string>(CONVERSATION_DRAFT_KEY, '')
  const initial = createSession(legacyHistory[0]?.command?.slice(0, 12) || '新会话')
  initial.history = legacyHistory
  initial.draft = legacyDraft
  return [initial]
}

export function sanitizeDisplayText(text: string): string {
  return text
    .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function summarizeAssistantReply(response: CommandDispatchResponse): string {
  const data = response.data ?? {}
  const finalResponse = typeof data.final_response === 'string' ? sanitizeDisplayText(data.final_response) : ''
  if (finalResponse) return finalResponse
  if (response.route === 'approval_required') {
    return '当前命中了需要审批的 Skill，请在下方确认后继续。'
  }
  if (response.error) return sanitizeDisplayText(response.error)

  if (response.route === 'find_alerts') {
    const alerts = Array.isArray(data.alerts) ? data.alerts : []
    return alerts.length ? `已查询到 ${alerts.length} 条告警，可以展开查看详情。` : '当前没有查询到可处理告警。'
  }
  if (response.route === 'get_ip_info') {
    const ip = typeof data.ip === 'string' ? data.ip : '目标 IP'
    return `已完成 ${ip} 的信息查询，可以展开查看资产与用户上下文。`
  }
  if (response.route === 'ban_ip') {
    const ip = typeof data.ip === 'string' ? data.ip : '目标 IP'
    return response.success ? `已发起 ${ip} 的封禁动作，请展开查看执行回执。` : `封禁 ${ip} 失败，请展开查看原因。`
  }
  if (response.route === 'close_alert') {
    return response.success ? '结单请求已提交，可以展开查看返回内容。' : '结单失败，请展开查看原因。'
  }
  if (response.route === 'contact_bot') {
    return response.success ? '通知已发送或已按演示模式模拟发送。' : '通知发送失败，请展开查看原因。'
  }
  if (response.route === 'handle_alert_close' || response.route === 'handle_alert_dispose') {
    return response.success ? '已完成告警处理链路，可以展开查看执行摘要。' : '告警处理链路未完全成功，请展开查看详情。'
  }
  if (response.route === 'help') {
    return '我已经整理了几条可直接使用的示例命令。'
  }
  return response.success ? '命令已执行完成，可以展开查看详细结果。' : '命令执行失败，请展开查看详细错误。'
}

function summarizeAssistantHistory(response: CommandDispatchResponse): string {
  const approvalStatus = String(response.approval?.status || '').trim().toLowerCase()
  if (approvalStatus === 'pending') {
    return '上一轮请求命中了需要审批的 Skill，尚未处理。'
  }
  if (approvalStatus === 'approved') {
    return '上一轮请求包含需要审批的 Skill，已获批准并完成处理。'
  }
  if (approvalStatus === 'rejected') {
    return '上一轮请求包含需要审批的 Skill，用户拒绝执行。'
  }
  return summarizeAssistantReply(response)
}

let state: ConversationRuntimeState = {
  sessions: buildInitialSessions(),
  activeSessionId: readLocalValue<string>(CONVERSATION_ACTIVE_SESSION_KEY, buildInitialSessions()[0]?.id || ''),
  pendingCommand: '',
  running: false,
  runningSessionId: '',
  streamingReply: '',
  streamingRoute: '',
  streamingSuccess: true,
  streamingStatus: '正在分析并调用所需能力，请稍候...',
  activeRequestId: '',
}

removeLocalValue(CONVERSATION_HISTORY_KEY)
removeLocalValue(CONVERSATION_DRAFT_KEY)

const listeners = new Set<(next: ConversationRuntimeState) => void>()
let abortController: AbortController | null = null

function emit() {
  writeLocalValue(CONVERSATION_SESSIONS_KEY, state.sessions)
  if (state.activeSessionId) {
    writeLocalValue(CONVERSATION_ACTIVE_SESSION_KEY, state.activeSessionId)
  }
  listeners.forEach((listener) => listener(state))
}

function setState(updater: (current: ConversationRuntimeState) => ConversationRuntimeState) {
  state = updater(state)
  emit()
}

function getActiveSession(current: ConversationRuntimeState) {
  return current.sessions.find((session) => session.id === current.activeSessionId) ?? current.sessions[0] ?? createSession()
}

function updateSession(sessionId: string, updater: (session: ConversationSession) => ConversationSession) {
  setState((current) => ({
    ...current,
    sessions: current.sessions.map((session) => (session.id === sessionId ? updater(session) : session)),
  }))
}

export function getConversationRuntimeState() {
  return state
}

export function subscribeConversationRuntime(handler: (next: ConversationRuntimeState) => void) {
  listeners.add(handler)
  return () => {
    listeners.delete(handler)
  }
}

export function setConversationActiveSession(sessionId: string) {
  setState((current) => ({ ...current, activeSessionId: sessionId }))
}

export function setConversationDraft(value: string) {
  const active = getActiveSession(state)
  updateSession(active.id, (session) => ({ ...session, draft: value }))
}

export function createConversationSession() {
  const next = createSession()
  setState((current) => ({
    ...current,
    sessions: [next, ...current.sessions],
    activeSessionId: next.id,
  }))
}

export function clearActiveConversation() {
  const active = getActiveSession(state)
  updateSession(active.id, (session) => ({
    ...session,
    history: [],
    draft: '',
    updatedAt: new Date().toISOString(),
    title: '新会话',
  }))
  setState((current) => ({ ...current, pendingCommand: '' }))
}

export function deleteActiveConversation() {
  if (state.sessions.length <= 1) {
    clearActiveConversation()
    return
  }
  const nextSessions = state.sessions.filter((session) => session.id !== state.activeSessionId)
  setState((current) => ({
    ...current,
    sessions: nextSessions,
    activeSessionId: nextSessions[0]?.id ?? '',
    pendingCommand: current.runningSessionId === current.activeSessionId ? current.pendingCommand : '',
  }))
}

export async function stopConversationRun() {
  if (state.activeRequestId) {
    try {
      await stopStreamingCommand(state.activeRequestId)
    } catch {
      // Ignore stop API failures and still abort locally.
    }
  }
  abortController?.abort()
}

export async function startConversationRun() {
  const activeSession = getActiveSession(state)
  const text = activeSession.draft.trim()
  if (!text || state.running) return

  abortController = new AbortController()
  const targetSessionId = activeSession.id
  const historyMessages: ConversationHistoryMessage[] = [...activeSession.history]
    .reverse()
    .flatMap((item) => {
      const assistant = summarizeAssistantHistory(item.response)
      const entries: ConversationHistoryMessage[] = [{ role: 'user', content: item.command }]
      if (assistant) {
        entries.push({ role: 'assistant', content: assistant })
      }
      return entries
    })

  setState((current) => ({
    ...current,
    pendingCommand: text,
    running: true,
    runningSessionId: targetSessionId,
    streamingReply: '',
    streamingRoute: '',
    streamingSuccess: true,
    streamingStatus: '正在分析并调用所需能力，请稍候...',
    activeRequestId: '',
    sessions: current.sessions.map((session) => (
      session.id === targetSessionId ? { ...session, draft: '' } : session
    )),
  }))

  try {
    const result = await streamCommand(text, historyMessages, (event: CommandStreamEvent) => {
      if (event.type === 'request') {
        setState((current) => ({ ...current, activeRequestId: event.payload.request_id }))
        return
      }
      if (event.type === 'meta') {
        setState((current) => ({
          ...current,
          streamingRoute: event.payload.route,
          streamingSuccess: event.payload.success,
        }))
        return
      }
      if (event.type === 'status') {
        setState((current) => ({ ...current, streamingStatus: event.payload.text }))
        return
      }
      if (event.type === 'delta') {
        setState((current) => ({
          ...current,
          streamingReply: sanitizeDisplayText(current.streamingReply + event.payload.text),
        }))
      }
    }, abortController.signal)

    const item: CommandHistoryItem = {
      id: `${Date.now()}`,
      command: text,
      response: result,
      createdAt: new Date().toISOString(),
    }
    setState((current) => ({
      ...current,
      sessions: current.sessions.map((session) => {
        if (session.id !== targetSessionId) return session
        return {
          ...session,
          history: [item, ...session.history].slice(0, 20),
          draft: '',
          updatedAt: item.createdAt,
          title: session.history.length ? session.title : text.slice(0, 18) || '新会话',
        }
      }),
    }))
    publishRuntimeActivity({
      type: 'command_dispatch',
      title: text,
      detail: isCommandWaitingApproval(result) ? '命令已暂停，等待技能审批。' : result.success ? `命令已通过 ${result.route} 路由处理。` : result.error ?? '命令执行失败。',
      success: result.success,
      status: isCommandWaitingApproval(result) ? 'pending_approval' : result.success ? 'success' : 'failed',
      timestamp: new Date().toISOString(),
    })
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === 'AbortError'
    const partialReply = sanitizeDisplayText(state.streamingReply)
    const item: CommandHistoryItem = {
      id: `${Date.now()}`,
      command: text,
      createdAt: new Date().toISOString(),
      response: {
        command_text: text,
        route: aborted ? (state.streamingRoute || 'stopped') : 'request_error',
        success: false,
        data: partialReply ? { final_response: partialReply, interrupted: true } : { interrupted: true },
        error: aborted ? '已停止当前任务' : error instanceof Error ? error.message : 'Unknown error',
      },
    }
    setState((current) => ({
      ...current,
      sessions: current.sessions.map((session) => {
        if (session.id !== targetSessionId) return session
        return {
          ...session,
          history: [item, ...session.history].slice(0, 20),
          draft: '',
          updatedAt: item.createdAt,
          title: session.history.length ? session.title : text.slice(0, 18) || '新会话',
        }
      }),
    }))
  } finally {
    abortController = null
    setState((current) => ({
      ...current,
      pendingCommand: '',
      running: false,
      runningSessionId: '',
      streamingReply: '',
      streamingRoute: '',
      streamingSuccess: true,
      streamingStatus: '正在分析并调用所需能力，请稍候...',
      activeRequestId: '',
    }))
  }
}

export async function resolveConversationApproval(historyItemId: string, approvalId: string, decision: 'approve' | 'reject') {
  const activeSession = getActiveSession(state)
  if (state.running || !activeSession) return

  abortController = new AbortController()
  const targetSessionId = activeSession.id

  setState((current) => ({
    ...current,
    running: true,
    runningSessionId: targetSessionId,
    streamingReply: '',
    streamingRoute: '',
    streamingSuccess: true,
    streamingStatus: decision === 'approve' ? '正在批准并继续执行...' : '正在拒绝并继续推理...',
    activeRequestId: approvalId,
  }))

  try {
    const result = await streamApprovalDecision(approvalId, decision, (event: CommandStreamEvent) => {
      if (event.type === 'request') {
        setState((current) => ({ ...current, activeRequestId: event.payload.request_id }))
        return
      }
      if (event.type === 'meta') {
        setState((current) => ({
          ...current,
          streamingRoute: event.payload.route,
          streamingSuccess: event.payload.success,
        }))
        return
      }
      if (event.type === 'status') {
        setState((current) => ({ ...current, streamingStatus: event.payload.text }))
        return
      }
      if (event.type === 'delta') {
        setState((current) => ({
          ...current,
          streamingReply: sanitizeDisplayText(current.streamingReply + event.payload.text),
        }))
      }
    }, abortController.signal)

    setState((current) => ({
      ...current,
      sessions: current.sessions.map((session) => {
        if (session.id !== targetSessionId) return session
        return {
          ...session,
          history: session.history.map((item) => {
            if (item.id !== historyItemId) return item
            return {
              ...item,
              response: result,
            }
          }),
          updatedAt: new Date().toISOString(),
        }
      }),
    }))
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    setState((current) => ({
      ...current,
      sessions: current.sessions.map((session) => {
        if (session.id !== targetSessionId) return session
        return {
          ...session,
          history: session.history.map((item) => {
            if (item.id !== historyItemId) return item
            return {
              ...item,
              response: {
                ...item.response,
                success: false,
                error: message,
              },
            }
          }),
        }
      }),
    }))
  } finally {
    abortController = null
    setState((current) => ({
      ...current,
      running: false,
      runningSessionId: '',
      streamingReply: '',
      streamingRoute: '',
      streamingSuccess: true,
      streamingStatus: '正在分析并调用所需能力，请稍候...',
      activeRequestId: '',
    }))
  }
}
