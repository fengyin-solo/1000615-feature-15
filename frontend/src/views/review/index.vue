<template>
  <section class="page" data-module="review">
    <header class="page-head">
      <div>
        <h2>结果复核管理</h2>
        <p class="page-desc">维护复核记录，支持勾选多条待复核记录批量确认通过或批量发起重测，统一填写复核意见与差异说明。</p>
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
      <span>待复核 <strong>{{ pendingCount }}</strong> 条</span>
      <span>已选 <strong>{{ selectedIds.length }}</strong> 条</span>
      <button class="btn primary" type="button" :disabled="!selectedIds.length" @click="openBatch('确认通过')">
        批量确认通过
      </button>
      <button class="btn" type="button" :disabled="!selectedIds.length" @click="openBatch('发起重测')">
        批量发起重测
      </button>
      <span v-if="pendingCount === 0" class="batch-hint">当前没有待复核记录，无需批量处理</span>
      <span v-else class="batch-hint">仅「待复核」状态的记录可勾选，整批校验不通过将整批拒绝</span>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input
              type="checkbox"
              :checked="allChecked"
              :disabled="!selectableRows.length"
              title="全选当前列表中的待复核记录"
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
              :checked="selectedIds.includes(row.id)"
              :disabled="row.status !== '待复核'"
              :title="row.status === '待复核' ? '勾选后可参与批量处理' : '仅待复核记录可批量处理'"
              @change="toggleRow(row)"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">{{ emptyText }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条结果复核记录</span>
      <span v-if="okMessage" class="ok-text">{{ okMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="batchAction" class="modal-mask" @click.self="closeBatch">
      <div class="modal">
        <h3>批量{{ batchAction }}（{{ selectedRows.length }} 条）</h3>
        <ul class="selected-list">
          <li v-for="row in selectedRows" :key="row.id">
            <span>{{ row['复核编号'] }} · {{ row['复核项目'] }} · 关联结果 {{ row['关联结果'] }}</span>
            <input
              v-if="batchAction === '发起重测'"
              v-model="reasons[row.id]"
              :placeholder="`请单独填写 ${row['复核编号']} 的重测原因（必填）`"
            />
          </li>
        </ul>
        <label class="modal-field">
          <span>复核意见（必填，统一应用到本批记录）</span>
          <textarea v-model="opinion" rows="2" placeholder="例如：数据与原始记录一致，同意通过"></textarea>
        </label>
        <label class="modal-field">
          <span>差异说明（统一应用到本批记录）</span>
          <textarea v-model="difference" rows="2" placeholder="例如：与初检结果一致，无差异"></textarea>
        </label>
        <div v-if="batchFailures.length" class="failure-box">
          <p>整批已拒绝，未改动任何记录，请逐条处理：</p>
          <ul>
            <li v-for="failure in batchFailures" :key="failure">{{ failure }}</li>
          </ul>
        </div>
        <div class="modal-actions">
          <button class="btn primary" type="button" :disabled="submitting" @click="submitBatch">
            {{ submitting ? '提交中…' : '确认提交' }}
          </button>
          <button class="btn ghost" type="button" @click="closeBatch">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

interface Row {
  id: number
  status?: string
  [key: string]: string | number | null | undefined
}

interface StatCard {
  label: string
  value: number
}

type BatchAction = '确认通过' | '发起重测'

const ENDPOINT = '/api/review'
const columns = ["复核编号", "关联结果", "复核项目", "复核人", "复核意见", "复核时间", "差异说明", "重测原因", "复核状态"]
const actions = ["开始复核", "确认通过", "发起重测"]
const statuses = ["待复核", "复核中", "已通过", "需重测"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatCard[]>([
  { label: '待复核记录', value: 0 },
  { label: '本月通过数', value: 0 },
  { label: '需重测项数', value: 0 },
])
const errorMessage = ref('')
const okMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const selectedIds = ref<number[]>([])
const batchAction = ref<BatchAction | ''>('')
const opinion = ref('')
const difference = ref('')
const reasons = ref<Record<number, string>>({})
const batchFailures = ref<string[]>([])
const submitting = ref(false)

const pendingCount = computed(() => stats.value.find((item) => item.label === '待复核记录')?.value ?? 0)
const selectableRows = computed(() => rows.value.filter((row) => row.status === '待复核'))
const selectedRows = computed(() => rows.value.filter((row) => selectedIds.value.includes(row.id)))
const allChecked = computed(
  () => selectableRows.value.length > 0 && selectableRows.value.every((row) => selectedIds.value.includes(row.id)),
)
const emptyText = computed(() => {
  if (keyword.value || statusFilter.value) return '暂无符合条件的结果复核记录，可调整筛选条件后重试'
  if (pendingCount.value === 0) return '当前没有待复核记录，结果复核已全部处理完毕'
  return '暂无结果复核数据，可先登记复核记录'
})

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

function toggleRow(row: Row) {
  if (row.status !== '待复核') return
  selectedIds.value = selectedIds.value.includes(row.id)
    ? selectedIds.value.filter((id) => id !== row.id)
    : [...selectedIds.value, row.id]
}

function toggleAll() {
  if (allChecked.value) {
    const pageIds = new Set(selectableRows.value.map((row) => row.id))
    selectedIds.value = selectedIds.value.filter((id) => !pageIds.has(id))
  } else {
    const merged = new Set([...selectedIds.value, ...selectableRows.value.map((row) => row.id)])
    selectedIds.value = [...merged]
  }
}

function pruneSelection() {
  const valid = new Set(selectableRows.value.map((row) => row.id))
  selectedIds.value = selectedIds.value.filter((id) => valid.has(id))
}

function openBatch(action: BatchAction) {
  batchAction.value = action
  opinion.value = ''
  difference.value = ''
  reasons.value = Object.fromEntries(selectedIds.value.map((id) => [id, '']))
  batchFailures.value = []
  errorMessage.value = ''
  okMessage.value = ''
}

function closeBatch() {
  batchAction.value = ''
  batchFailures.value = []
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  okMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '结果复核动作未生效，请稍后重试')
    }
    okMessage.value = payload.message ?? ''
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结果复核操作失败'
  }
}

async function submitBatch() {
  if (!batchAction.value) return
  batchFailures.value = []
  const trimmedOpinion = opinion.value.trim()
  if (!trimmedOpinion) {
    batchFailures.value = ['请填写复核意见：批量处理必须统一填写复核意见']
    return
  }
  if (batchAction.value === '发起重测') {
    const missing = selectedRows.value.filter((row) => !(reasons.value[row.id] ?? '').trim())
    if (missing.length) {
      batchFailures.value = missing.map((row) => `${row['复核编号']}：发起重测必须为该条单独填写重测原因`)
      return
    }
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({
        action: batchAction.value,
        ids: selectedIds.value,
        opinion: trimmedOpinion,
        difference: difference.value.trim(),
        reasons: reasons.value,
      }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      batchFailures.value = Array.isArray(payload.failures) && payload.failures.length
        ? payload.failures
        : [payload.message ?? '批量处理被拒绝']
      return
    }
    okMessage.value = payload.message ?? '批量处理完成'
    selectedIds.value = []
    closeBatch()
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    batchFailures.value = [error instanceof Error ? error.message : '批量处理请求失败']
  } finally {
    submitting.value = false
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
    pruneSelection()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结果复核列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('复核统计读取失败')
    }
    const payload = await response.json()
    stats.value = payload.cards ?? stats.value
  } catch {
    // 统计卡读取失败不阻断列表展示，保留上一次数据
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>
