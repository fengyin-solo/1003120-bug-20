<template>
  <section class="page" data-module="explosive">
    <header class="page-head">
      <div>
        <h2>爆破管理管理</h2>
        <p class="page-desc">审批链按 待审批 → 已审批 → 已爆破 → 已检查 顺序推进；跳级、倒序、重复提交、缺少结论的操作会被当场拒绝并说明原因。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出爆破管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>爆破编号</span>
        <input v-model="keyword" placeholder="按爆破编号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="ledgerPendingCount > 0" class="ledger-tip">
      有 {{ ledgerPendingCount }} 条爆后安全确认/历史复核待办在
      <RouterLink to="/safety-ledger">安全检查台账</RouterLink>
      等待处理。
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
          <th>明细</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span class="status-badge" :class="statusClass(row.status)">{{ row.status }}</span>
            <span v-if="row.needs_review" class="review-flag">待复核</span>
          </td>
          <td class="row-actions">
            <template v-if="nextAction(row.status)">
              <button class="link" type="button" @click="openAction(nextAction(row.status)!, row)">
                {{ nextAction(row.status) }}
              </button>
            </template>
            <span v-else class="muted">流程已完结</span>
          </td>
          <td><button class="link" type="button" @click="selected = row">查看留痕</button></td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无爆破管理数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条爆破管理记录</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <!-- 动作弹框：需要填写推进结论（审批签字/检查结论），没有结论不许提交 -->
    <div v-if="pending" class="modal-mask" @click.self="pending = null">
      <div class="modal-card">
        <h3>{{ pending.action }}</h3>
        <p class="muted">
          {{ pending.row['爆破编号'] }}：{{ pending.row.status }} → {{ targetStatus(pending.action) }}
        </p>
        <label class="form-item">
          <span>操作人</span>
          <input v-model="operator" placeholder="签字/操作人" />
        </label>
        <label class="form-item">
          <span>{{ requiresConclusion(pending.action) ? conclusionLabel(pending.action) : '备注（可选）' }}</span>
          <textarea v-model="conclusion" :rows="3" :placeholder="conclusionLabel(pending.action)"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="pending = null">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAction">
            {{ submitting ? '提交中…' : '确认提交' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 详情/留痕抽屉：回执、列表、详情以这里的状态为准 -->
    <div v-if="selected" class="modal-mask" @click.self="selected = null">
      <div class="modal-card wide">
        <h3>爆破记录明细 · {{ selected['爆破编号'] }}</h3>
        <p>
          当前状态：<span class="status-badge" :class="statusClass(selected.status)">{{ selected.status }}</span>
          <span v-if="selected.needs_review" class="review-flag">待复核</span>
        </p>
        <dl class="detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt><dd>{{ selected[column] ?? '—' }}</dd>
          </template>
        </dl>
        <h4>状态留痕</h4>
        <table v-if="historyOf(selected).length" class="data-table history-table">
          <thead>
            <tr><th>序</th><th>时刻</th><th>操作人</th><th>动作</th><th>状态变化</th><th>结论/备注</th></tr>
          </thead>
          <tbody>
            <tr v-for="h in historyOf(selected)" :key="h.seq">
              <td>{{ h.seq }}</td>
              <td>{{ h.time }}</td>
              <td>{{ h.operator }}<span v-if="h.backfilled" class="review-flag">历史补录</span></td>
              <td>{{ h.action }}</td>
              <td>{{ h.from_status }} → {{ h.to_status }}</td>
              <td>{{ h.conclusion || '—' }}<span v-if="h.note" class="muted">（{{ h.note }}）</span></td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">暂无状态留痕。</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="selected = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type HistoryItem = {
  seq: number
  time: string
  operator: string
  action: string
  from_status: string
  to_status: string
  conclusion: string
  note: string
  backfilled: boolean
}
type Row = Record<string, string | number | boolean | null | HistoryItem[]> & {
  id: number
  status: string
  history?: HistoryItem[]
  needs_review?: boolean
}

const session = useSessionStore()
const ENDPOINT = '/api/explosive'
const columns = ['爆破编号', '爆破区域', '炸药用量', '雷管用量', '爆破时间', '警戒范围', '爆破人员']
const statuses = ['待审批', '已审批', '已爆破', '已检查']
// 当前状态 -> 唯一允许的下一步动作；终态没有可执行动作
const NEXT_ACTION: Record<string, string> = {
  待审批: '提交审批',
  已审批: '执行爆破',
  已爆破: '爆后检查',
}
const TARGET_STATUS: Record<string, string> = {
  提交审批: '已审批',
  执行爆破: '已爆破',
  爆后检查: '已检查',
}

const rows = ref<Row[]>([])
const total = ref(0)
const keyword = ref('')
const statusFilter = ref('')
const message = ref('')
const messageOk = ref(true)
const ledgerPendingCount = ref(0)

const selected = ref<Row | null>(null)
const pending = ref<{ action: string; row: Row } | null>(null)
const operator = ref(session.operator)
const conclusion = ref('')
const submitting = ref(false)

const stats = computed(() => [
  { label: '待审批爆破', value: rows.value.filter((r) => r.status === '待审批').length },
  { label: '已爆破待检查', value: rows.value.filter((r) => r.status === '已爆破').length },
  { label: '已检查记录', value: rows.value.filter((r) => r.status === '已检查').length },
])

function nextAction(status: string): string | undefined {
  return NEXT_ACTION[status]
}
function targetStatus(action: string): string {
  return TARGET_STATUS[action] ?? ''
}
function requiresConclusion(action: string): boolean {
  return action === '提交审批' || action === '爆后检查'
}
function conclusionLabel(action: string): string {
  return action === '提交审批' ? '审批结论与签字（必填）' : '爆后安全检查结论（必填）'
}
function statusClass(status: string): string {
  return { 待审批: 'st-pending', 已审批: 'st-approved', 已爆破: 'st-fired', 已检查: 'st-checked' }[status] ?? ''
}
function historyOf(row: Row): HistoryItem[] {
  return row.history ?? []
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openAction(action: string, row: Row) {
  pending.value = { action, row }
  operator.value = session.operator
  conclusion.value = ''
  message.value = ''
}

async function submitAction() {
  if (!pending.value) return
  if (requiresConclusion(pending.value.action) && !conclusion.value.trim()) {
    messageOk.value = false
    message.value = conclusionLabel(pending.value.action).replace('（必填）', '') + '为空，不能推进'
    return
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${pending.value.row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          action: pending.value.action,
          operator: operator.value || session.operator,
          conclusion: conclusion.value,
        },
      }),
    })
    const payload = await response.json()
    messageOk.value = Boolean(payload.ok)
    message.value = payload.message || (payload.ok ? '操作已生效' : '操作未生效')
    if (payload.ok) {
      pending.value = null
      selected.value = null
      await reload()
    }
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '爆破管理操作失败'
  } finally {
    submitting.value = false
  }
}

async function reload() {
  message.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('爆破记录列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '爆破管理列表读取失败'
  }
  try {
    const resp = await request('/api/safety-ledger')
    if (resp.ok) {
      const data = await resp.json()
      ledgerPendingCount.value = data.total ?? 0
    }
  } catch {
    ledgerPendingCount.value = 0
  }
}

onMounted(reload)
</script>
