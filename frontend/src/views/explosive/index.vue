<template>
  <section class="page" data-module="explosive">
    <header class="page-head">
      <div>
        <h2>爆破管理管理</h2>
        <p class="page-desc">爆破审批链严格按 待审批 → 已审批 → 已爆破 → 已检查 推进，每步留痕并同步安全检查台账。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记爆破记录</button>
        <button class="btn" type="button" @click="exportRows">导出爆破管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 安全检查台账待办：与审批链状态实时同步 -->
    <div class="todo-panel">
      <h3>安全检查台账待办（{{ todos.length }}）· 爆后检查 {{ todoCount.blast }} · 存量跳级复核 {{ todoCount.legacy }}</h3>
      <div v-if="todos.length" class="todo-list">
        <div v-for="todo in todos" :key="todo.todo_id" class="todo-item">
          <div>
            <span :class="['tag', todo.kind === 'legacy_review' ? 'tag-warn' : 'tag-danger']">{{ todo.kind_label }}</span>
            {{ todo.title }}
            <div class="todo-meta">来源动作 {{ todo.created_at }} · {{ todo.operator }}<span v-if="todo.note"> · {{ todo.note }}</span></div>
          </div>
          <span class="row-actions">
            <button class="link" type="button" @click="openDetail(todo.entry_id)">查看留痕</button>
            <button v-if="todo.kind === 'blast_check'" class="link" type="button" @click="runAction('爆后检查', todo.entry_id)">执行爆后检查</button>
            <button v-else class="link" type="button" @click="openReview(todo.entry_id)">复核人工签字</button>
          </span>
        </div>
      </div>
      <div v-else class="empty-state">安全检查台账暂无待办，爆后检查与存量复核都已销账</div>
    </div>

    <form class="filter-bar" @submit.prevent="() => reload()">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>审批状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span :class="['tag', statusTag(row.status)]">{{ row.status }}</span>
            <span v-if="row.legacy_skipped && !row.legacy_reviewed" class="tag tag-warn">待复核</span>
            <span v-else-if="row.legacy_skipped" class="tag tag-done">已复核</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(Number(row.id))">详情/留痕</button>
            <template v-if="canOperate(row)">
              <button
                v-if="row.status === '待审批'"
                class="link"
                type="button"
                @click="openApproval(Number(row.id))"
              >提交审批</button>
              <button
                v-if="row.status === '已审批' && !safetyConfirmed(row)"
                class="link"
                type="button"
                @click="runAction('安全确认', Number(row.id))"
              >安全确认</button>
              <button
                v-if="row.status === '已审批' && safetyConfirmed(row)"
                class="link"
                type="button"
                :disabled="!safetyConfirmed(row)"
                @click="runAction('执行爆破', Number(row.id))"
              >执行爆破</button>
              <button
                v-if="row.status === '已爆破'"
                class="link"
                type="button"
                @click="runAction('爆后检查', Number(row.id))"
              >爆后检查</button>
            </template>
            <span v-else-if="row.legacy_skipped && !row.legacy_reviewed" class="todo-meta">待复核锁定</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无爆破管理数据，可先登记爆破记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条爆破管理记录</span>
      <span v-if="feedback" :class="feedback.ok ? 'ok-text' : 'error-text'">{{ feedback.text }}</span>
    </footer>

    <!-- 审批结论弹窗：没有结论不许提交 -->
    <div v-if="approvalTarget" class="modal-mask" @click.self="approvalTarget = null">
      <div class="modal">
        <h3>提交审批 · 爆破记录 #{{ approvalTarget }}</h3>
        <div class="form-row">
          <label>审批结论（必填）</label>
          <select v-model="approvalConclusion">
            <option value="同意">同意</option>
            <option value="同意，限本班次执行">同意，限本班次执行</option>
            <option value="不同意，退回补充措施">不同意，退回补充措施</option>
          </select>
        </div>
        <div class="form-row">
          <label>补充说明</label>
          <textarea v-model="approvalRemark" rows="3" placeholder="瓦斯检查、药量核对等审批说明"></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="approvalTarget = null">取消</button>
          <button class="btn primary" type="button" @click="submitApproval">提交审批结论</button>
        </div>
      </div>
    </div>

    <!-- 存量跳级复核弹窗 -->
    <div v-if="reviewTarget" class="modal-mask" @click.self="reviewTarget = null">
      <div class="modal">
        <h3>存量跳级复核 · 爆破记录 #{{ reviewTarget }}</h3>
        <p class="page-desc">该记录当时按人工签字保留状态，复核只核对签字并销账，不回改、不补造审批链。</p>
        <div class="form-row">
          <label>复核意见（必填）</label>
          <textarea v-model="reviewOpinion" rows="3" placeholder="例如：纸质工单 BH-2026-xxxx 签字齐全，认可历史结论"></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="reviewTarget = null">取消</button>
          <button class="btn primary" type="button" @click="submitReview">确认复核</button>
        </div>
      </div>
    </div>

    <!-- 详情与留痕弹窗：回执、列表、详情读到的状态在这里对账 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <h3>爆破记录 #{{ detail.entry_id }} · {{ detail.爆破编号 }}</h3>
        <p>
          当前状态：<span :class="['tag', statusTag(detail.status)]">{{ detail.status }}</span>
          <span v-if="detail.legacy_skipped && !detail.legacy_reviewed" class="tag tag-warn">存量跳级·待复核</span>
          <span v-else-if="detail.legacy_skipped" class="tag tag-done">存量跳级·已复核</span>
        </p>
        <ul class="trace-list">
          <li v-for="(item, idx) in detail.history" :key="idx" :class="{ 'trace-legacy': item.source === 'legacy' }">
            <strong>{{ item.action }}：{{ item.from_status || '—' }} → {{ item.to_status }}</strong>
            <div class="trace-meta">{{ item.at }} · {{ item.actor }}<span v-if="item.source === 'legacy'"> · 历史人工签字</span></div>
            <div v-if="item.note">{{ item.note }}</div>
          </li>
        </ul>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Trace = {
  at: string
  actor: string
  action: string
  from_status: string
  to_status: string
  note: string
  source: string
}
type Row = Record<string, string | number | boolean | Trace[] | null> & {
  id: number
  status: string
  history?: Trace[]
  legacy_skipped?: boolean
  legacy_reviewed?: boolean
}
type Todo = {
  todo_id: string
  kind: 'blast_check' | 'legacy_review'
  kind_label: string
  entry_id: number
  title: string
  created_at: string
  operator: string
  note: string
}
type ActionResponse = { ok: boolean; message: string; entry?: Row }
type HistoryResponse = {
  entry_id: number
  爆破编号: string
  status: string
  legacy_skipped: boolean
  legacy_reviewed: boolean
  history: Trace[]
}

const ENDPOINT = '/api/explosive'
const session = useSessionStore()
const columns = ["爆破编号", "爆破区域", "炸药用量", "雷管用量", "爆破时间", "警戒范围", "爆破人员"]
const filterFields = columns.slice(0, 3)

const rows = ref<Row[]>([])
const total = ref(0)
const todos = ref<Todo[]>([])
const filters = ref<Record<string, string>>({})
const feedback = ref<{ ok: boolean; text: string } | null>(null)

const approvalTarget = ref<number | null>(null)
const approvalConclusion = ref('同意')
const approvalRemark = ref('')
const reviewTarget = ref<number | null>(null)
const reviewOpinion = ref('')
const detail = ref<HistoryResponse | null>(null)

const stats = computed(() => [
  { label: '待审批爆破', value: rows.value.filter((r) => r.status === '待审批').length },
  { label: '已爆破待检查', value: rows.value.filter((r) => r.status === '已爆破').length },
  { label: '已检查记录', value: rows.value.filter((r) => r.status === '已检查').length },
  { label: '待复核存量', value: rows.value.filter((r) => r.legacy_skipped && !r.legacy_reviewed).length },
])
const todoCount = computed(() => ({
  blast: todos.value.filter((t) => t.kind === 'blast_check').length,
  legacy: todos.value.filter((t) => t.kind === 'legacy_review').length,
}))

function statusTag(status: string): string {
  if (status === '待审批') return 'tag-warn'
  if (status === '已检查') return 'tag-done'
  if (status === '已爆破') return 'tag-danger'
  return ''
}

function canOperate(row: Row): boolean {
  return !(row.legacy_skipped && !row.legacy_reviewed)
}

function safetyConfirmed(row: Row): boolean {
  return Boolean(row.history?.some((item) => item.action === '安全确认'))
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  feedback.value = { ok: false, text: '爆破记录登记入口尚未接入审批流' }
}

async function postAction(url: string, body: Record<string, unknown>): Promise<ActionResponse | null> {
  try {
    const response = await request(url, { method: 'POST', body: JSON.stringify(body) })
    return (await response.json()) as ActionResponse
  } catch {
    return null
  }
}

async function applyResult(result: ActionResponse | null) {
  if (!result) {
    feedback.value = { ok: false, text: '接口请求失败，状态未变更' }
    return
  }
  feedback.value = { ok: result.ok, text: result.message }
  await Promise.all([reload(false), loadTodos()])
}

async function runAction(action: string, entryId: number) {
  feedback.value = null
  const url = action === '安全确认'
    ? `${ENDPOINT}/${entryId}/safety-confirm`
    : `${ENDPOINT}/${entryId}/actions`
  const values: Record<string, unknown> = { actor: session.operator }
  if (action !== '安全确认') values.action = action
  const result = await postAction(url, { values, remark: action === '安全确认' ? '' : undefined })
  await applyResult(result)
}

function openApproval(entryId: number) {
  approvalTarget.value = entryId
  approvalConclusion.value = '同意'
  approvalRemark.value = ''
}

async function submitApproval() {
  if (approvalTarget.value === null) return
  if (!approvalConclusion.value.trim()) {
    feedback.value = { ok: false, text: '审批结论必填，没有结论不许跳过审批环节' }
    return
  }
  const target = approvalTarget.value
  approvalTarget.value = null
  const result = await postAction(`${ENDPOINT}/${target}/actions`, {
    values: { action: '提交审批', actor: session.operator, conclusion: approvalConclusion.value },
    remark: approvalRemark.value || undefined,
  })
  await applyResult(result)
}

function openReview(entryId: number) {
  reviewTarget.value = entryId
  reviewOpinion.value = ''
  void openDetail(entryId)
}

async function submitReview() {
  if (reviewTarget.value === null) return
  if (!reviewOpinion.value.trim()) {
    feedback.value = { ok: false, text: '复核意见必填' }
    return
  }
  const target = reviewTarget.value
  reviewTarget.value = null
  const result = await postAction(`/api/inspection/explosive/${target}/review`, {
    values: { actor: session.operator, opinion: reviewOpinion.value },
  })
  await applyResult(result)
}

async function openDetail(entryId: number) {
  try {
    const response = await request(`${ENDPOINT}/${entryId}/history`)
    if (!response.ok) throw new Error()
    detail.value = (await response.json()) as HistoryResponse
  } catch {
    feedback.value = { ok: false, text: '留痕读取失败' }
  }
}

async function loadTodos() {
  try {
    const response = await request('/api/inspection/todos')
    if (response.ok) {
      const payload = await response.json()
      todos.value = (payload.items ?? []) as Todo[]
    }
  } catch {
    // 待办面板保持上一次结果，不打断列表操作
  }
}

async function reload(clearFeedback = true) {
  if (clearFeedback) feedback.value = null
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) throw new Error()
    const payload = await response.json()
    rows.value = (payload.items ?? []) as Row[]
    total.value = payload.total ?? rows.value.length
  } catch {
    feedback.value = { ok: false, text: '爆破记录列表读取失败' }
  }
}

onMounted(async () => {
  await Promise.all([reload(false), loadTodos()])
})
</script>
