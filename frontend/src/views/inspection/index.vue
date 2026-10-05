<template>
  <section class="page" data-module="inspection">
    <header class="page-head">
      <div>
        <h2>安全检查台账</h2>
        <p class="page-desc">待办清单与爆破审批链实时同步：爆破完成进入爆后检查待办，存量跳级记录按人工签字保留并挂复核。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reload">刷新待办</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">待办总数</span>
        <strong class="stat-value">{{ total }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">爆后安全检查</span>
        <strong class="stat-value">{{ blastCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">存量跳级复核</span>
        <strong class="stat-value">{{ legacyCount }}</strong>
      </article>
    </div>

    <div class="filter-bar">
      <button class="btn" :class="{ ghost: filter !== '' }" type="button" @click="setFilter('')">全部</button>
      <button class="btn" :class="{ ghost: filter !== 'blast_check' }" type="button" @click="setFilter('blast_check')">爆后检查</button>
      <button class="btn" :class="{ ghost: filter !== 'legacy_review' }" type="button" @click="setFilter('legacy_review')">存量跳级复核</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>类别</th><th>爆破编号</th><th>爆破区域</th><th>当前审批状态</th><th>待办事项</th><th>产生时刻</th><th>经办人/签字</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="todo in todos" :key="todo.todo_id">
          <td>
            <span :class="['tag', todo.kind === 'legacy_review' ? 'tag-warn' : 'tag-danger']">{{ todo.kind_label }}</span>
          </td>
          <td>{{ todo.爆破编号 }}</td>
          <td>{{ todo.爆破区域 }}</td>
          <td><span :class="['tag', statusTag(todo.status)]">{{ todo.status }}</span></td>
          <td>{{ todo.title }}<div class="todo-meta">{{ todo.note }}</div></td>
          <td>{{ todo.created_at || '—' }}</td>
          <td>{{ todo.operator || '—' }}</td>
          <td class="row-actions">
            <router-link class="link" :to="`/explosive`">查看记录</router-link>
            <button v-if="todo.kind === 'blast_check'" class="link" type="button" @click="goCheck(todo.entry_id)">登记爆后检查</button>
            <button v-else class="link" type="button" @click="openReview(todo.entry_id)">复核签字</button>
          </td>
        </tr>
        <tr v-if="!todos.length">
          <td colspan="8" class="empty-state">安全检查台账暂无待办</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>待办由爆破审批链状态实时派生，不在台账内另存状态</span>
      <span v-if="feedback" :class="feedback.ok ? 'ok-text' : 'error-text'">{{ feedback.text }}</span>
    </footer>

    <div v-if="reviewTarget !== null" class="modal-mask" @click.self="reviewTarget = null">
      <div class="modal">
        <h3>存量跳级复核 · 爆破记录 #{{ reviewTarget }}</h3>
        <p class="page-desc">只核对当时的人工签字并销账，审批状态保持现状、不补造中间环节。</p>
        <div class="form-row">
          <label>复核意见（必填）</label>
          <textarea v-model="reviewOpinion" rows="3" placeholder="例如：纸质工单签字齐全，认可历史结论"></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="reviewTarget = null">取消</button>
          <button class="btn primary" type="button" @click="submitReview">确认复核</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Todo = {
  todo_id: string
  kind: 'blast_check' | 'legacy_review'
  kind_label: string
  entry_id: number
  爆破编号: string
  爆破区域: string
  status: string
  title: string
  created_at: string
  operator: string
  note: string
}
type ActionResponse = { ok: boolean; message: string }

const router = useRouter()
const session = useSessionStore()
const todos = ref<Todo[]>([])
const total = ref(0)
const blastCount = ref(0)
const legacyCount = ref(0)
const filter = ref('')
const feedback = ref<{ ok: boolean; text: string } | null>(null)
const reviewTarget = ref<number | null>(null)
const reviewOpinion = ref('')

function statusTag(status: string): string {
  if (status === '已检查') return 'tag-done'
  if (status === '已爆破') return 'tag-danger'
  return 'tag-warn'
}

function setFilter(kind: string) {
  filter.value = kind
  void reload()
}

async function reload() {
  feedback.value = null
  const suffix = filter.value ? `?kind=${filter.value}` : ''
  try {
    const response = await request(`/api/inspection/todos${suffix}`)
    if (!response.ok) throw new Error()
    const payload = await response.json()
    todos.value = payload.items ?? []
    total.value = payload.total ?? 0
    blastCount.value = payload.blast_check ?? 0
    legacyCount.value = payload.legacy_review ?? 0
  } catch {
    feedback.value = { ok: false, text: '安全检查台账读取失败' }
  }
}

function goCheck(entryId: number) {
  void router.push({ path: '/explosive' })
  // 爆后检查在爆破管理页执行，保证状态只在审批链上推进一处入口
}

function openReview(entryId: number) {
  reviewTarget.value = entryId
  reviewOpinion.value = ''
}

async function submitReview() {
  if (reviewTarget.value === null) return
  if (!reviewOpinion.value.trim()) {
    feedback.value = { ok: false, text: '复核意见必填' }
    return
  }
  const target = reviewTarget.value
  reviewTarget.value = null
  try {
    const response = await request(`/api/inspection/explosive/${target}/review`, {
      method: 'POST',
      body: JSON.stringify({ values: { actor: session.operator, opinion: reviewOpinion.value } }),
    })
    const result = (await response.json()) as ActionResponse
    feedback.value = { ok: result.ok, text: result.message }
    await reload()
  } catch {
    feedback.value = { ok: false, text: '复核提交失败，待办未销账' }
  }
}

onMounted(reload)
</script>
