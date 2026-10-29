<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { formatTime } from '../api.js'
import { questionLabels } from '../utils/answerFlow.js'
import QuestionContentFields from '../components/QuestionContentFields.vue'
import QuestionInsights from '../components/QuestionInsights.vue'

const props = defineProps({ api: { type: Function, required: true }, userId: { type: String, required: true }, initialQuestionId: String })
const emit = defineEmits(['notice'])
const items = ref([]), total = ref(0), offset = ref(0), busy = ref(false), error = ref('')
const selected = ref(null), history = ref([]), historyTotal = ref(0), historyOffset = ref(0)
const viewed = ref(null), draft = ref(null)
const insightsMode = ref(null)
const temporaryConfirm = ref(false)
const owned = computed(() => selected.value?.owner_id === props.userId)
let alive = true
onUnmounted(() => { alive = false })
const clone = value => JSON.parse(JSON.stringify(value))

async function run(action) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await action() } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) busy.value = false }
}
async function load(next = offset.value) {
  const data = await props.api(`/questions?offset=${next}&limit=20`)
  if (!alive) return
  items.value = data.items; total.value = data.total; offset.value = next
}
async function historyPage(next = 0) {
  const data = await props.api(`/questions/${selected.value.id}/versions?offset=${next}&limit=20`)
  if (!alive) return
  history.value = data.items; historyTotal.value = data.total; historyOffset.value = next
}
async function open(id) {
  const data = await props.api(`/questions/${id}`)
  if (!alive) return
  selected.value = data; viewed.value = clone(data.current_version); draft.value = null; insightsMode.value = null
  temporaryConfirm.value = false
  await historyPage()
}
function create() {
  selected.value = null; viewed.value = null; history.value = []; insightsMode.value = null
  draft.value = { type: 'single', title: '', options: [{ label: '' }, { label: '' }], validation: {} }
}
async function save() {
  await run(async () => {
    const content = clone(draft.value)
    for (const [key, value] of Object.entries(content.validation)) if (value === '' || value == null) delete content.validation[key]
    const data = selected.value
      ? await props.api(`/questions/${selected.value.id}/versions`, { method: 'POST', body: { content, expected_revision: selected.value.revision } })
      : await props.api('/questions', { method: 'POST', body: { content } })
    if (!alive) return
    await open(data.id); await load()
    if (alive) emit('notice', `已保存 v${data.current_version.number}，已有问卷保持原版本。`)
  })
}
async function restore() {
  if (!window.confirm(`将当前默认版本恢复为 v${viewed.value.number}？已有问卷不受影响。`)) return
  await run(async () => {
    const data = await props.api(`/questions/${selected.value.id}/current-version`, {
      method: 'PATCH', body: { expected_revision: selected.value.revision, version_id: viewed.value.id },
    })
    if (!alive) return
    await open(data.id); await load()
    if (alive) emit('notice', `当前默认版本已恢复为 v${data.current_version.number}。`)
  })
}
async function makeTemporary() {
  await run(async () => {
    const data = await props.api(`/questions/${selected.value.id}/temporary`, { method: 'POST', body: { expected_revision: selected.value.revision } })
    if (!alive) return
    selected.value = null; viewed.value = null; insightsMode.value = null; temporaryConfirm.value = false
    await load(0)
    if (alive) emit('notice', data.message)
  })
}
onMounted(() => run(async () => { await load(0); if (alive && props.initialQuestionId) await open(props.initialQuestionId) }))
</script>

<template>
  <div class="workspace-content">
    <div class="page-heading"><div><p class="eyebrow">可复用题目</p><h1>我的题目</h1><p class="muted">正式版本固定保存；是否必答和跳转在问卷中配置。</p></div><button class="button primary" :disabled="busy" @click="create">＋ 新建题目</button></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }}<span> 如提示内容已变化，请刷新题目后重新编辑。</span></p>
    <section class="panel detail-body">
      <div class="editor-toolbar"><h2>题目列表（{{ total }}）</h2><button class="button secondary" :disabled="busy" @click="run(async () => { draft = null; if (selected) await open(selected.id); await load() })">刷新</button></div>
      <p v-if="!items.length && !busy" class="muted">还没有可复用题目，可以先新建一道。</p>
      <div v-for="item in items" :key="item.id" class="library-list-row">
        <div><strong>{{ item.current_version.content.title }}</strong><p class="muted">{{ questionLabels[item.current_version.content.type] }} · 当前 v{{ item.current_version.number }} · 共 {{ item.max_version }} 版</p></div>
        <button class="button secondary" :disabled="busy" @click="run(() => open(item.id))">查看 / 管理</button>
      </div>
      <div class="pagination"><span>{{ total ? offset + 1 : 0 }}–{{ Math.min(offset + 20, total) }} / {{ total }}</span><div><button class="button secondary" :disabled="busy || offset === 0" @click="run(() => load(offset - 20))">上一页</button><button class="button secondary" :disabled="busy || offset + 20 >= total" @click="run(() => load(offset + 20))">下一页</button></div></div>
    </section>
    <section v-if="selected || draft" class="panel detail-body library-detail">
      <div class="editor-toolbar"><h2>{{ draft ? selected ? '保存为新版本' : '创建题目 v1' : '版本内容' }}</h2><button class="button secondary" :disabled="busy" @click="selected = null; viewed = null; draft = null">收起</button></div>
      <p v-if="selected" class="muted">题目 ID：{{ selected.id }} · 当前 v{{ selected.current_version.number }}</p>
      <template v-if="selected && !draft">
        <p class="field-hint">{{ owned ? '加入自己的题库后，可将题库ID分享给其他用户选用。' : '他人的题目仅可查看和选用，不能修改或恢复。' }}</p>
        <button v-if="owned" class="button secondary compact" :disabled="busy" @click="temporaryConfirm = !temporaryConfirm">移出我的题目 / 转为临时题</button>
        <div v-if="temporaryConfirm && owned" class="form-stack"><p class="field-hint">仅允许未被引用或只被自己一份问卷引用的题目移出；原问卷内容和答案保留，转换后不再提供全局分析。多份引用时会拒绝。</p><div class="editor-row"><button class="button primary compact" :disabled="busy" @click="makeTemporary">确认移出并转回临时题</button><button class="button secondary compact" :disabled="busy" @click="temporaryConfirm = false">取消转回</button></div></div>
        <div class="editor-row"><label>查看历史版本<select :value="viewed.id" :disabled="busy" @change="viewed = clone(history.find(v => v.id === $event.target.value))"><option v-if="!history.some(v => v.id === viewed.id)" :value="viewed.id">v{{ viewed.number }}（当前查看）</option><option v-for="v in history" :key="v.id" :value="v.id">v{{ v.number }}{{ v.id === selected.current_version_id ? '（当前默认）' : '' }}</option></select></label><button class="button secondary" :disabled="busy || historyOffset === 0" @click="run(() => historyPage(historyOffset - 20))">较新版本</button><button class="button secondary" :disabled="busy || historyOffset + 20 >= historyTotal" @click="run(() => historyPage(historyOffset + 20))">更早版本</button></div>
        <p class="muted">保存时间：{{ formatTime(viewed.created_at) }} · 来源版本 ID：{{ viewed.parent_version_id || '首次创建，无来源版本' }}</p>
        <QuestionContentFields :content="viewed.content" disabled />
        <div v-if="owned" class="editor-row"><button class="button primary" :disabled="busy" @click="draft = clone(selected.current_version.content); insightsMode = null">编辑当前版本</button><button class="button secondary" :disabled="busy || viewed.id === selected.current_version_id" @click="restore">恢复此版本为当前版本</button></div>
        <p v-if="owned" class="field-hint">编辑当前默认版本后提交新版本。若需基于旧内容修改，请先恢复旧版本。</p>
        <div class="editor-row"><button class="button secondary" :disabled="busy" @click="insightsMode = 'usage'">查看使用情况</button><button class="button secondary" :disabled="busy" @click="insightsMode = 'statistics'">查看全局统计</button><button v-if="insightsMode" class="text-button" @click="insightsMode = null">收起分析</button></div>
        <QuestionInsights v-if="insightsMode" :key="`${selected.id}-${viewed.id}-${insightsMode}`" :api="api" :question-id="selected.id" :version-id="viewed.id" :initial-mode="insightsMode" />
      </template>
      <form v-if="draft" class="form-stack" @submit.prevent="save">
        <QuestionContentFields :content="draft" :disabled="busy" />
        <p class="field-hint">新题目仅自己可用，加入题库后可通过题库ID分享。保存后版本不可覆盖；取消不会改变原版本。未保存内容不自动保留。</p>
        <div class="editor-row"><button class="button primary" :disabled="busy" type="submit">{{ busy ? '保存中…' : selected ? '保存为新版本' : '保存 v1' }}</button><button class="button secondary" :disabled="busy" type="button" @click="draft = null">取消编辑</button></div>
      </form>
    </section>
  </div>
</template>
