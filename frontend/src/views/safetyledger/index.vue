<template>
  <section class="page" data-module="safety-ledger">
    <header class="page-head">
      <div>
        <h2>安全检查台账</h2>
        <p class="page-desc">
          爆破记录进入“已爆破”后自动生成爆后安全确认待办；上线前已到终态、无法线上核验安全确认环节的历史记录挂这里等人工复核。
        </p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>类型</span>
        <select v-model="kindFilter">
          <option value="">全部类型</option>
          <option value="爆后安全检查">爆后安全检查</option>
          <option value="存量跳级复核">存量跳级复核</option>
        </select>
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="statusFilter">
          <option value="">待办（默认）</option>
          <option value="待检查">待检查</option>
          <option value="待复核">待复核</option>
          <option value="已核销">已核销</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>待办事项</th>
          <th>类型</th>
          <th>状态</th>
          <th>来源记录</th>
          <th>建立时刻</th>
          <th>建立人</th>
          <th>说明</th>
          <th>处理</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row.title }}</td>
          <td>{{ row.kind }}</td>
          <td><span class="status-badge" :class="row.status === '已核销' ? 'st-checked' : 'st-pending'">{{ row.status }}</span></td>
          <td>
            <RouterLink class="link" :to="`/explosive`">#{{ row.entry_id }}</RouterLink>
          </td>
          <td>{{ row.created_at || '—' }}</td>
          <td>{{ row.created_by || '—' }}</td>
          <td>{{ row.result || '—' }}</td>
          <td>
            <button v-if="row.kind === '存量跳级复核' && row.status !== '已核销'" class="link" type="button" @click="openReview(row)">
              登记复核
            </button>
            <span v-else-if="row.status === '已核销'" class="muted">{{ row.closed_by }} · {{ row.closed_at }}</span>
            <span v-else class="muted">请在爆破管理页完成爆后检查</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="8" class="empty-state">暂无待办，安全确认环节都已闭环</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条记录</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <div v-if="pending" class="modal-mask" @click.self="pending = null">
      <div class="modal-card">
        <h3>存量记录复核 · #{{ pending.entry_id }}</h3>
        <p class="muted">{{ pending.title }}</p>
        <p class="muted">{{ pending.result }}</p>
        <label class="form-item">
          <span>复核人</span>
          <input v-model="operator" placeholder="复核签字人" />
        </label>
        <label class="form-item">
          <span>复核结论（必填）</span>
          <textarea v-model="result" rows="3" placeholder="核对纸质审批/检查单据后写明结论"></textarea>
        </label>
        <label class="form-item">
          <span>确认后状态（可选）</span>
          <select v-model="confirmStatus">
            <option value="">保留原状态（尊重当时签字）</option>
            <option value="待审批">待审批</option>
            <option value="已审批">已审批</option>
            <option value="已爆破">已爆破</option>
            <option value="已检查">已检查</option>
          </select>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="pending = null">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitReview">
            {{ submitting ? '提交中…' : '确认复核并核销' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Todo = {
  id: number
  ref: string
  entry_id: number
  title: string
  kind: string
  status: string
  created_at: string
  created_by: string
  closed_at: string | null
  closed_by: string | null
  result: string
}

const session = useSessionStore()
const rows = ref<Todo[]>([])
const total = ref(0)
const kindFilter = ref('')
const statusFilter = ref('')
const message = ref('')
const messageOk = ref(true)

const pending = ref<Todo | null>(null)
const operator = ref(session.operator)
const result = ref('')
const confirmStatus = ref('')
const submitting = ref(false)

function openReview(row: Todo) {
  pending.value = row
  operator.value = session.operator
  result.value = ''
  confirmStatus.value = ''
  message.value = ''
}

async function submitReview() {
  if (!pending.value) return
  if (!result.value.trim()) {
    messageOk.value = false
    message.value = '请先填写复核结论'
    return
  }
  submitting.value = true
  try {
    const response = await request(`/api/safety-ledger/${pending.value.id}/review`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          operator: operator.value || session.operator,
          result: result.value,
          confirm_status: confirmStatus.value,
        },
      }),
    })
    const payload = await response.json()
    messageOk.value = Boolean(payload.ok)
    message.value = payload.message
    if (payload.ok) {
      pending.value = null
      await reload()
    }
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '复核提交失败'
  } finally {
    submitting.value = false
  }
}

async function reload() {
  message.value = ''
  const query = new URLSearchParams()
  if (kindFilter.value) query.set('kind', kindFilter.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  const response = await request(`/api/safety-ledger?${query.toString()}`)
  if (!response.ok) {
    messageOk.value = false
    message.value = '安全检查台账读取失败'
    return
  }
  const payload = await response.json()
  rows.value = payload.items ?? []
  total.value = payload.total ?? 0
}

onMounted(reload)
</script>
