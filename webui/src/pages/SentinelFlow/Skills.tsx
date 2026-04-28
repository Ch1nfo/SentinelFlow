import { useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, RefreshCw, Search, Sparkles } from 'lucide-react'
import { createSkill, debugSkill, deleteSkill, fetchSkillDetail, fetchSkills, saveSkill, type SkillDebugResponse, type SkillDetail, type SkillSummary } from '@/api/sentinelflow'
import KeyValueList from '@/components/sentinelflow/KeyValueList'
import JsonPreview from '@/components/sentinelflow/JsonPreview'
import StatusBadge from '@/components/sentinelflow/StatusBadge'
import Surface from '@/components/sentinelflow/Surface'
import PageHeader from '@/components/common/PageHeader'
import { brand, withProductName } from '@/config/brand'
import { useSentinelFlowAsyncData } from '@/hooks/useSentinelFlowAsyncData'

function getSkillTypeLabel(type: string) {
  if (type === 'doc') return '纯文本（Markdown）'
  if (type === 'hybrid') return '文本 + 可执行'
  return type
}

const DEFAULT_COMPLETION_POLICY = {
  enabled: false,
  action_kind: 'other',
  completion_effect: 'none',
}

const COMPLETION_ACTION_OPTIONS = [
  { value: 'ban_ip', label: '封禁 IP' },
  { value: 'notify', label: '通知' },
  { value: 'closure', label: '结单闭环' },
  { value: 'collect_context', label: '上下文查询' },
  { value: 'other', label: '其他' },
]

const COMPLETION_EFFECT_OPTIONS = [
  { value: 'containment', label: '遏制/封禁' },
  { value: 'notification', label: '通知人工' },
  { value: 'closure', label: '结单闭环' },
  { value: 'none', label: '不作为闭环条件' },
]

function completionPolicyLabel(policy: SkillSummary['completion_policy'] | undefined): string {
  if (!policy?.enabled) return '未参与'
  const action = COMPLETION_ACTION_OPTIONS.find((item) => item.value === policy.action_kind)?.label ?? policy.action_kind
  const effect = COMPLETION_EFFECT_OPTIONS.find((item) => item.value === policy.completion_effect)?.label ?? policy.completion_effect
  return `${action} / ${effect}`
}

export default function SentinelFlowSkillsPage() {
  const { data, loading, error, reload } = useSentinelFlowAsyncData(fetchSkills, [])
  const detailPanelRef = useRef<HTMLDivElement | null>(null)
  const skillListPanelRef = useRef<HTMLDivElement | null>(null)
  const [selectedSkill, setSelectedSkill] = useState<SkillSummary | null>(null)
  const [detail, setDetail] = useState<SkillDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [editingSkillName, setEditingSkillName] = useState<string | null>(null)
  const [debuggingSkillName, setDebuggingSkillName] = useState<string | null>(null)
  const [debugRunning, setDebugRunning] = useState(false)
  const [debugInput, setDebugInput] = useState('{\n  "ip": "198.51.100.10"\n}')
  const [debugOutput, setDebugOutput] = useState<SkillDebugResponse | null>(null)
  const [debugError, setDebugError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [skillListPanelHeight, setSkillListPanelHeight] = useState<number | null>(null)
  const [skillListMaxHeight, setSkillListMaxHeight] = useState<number | null>(null)
  const [draft, setDraft] = useState({
    name: '',
    description: '',
    type: 'doc',
    mode: 'subprocess',
    content: '',
    code: '',
    approvalRequired: false,
    completionPolicy: { ...DEFAULT_COMPLETION_POLICY },
  })

  useEffect(() => {
    const first = data?.skills?.[0] ?? null
    setSelectedSkill((prev) => prev ?? first)
  }, [data])

  useEffect(() => {
    if (!selectedSkill) {
      setDetail(null)
      return
    }
    setDetailError(null)
    fetchSkillDetail(selectedSkill.name).then(setDetail).catch((err) => {
      setDetailError(err instanceof Error ? err.message : 'Unknown error')
      })
  }, [selectedSkill])

  const filteredSkills = useMemo(() => {
    const skills = data?.skills ?? []
    const query = searchQuery.trim().toLowerCase()
    if (!query) return skills
    return skills.filter((skill) => {
      const haystack = `${skill.name} ${skill.description} ${skill.type} ${skill.mode ?? ''}`.toLowerCase()
      return haystack.includes(query)
    })
  }, [data?.skills, searchQuery])

  useEffect(() => {
    const detailNode = detailPanelRef.current
    const listPanelNode = skillListPanelRef.current
    if (!detailNode || !listPanelNode || typeof ResizeObserver === 'undefined') return

    const syncHeight = () => {
      try {
        const detailHeight = Math.max(0, Math.round(detailNode.getBoundingClientRect().height))
        const scrollNode = listPanelNode.querySelector('.sentinelflow-skill-list-scroll') as HTMLDivElement | null
        const scrollHeight = scrollNode?.offsetHeight ?? 0
        const chromeHeight = Math.max(0, Math.round(listPanelNode.offsetHeight - scrollHeight))
        const nextHeight = Math.max(0, detailHeight - chromeHeight)
        setSkillListPanelHeight(detailHeight || null)
        setSkillListMaxHeight(nextHeight || null)
      } catch {
        setSkillListPanelHeight(null)
        setSkillListMaxHeight(null)
      }
    }

    try {
      syncHeight()
      const observer = new ResizeObserver(() => syncHeight())
      observer.observe(detailNode)
      observer.observe(listPanelNode)
      return () => observer.disconnect()
    } catch {
      setSkillListPanelHeight(null)
      setSkillListMaxHeight(null)
      return
    }
  }, [detail, detailError, filteredSkills.length, loading, error])

  async function handleRefresh() {
    if (refreshing) return
    setRefreshing(true)
    try {
      await reload()
    } finally {
      setRefreshing(false)
    }
  }

  async function handleCreateSkill() {
    if (!draft.name.trim() || !draft.description.trim() || !draft.content.trim()) return
    if (draft.type === 'hybrid' && !draft.code.trim()) return
    setCreating(true)
    setFormError(null)
    try {
      const created = await createSkill(draft)
      await reload()
      setSelectedSkill({
        name: created.name,
        description: created.description,
        type: created.type,
        executable: created.executable,
        approval_required: created.approval_required,
        completion_policy: created.completion_policy,
        entry: created.entry,
        mode: created.mode,
      })
      setDetail(created)
      setDraft({ name: '', description: '', type: 'doc', mode: 'subprocess', content: '', code: '', approvalRequired: false, completionPolicy: { ...DEFAULT_COMPLETION_POLICY } })
      setEditingSkillName(null)
    } catch (error) {
      setFormError(error instanceof Error ? error.message : '创建 Skill 失败。')
    } finally {
      setCreating(false)
    }
  }

  async function handleSaveSkill() {
    if (!editingSkillName || !draft.description.trim() || !draft.content.trim()) return
    if (draft.type === 'hybrid' && !draft.code.trim()) return
    setSaving(true)
    setFormError(null)
    try {
      const saved = await saveSkill(editingSkillName, draft)
      setDetail(saved)
      setSelectedSkill({
        name: saved.name,
        description: saved.description,
        type: saved.type,
        executable: saved.executable,
        approval_required: saved.approval_required,
        completion_policy: saved.completion_policy,
        entry: saved.entry,
        mode: saved.mode,
      })
      await reload()
      setEditingSkillName(null)
      setDebuggingSkillName(null)
      setDraft({ name: '', description: '', type: 'doc', mode: 'subprocess', content: '', code: '', approvalRequired: false, completionPolicy: { ...DEFAULT_COMPLETION_POLICY } })
      setDebugInput('{\n  "ip": "198.51.100.10"\n}')
      setDebugOutput(null)
      setDebugError(null)
    } catch (error) {
      setFormError(error instanceof Error ? error.message : '保存 Skill 失败。')
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteSkill() {
    if (!selectedSkill || deleting) return
    const confirmed = window.confirm(`确认删除 Skill “${selectedSkill.name}”吗？`)
    if (!confirmed) return
    setDeleting(true)
    try {
      await deleteSkill(selectedSkill.name)
      await reload()
      setSelectedSkill(null)
      setDetail(null)
      setEditingSkillName(null)
      setDraft({ name: '', description: '', type: 'doc', mode: 'subprocess', content: '', code: '', approvalRequired: false, completionPolicy: { ...DEFAULT_COMPLETION_POLICY } })
    } finally {
      setDeleting(false)
    }
  }

  function handleStartEdit() {
    if (!detail) return
    setEditingSkillName(detail.name)
    setDebuggingSkillName(null)
    setFormError(null)
    setDraft({
      name: detail.name,
      description: detail.description,
      type: detail.type,
      mode: detail.mode ?? 'subprocess',
      content: detail.markdown,
      code: detail.code ?? '',
      approvalRequired: detail.approval_required,
      completionPolicy: { ...DEFAULT_COMPLETION_POLICY, ...(detail.completion_policy ?? {}) },
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function handleCancelEdit() {
    setEditingSkillName(null)
    setDebuggingSkillName(null)
    setFormError(null)
    setDraft({ name: '', description: '', type: 'doc', mode: 'subprocess', content: '', code: '', approvalRequired: false, completionPolicy: { ...DEFAULT_COMPLETION_POLICY } })
    setDebugInput('{\n  "ip": "198.51.100.10"\n}')
    setDebugOutput(null)
    setDebugError(null)
  }

  function handleStartDebug() {
    if (!detail) return
    setEditingSkillName(detail.name)
    setDebuggingSkillName(detail.name)
    setFormError(null)
    setDraft({
      name: detail.name,
      description: detail.description,
      type: detail.type,
      mode: detail.mode ?? 'subprocess',
      content: detail.markdown,
      code: detail.code ?? '',
      approvalRequired: detail.approval_required,
      completionPolicy: { ...DEFAULT_COMPLETION_POLICY, ...(detail.completion_policy ?? {}) },
    })
    setDebugOutput(null)
    setDebugError(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function handleRunDebug() {
    if (!debuggingSkillName) return
    setDebugRunning(true)
    setDebugError(null)
    try {
      let parsedInput: Record<string, unknown> = {}
      try {
        parsedInput = debugInput.trim() ? JSON.parse(debugInput) as Record<string, unknown> : {}
      } catch {
        setDebugOutput(null)
        setDebugError('输入参数不是合法的 JSON。')
        return
      }
      const result = await debugSkill(debuggingSkillName, { arguments: parsedInput })
      setDebugOutput(result)
    } finally {
      setDebugRunning(false)
    }
  }

  const completionPolicyControls = (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <label className="flex items-center gap-2 text-sm font-semibold text-gray-900">
        <input
          type="checkbox"
          checked={draft.completionPolicy.enabled}
          onChange={(event) => setDraft((current) => ({
            ...current,
            completionPolicy: {
              ...current.completionPolicy,
              enabled: event.target.checked,
            },
          }))}
        />
        参与自动处置闭环
      </label>
      <div className="mt-1 text-xs leading-5 text-gray-500">
        勾选后，该 Skill 的成功执行可作为自动处置完成条件；未勾选的旧 Skill 不参与闭环判定。
      </div>
      {draft.completionPolicy.enabled ? (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <select
            className="sentinelflow-settings-input"
            value={draft.completionPolicy.action_kind}
            onChange={(event) => setDraft((current) => ({
              ...current,
              completionPolicy: {
                ...current.completionPolicy,
                action_kind: event.target.value,
              },
            }))}
          >
            {COMPLETION_ACTION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <select
            className="sentinelflow-settings-input"
            value={draft.completionPolicy.completion_effect}
            onChange={(event) => setDraft((current) => ({
              ...current,
              completionPolicy: {
                ...current.completionPolicy,
                completion_effect: event.target.value,
              },
            }))}
          >
            {COMPLETION_EFFECT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </div>
      ) : null}
    </div>
  )

  return (
    <div className="sentinelflow-page-stack">
      <PageHeader
        title={`${brand.productName} Skills`}
        description={withProductName('管理平台可读取和可执行的 Skills。')}
        icon={<BookOpen className="w-8 h-8" />}
        action={
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="搜索 Skill"
                className="w-56 rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
              />
            </div>
            <button
              type="button"
              onClick={() => void handleRefresh()}
              className="rounded-lg border border-gray-300 p-2 text-gray-600 transition-colors hover:bg-gray-50"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            </button>
          </div>
        }
      />

      <Surface title={`${brand.productName} Skills`} subtitle={withProductName('这里统一管理“纯文本（Markdown）”与“文本 + 可执行”两类 Skills。')}>
        <div className="mb-4 grid gap-3 md:grid-cols-2">
          <button
            type="button"
            onClick={() => setDraft((current) => ({ ...current, type: 'doc' }))}
            className={`rounded-xl border bg-white p-4 text-left transition-all ${
              draft.type === 'doc'
                ? 'border-sky-500 ring-2 ring-sky-100'
                : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            <div className="text-sm font-semibold text-gray-900">纯文本（Markdown）</div>
            <div className="mt-2 text-sm leading-6 text-gray-600">
              只包含 Markdown 文档，用来提供说明、规范、研判指南或操作指引。
            </div>
          </button>
          <button
            type="button"
            onClick={() => setDraft((current) => ({ ...current, type: 'hybrid' }))}
            className={`rounded-xl border bg-white p-4 text-left transition-all ${
              draft.type === 'hybrid'
                ? 'border-sky-500 ring-2 ring-sky-100'
                : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            <div className="text-sm font-semibold text-gray-900">文本 + 可执行</div>
            <div className="mt-2 text-sm leading-6 text-gray-600">
              同时包含 Markdown 文档和 `main.py` 代码，适合给 Agent 先读文档再执行。
            </div>
          </button>
        </div>

        <div className="mb-4 rounded-xl border border-gray-200 bg-white p-4">
          <div className="mb-3 text-sm font-semibold text-gray-900">
            {debuggingSkillName ? `调试 Skill：${debuggingSkillName}` : editingSkillName ? `编辑 Skill：${editingSkillName}` : '新建 Skill'}
          </div>
          {formError ? <div className="mb-3 sentinelflow-message-block sentinelflow-message-error">{formError}</div> : null}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <input className="sentinelflow-settings-input" placeholder="Skill 名称，如 ip-investigate" value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} disabled={Boolean(editingSkillName)} />
            <input className="sentinelflow-settings-input" placeholder="描述" value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} />
            {editingSkillName ? (
              <div className="flex gap-3">
                <button type="button" className="sentinelflow-primary-button flex-1" onClick={() => void handleSaveSkill()} disabled={saving}>
                  {saving ? '保存中...' : '保存更改'}
                </button>
                <button type="button" className="sentinelflow-ghost-button" onClick={handleCancelEdit} disabled={saving}>
                  {debuggingSkillName ? '退出调试' : '取消编辑'}
                </button>
              </div>
            ) : (
              <button type="button" className="sentinelflow-primary-button" onClick={() => void handleCreateSkill()} disabled={creating}>
                {creating ? '创建中...' : '新建 Skill'}
              </button>
            )}
          </div>
          {debuggingSkillName ? (
            <div className="mt-3 grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <textarea className="sentinelflow-command-input" rows={8} placeholder="Skill 文档内容（Markdown，必填）" value={draft.content} onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))} />
                {draft.type === 'hybrid' ? (
                  <div className="space-y-1">
                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input type="checkbox" checked={draft.approvalRequired} onChange={(event) => setDraft((current) => ({ ...current, approvalRequired: event.target.checked }))} />
                      执行需审批（仅对对话 / 手动单告警生效，每次执行都需单独审批）
                    </label>
                    <div className="text-xs text-gray-500">
                      自动执行、自动重试和 Skill 调试会直接执行，不会等待人工审批。
                    </div>
                  </div>
                ) : null}
                {draft.type === 'hybrid' ? completionPolicyControls : null}
                {draft.type === 'hybrid' ? (
                  <textarea className="sentinelflow-command-input font-mono" rows={12} placeholder="可执行代码（保存为 main.py）" value={draft.code} onChange={(event) => setDraft((current) => ({ ...current, code: event.target.value }))} />
                ) : null}
              </div>
              <div className="space-y-3">
                <div>
                  <div className="mb-2 text-sm font-semibold text-gray-900">输入参数（JSON）</div>
                  <textarea className="sentinelflow-command-input font-mono" rows={8} value={debugInput} onChange={(event) => setDebugInput(event.target.value)} />
                </div>
                <div>
                  <div className="mb-2 flex items-center justify-between text-sm font-semibold text-gray-900">
                    <span>输出结果</span>
                    <button type="button" className="sentinelflow-primary-button" onClick={() => void handleRunDebug()} disabled={debugRunning}>
                      {debugRunning ? '运行中...' : '运行'}
                    </button>
                  </div>
                  {debugError ? <div className="sentinelflow-message-block sentinelflow-message-error">{debugError}</div> : null}
                  <div className="rounded-xl border border-gray-200 bg-white p-3">
                    <JsonPreview value={debugOutput ?? { hint: '运行后将在这里显示输出结果。' }} />
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <>
              <textarea className="sentinelflow-command-input mt-3" rows={8} placeholder="Skill 文档内容（Markdown，必填）" value={draft.content} onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))} />
              {draft.type === 'hybrid' ? (
                <div className="mt-3 space-y-1">
                  <label className="flex items-center gap-2 text-sm text-gray-700">
                    <input type="checkbox" checked={draft.approvalRequired} onChange={(event) => setDraft((current) => ({ ...current, approvalRequired: event.target.checked }))} />
                    执行需审批（仅对对话 / 手动单告警生效，每次执行都需单独审批）
                  </label>
                  <div className="text-xs text-gray-500">
                    自动执行、自动重试和 Skill 调试会直接执行，不会等待人工审批。
                  </div>
                </div>
              ) : null}
              {draft.type === 'hybrid' ? <div className="mt-3">{completionPolicyControls}</div> : null}
              {draft.type === 'hybrid' ? (
                <textarea className="sentinelflow-command-input mt-3 font-mono" rows={10} placeholder="可执行代码（保存为 main.py）" value={draft.code} onChange={(event) => setDraft((current) => ({ ...current, code: event.target.value }))} />
              ) : null}
            </>
          )}
        </div>

        <div className="mb-4 grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <Sparkles className="h-4 w-4 text-sky-500" />
              Skill 总数
            </div>
            <div className="text-3xl font-bold text-gray-900">{data?.skills?.length ?? 0}</div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-2 text-sm font-semibold text-gray-900">文本 + 可执行</div>
            <div className="text-3xl font-bold text-gray-900">{(data?.skills ?? []).filter((skill) => skill.executable).length}</div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-2 text-sm font-semibold text-gray-900">纯文本（Markdown）</div>
            <div className="text-3xl font-bold text-gray-900">{(data?.skills ?? []).filter((skill) => skill.type === 'doc').length}</div>
          </div>
        </div>

        <div className="sentinelflow-grid-2">
          <div
            ref={skillListPanelRef}
            className="sentinelflow-detail-panel h-auto overflow-hidden"
            style={skillListPanelHeight ? { height: `${skillListPanelHeight}px` } : undefined}
          >
            <h3>可用 Skills</h3>
            <div
              className="sentinelflow-skill-list-scroll"
              style={skillListMaxHeight ? { maxHeight: `${skillListMaxHeight}px` } : undefined}
            >
              <table className="sentinelflow-data-table">
                <thead>
                  <tr><th>Skill</th><th>类型</th><th>是否可执行</th></tr>
                </thead>
                <tbody>
                  {loading ? <tr><td colSpan={3}>正在加载 Skills...</td></tr> : null}
                  {error ? <tr><td colSpan={3}>加载失败：{error}</td></tr> : null}
                  {!loading && !error ? filteredSkills.map((skill) => (
                    <tr key={skill.name} className={selectedSkill?.name === skill.name ? 'sentinelflow-table-row-active' : ''} onClick={() => setSelectedSkill(skill)}>
                      <td>{skill.name}</td>
                      <td>{getSkillTypeLabel(skill.type)}</td>
                      <td>{skill.executable ? '是' : '否'}</td>
                    </tr>
                  )) : null}
                  {!loading && !error && filteredSkills.length === 0 ? <tr><td colSpan={3}>没有匹配的 Skill。</td></tr> : null}
                </tbody>
              </table>
            </div>
          </div>
          <div ref={detailPanelRef} className="sentinelflow-detail-panel h-auto self-start">
            <h3>{detail?.name ?? 'Skill 详情'}</h3>
            <p className="sentinelflow-muted-text">{detail?.description ?? '选择一个 Skill 查看说明文档。'}</p>
            {detail ? (
              <KeyValueList
                items={[
                  { label: '类型', value: getSkillTypeLabel(detail.type) },
                  { label: '可执行', value: detail.executable ? '是' : '否' },
                  { label: '执行审批', value: detail.approval_required ? '需要审批（仅对对话 / 手动单告警；每次执行都需单独审批）' : '直接执行' },
                  { label: '自动处置闭环', value: completionPolicyLabel(detail.completion_policy) },
                ]}
              />
            ) : null}
            {detail?.executable ? <StatusBadge tone="success">可执行</StatusBadge> : null}
            {detail?.approval_required ? <StatusBadge tone="warn">执行需审批（对话 / 手动单告警；每次执行都需单独审批）</StatusBadge> : null}
            {detail?.completion_policy?.enabled ? <StatusBadge tone="info">参与自动处置闭环</StatusBadge> : null}
            {detail?.approval_required ? <div className="mt-2 text-xs text-gray-500">自动执行、自动重试和调试当前 Skill 时会直接执行，不会停在审批状态；对话和手动单告警场景下，每次实际执行都会重新发起审批。</div> : null}
            {detailError ? <div className="sentinelflow-message-block sentinelflow-message-error">{detailError}</div> : null}
            {detail ? (
              <div className="mt-4 space-y-3">
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <div className="mb-2 text-sm font-semibold text-gray-900">Markdown 文档</div>
                  <div className="max-h-72 overflow-auto rounded-lg border border-gray-100 bg-gray-50 p-4">
                    <pre className="whitespace-pre-wrap break-words text-sm leading-6 text-gray-700">{detail.markdown}</pre>
                  </div>
                </div>
                {detail.type === 'hybrid' ? (
                  <div className="rounded-xl border border-gray-200 bg-white p-4">
                    <div className="mb-2 text-sm font-semibold text-gray-900">可执行代码（main.py）</div>
                    <div className="max-h-72 overflow-auto rounded-lg border border-gray-100 bg-gray-50 p-4">
                      <pre className="whitespace-pre-wrap break-words font-mono text-sm leading-6 text-gray-700">{detail.code || '# 暂无代码内容'}</pre>
                    </div>
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-3">
                  <button type="button" className="sentinelflow-primary-button" onClick={handleStartEdit}>
                    开始编辑
                  </button>
                  {detail.type === 'hybrid' ? (
                    <button type="button" className="sentinelflow-ghost-button" onClick={handleStartDebug}>
                      调试当前 Skill
                    </button>
                  ) : null}
                  <button type="button" className="sentinelflow-ghost-button" onClick={() => void handleDeleteSkill()} disabled={deleting}>
                    {deleting ? '删除中...' : '删除 Skill'}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </Surface>
    </div>
  )
}
