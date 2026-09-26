<template>
  <section class="page" data-module="review">
    <header class="page-head">
      <div>
        <h2>结果复核管理</h2>
        <p class="page-desc">维护复核记录，围绕复核编号、关联结果、复核项目、复核人做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记复核记录</button>
        <button class="btn" type="button" @click="exportRows">导出结果复核清单</button>
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
        <span>复核编号</span>
        <input v-model="keyword" placeholder="按复核编号检索" />
      </label>
      <label class="filter-item">
        <span>复核状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <span>已勾选 {{ selectedIds.length }} 条待复核记录</span>
      <button class="btn primary" type="button" :disabled="!selectedIds.length" @click="openBatch('确认通过')">
        批量确认通过
      </button>
      <button class="btn" type="button" :disabled="!selectedIds.length" @click="openBatch('发起重测')">
        批量发起重测
      </button>
      <button v-if="selectedIds.length" class="btn ghost" type="button" @click="clearSelection">清空勾选</button>
    </div>

    <div v-if="failures.length" class="failure-panel">
      <p class="error-text">批量处理已整批拒绝，没有记录被改动，请逐条核对以下问题：</p>
      <ul>
        <li v-for="(failure, index) in failures" :key="index">
          <strong>{{ failure.复核编号 === '—' ? '整批' : failure.复核编号 }}</strong>：{{ failure.原因 }}
        </li>
      </ul>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input
              type="checkbox"
              :checked="allChecked"
              :disabled="!actionableRows.length"
              title="全选当前可处理的待复核记录"
              @change="toggleAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input
              type="checkbox"
              :checked="selectedIds.includes(Number(row.id))"
              :disabled="!isActionable(row)"
              :title="isActionable(row) ? '勾选后可批量处理' : '已进入终态，不能再批量处理'"
              @change="toggleOne(row)"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
          <td class="row-actions">
            <template v-if="isActionable(row)">
              <button class="link" type="button" @click="runAction('开始复核', row)">开始复核</button>
              <button class="link" type="button" @click="openBatch('确认通过', row)">确认通过</button>
              <button class="link" type="button" @click="openBatch('发起重测', row)">发起重测</button>
            </template>
            <span v-else class="muted-text">已处理</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">
            {{ statusFilter === '待复核'
              ? '当前没有待复核的记录，可切换状态或重置条件查看其他复核记录'
              : '暂无结果复核数据，可先登记复核记录' }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条结果复核记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="dialogAction" class="dialog-mask" @click.self="closeDialog">
      <div class="dialog">
        <h3>批量{{ dialogAction }}（{{ dialogRows.length }} 条）</h3>
        <p class="dialog-ids">复核编号：{{ dialogRows.map((row) => row['复核编号']).join('、') }}</p>
        <label class="dialog-field">
          <span>复核人</span>
          <input v-model="reviewer" placeholder="默认为当前值班人员" />
        </label>
        <label class="dialog-field">
          <span>复核意见（必填，对本批统一填写）</span>
          <textarea v-model="opinion" rows="3" placeholder="填写本批记录的统一复核意见"></textarea>
        </label>
        <label class="dialog-field">
          <span>差异说明（对本批统一填写）</span>
          <textarea v-model="diffNote" rows="2" placeholder="如复核数据与原始记录存在差异，请统一说明"></textarea>
        </label>
        <template v-if="dialogAction === '发起重测'">
          <p class="dialog-tip">以下条目将发起重测，必须逐条单独写明重测原因：</p>
          <label v-for="row in dialogRows" :key="String(row.id)" class="dialog-field">
            <span>{{ row['复核编号'] }} 的重测原因（必填）</span>
            <input v-model="retestReasons[String(row.id)]" placeholder="单独说明该条需要重测的原因" />
          </label>
        </template>
        <p v-if="dialogError" class="error-text">{{ dialogError }}</p>
        <footer class="dialog-actions">
          <button class="btn primary" type="button" :disabled="submitting" @click="submitBatch">
            {{ submitting ? '提交中…' : `确认批量${dialogAction}` }}
          </button>
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>
type BatchAction = '确认通过' | '发起重测'
type Failure = { id: number | null; 复核编号: string; 原因: string }

const ENDPOINT = '/api/review'
const columns = ["复核编号", "关联结果", "复核项目", "复核人", "复核意见", "复核时间", "差异说明", "重测原因", "复核状态"]
const statuses = ["待复核", "复核中", "已通过", "需重测"]
const ACTIONABLE = ['待复核', '复核中']

const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const stats = ref([
  { label: '待复核记录', value: 0 },
  { label: '本月通过数', value: 0 },
  { label: '需重测项数', value: 0 },
])

const selectedIds = ref<number[]>([])
const failures = ref<Failure[]>([])

const dialogAction = ref<'' | BatchAction>('')
const dialogRows = ref<Row[]>([])
const reviewer = ref('')
const opinion = ref('')
const diffNote = ref('')
const retestReasons = ref<Record<string, string>>({})
const dialogError = ref('')
const submitting = ref(false)

const actionableRows = computed(() => rows.value.filter((row) => isActionable(row)))
const allChecked = computed(
  () => actionableRows.value.length > 0
    && actionableRows.value.every((row) => selectedIds.value.includes(Number(row.id))),
)

function isActionable(row: Row) {
  return ACTIONABLE.includes(String(row['status'] ?? ''))
}

function toggleAll() {
  if (allChecked.value) {
    const pageIds = new Set(actionableRows.value.map((row) => Number(row.id)))
    selectedIds.value = selectedIds.value.filter((id) => !pageIds.has(id))
  } else {
    const merged = new Set(selectedIds.value)
    for (const row of actionableRows.value) merged.add(Number(row.id))
    selectedIds.value = [...merged]
  }
}

function toggleOne(row: Row) {
  const id = Number(row.id)
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function clearSelection() {
  selectedIds.value = []
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '复核记录登记入口尚未接入审批流'
}

function openBatch(action: BatchAction, row?: Row) {
  failures.value = []
  errorMessage.value = ''
  noticeMessage.value = ''
  dialogRows.value = row ? [row] : rows.value.filter((item) => selectedIds.value.includes(Number(item.id)))
  if (!dialogRows.value.length) {
    errorMessage.value = '请先勾选需要批量处理的复核记录'
    return
  }
  dialogAction.value = action
  reviewer.value = session.operator
  dialogError.value = ''
  const reasons: Record<string, string> = {}
  for (const item of dialogRows.value) reasons[String(item.id)] = retestReasons.value[String(item.id)] ?? ''
  retestReasons.value = reasons
}

function closeDialog() {
  dialogAction.value = ''
  dialogError.value = ''
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('结果复核动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结果复核操作失败'
  }
}

async function submitBatch() {
  dialogError.value = ''
  if (!opinion.value.trim()) {
    dialogError.value = '请先填写复核意见，批量处理必须统一填写复核意见'
    return
  }
  if (dialogAction.value === '发起重测') {
    const missing = dialogRows.value.filter((row) => !(retestReasons.value[String(row.id)] ?? '').trim())
    if (missing.length) {
      dialogError.value = `以下条目缺少单独的重测原因：${missing.map((row) => row['复核编号']).join('、')}`
      return
    }
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({
        ids: dialogRows.value.map((row) => Number(row.id)),
        action: dialogAction.value,
        复核意见: opinion.value.trim(),
        差异说明: diffNote.value.trim(),
        复核人: reviewer.value.trim(),
        重测原因: retestReasons.value,
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      failures.value = payload.failures ?? []
      errorMessage.value = payload.message ?? '批量处理已整批拒绝'
      closeDialog()
      await Promise.all([reload(), loadSummary()])
      return
    }
    noticeMessage.value = payload.message ?? '批量处理完成'
    selectedIds.value = []
    opinion.value = ''
    diffNote.value = ''
    retestReasons.value = {}
    closeDialog()
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '批量复核操作失败'
  } finally {
    submitting.value = false
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) return
    const payload = await response.json()
    stats.value = stats.value.map((item) => ({ ...item, value: Number(payload[item.label] ?? 0) }))
  } catch {
    // 计数拉取失败不阻断列表展示
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('复核记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const visible = new Set(rows.value.map((row) => Number(row.id)))
    selectedIds.value = selectedIds.value.filter((id) => visible.has(id))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结果复核列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
