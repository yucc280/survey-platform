<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import QuestionContentFields from './QuestionContentFields.vue'
import QuestionInsights from './QuestionInsights.vue'
const props = defineProps({ api: { type: Function, required: true }, source: Object, disabled: Boolean, purpose: { type: String, default: 'survey' } })
const emit = defineEmits(['select', 'cancel'])
const items = ref([]), offset = ref(0), total = ref(0), question = ref(null)
const versions = ref([]), version = ref(null), versionOffset = ref(0), versionTotal = ref(0)
const busy = ref(false), error = ref('')
const scope = ref('mine'), keyword = ref(''), bankId = ref(''), banks = ref([]), bankOffset = ref(0), bankTotal = ref(0)
const insightsMode = ref(null)
let alive = true
onUnmounted(() => { alive = false })
async function run(action) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await action() } catch (e) { if (alive) { error.value = e.message; question.value = null; version.value = null } }
  finally { if (alive) busy.value = false }
}
async function list(next = 0) {
  if (['bank', 'shared'].includes(scope.value) && !bankId.value) { items.value = []; total.value = 0; return }
  const query = new URLSearchParams({ offset: next, limit: 20, scope: scope.value, keyword: keyword.value })
  const data = ['bank', 'shared'].includes(scope.value)
    ? await props.api(`/question-banks/${bankId.value}?offset=${next}&limit=20`)
    : await props.api(`/questions?${query}`)
  if (!alive) return
  items.value = data.items; total.value = data.total; offset.value = next
}
async function history(next = 0) {
  const data = await props.api(`/questions/${question.value.id}/versions?offset=${next}&limit=20`)
  if (!alive) return
  versions.value = data.items; versionOffset.value = next; versionTotal.value = data.total
}
async function choose(id) {
  question.value = null; version.value = null; insightsMode.value = null
  const data = await props.api(`/questions/${id}`)
  if (!alive) return
  question.value = data; version.value = data.current_version
  await history()
}
async function loadBanks(next = 0) {
  bankId.value = ''; resetSelection()
  const data = await props.api(`/question-banks?offset=${next}&limit=20`)
  if (alive) { banks.value = data.items; bankTotal.value = data.total; bankOffset.value = next }
}
function resetSelection() { question.value = null; version.value = null; insightsMode.value = null; versions.value = []; items.value = []; total.value = 0; offset.value = 0 }
function changeScope() {
  resetSelection(); bankId.value = ''
  run(() => scope.value === 'bank' ? loadBanks() : scope.value === 'shared' ? Promise.resolve() : list())
}
function search() { resetSelection(); run(() => list()) }
onMounted(() => run(() => props.source ? choose(props.source.question_id) : list()))
</script>

<template>
  <section class="question-card version-picker">
    <h4>{{ source ? '替换引用版本' : purpose === 'bank' ? '选择加入题库的题目' : '选择可复用题目' }}</h4>
    <p class="field-hint">{{ purpose === 'bank' ? '题库只关联逻辑题目，不固定这里预览的版本；编写问卷时再选择具体版本。' : '默认推荐当前版本，也可以选择历史版本。选入后保留固定快照，必答和跳转在问卷中设置。' }}</p>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <fieldset :disabled="busy || disabled" class="editor-fieldset form-stack">
      <template v-if="!source">
        <label>选题范围<select v-model="scope" @change="changeScope"><option value="mine">我的题目</option><option v-if="purpose !== 'bank'" value="bank">我的题库</option><option v-if="purpose !== 'bank'" value="shared">输入他人题库 ID</option></select></label>
        <template v-if="scope === 'bank'"><label>选择题库<select v-model="bankId" @change="search"><option value="" disabled>请选择自己的题库</option><option v-for="bank in banks" :key="bank.id" :value="bank.id">{{ bank.name }}</option></select></label><div class="editor-row"><button type="button" class="button secondary compact" :disabled="bankOffset === 0" @click="run(() => loadBanks(bankOffset - 20))">上一页题库</button><button type="button" class="button secondary compact" :disabled="bankOffset + 20 >= bankTotal" @click="run(() => loadBanks(bankOffset + 20))">下一页题库</button></div></template>
        <div v-else-if="scope === 'shared'" class="editor-row"><label>题库分享 ID<input v-model.trim="bankId" maxlength="24" placeholder="输入24位题库ID" @input="resetSelection" @keydown.enter.prevent="search" /></label><button type="button" class="button secondary" @click="search">查找题库</button></div>
        <div v-else class="editor-row"><label>题干关键词<input v-model="keyword" maxlength="200" placeholder="可搜索历史版本的题干" @keydown.enter.prevent="search" /></label><button type="button" class="button secondary" @click="search">查找题目</button></div>
        <label>选择题目<select :value="question?.id || ''" @change="run(() => choose($event.target.value))"><option value="" disabled>请选择题目</option><option v-for="item in items" :key="item.id" :value="item.id">{{ item.current_version.content.title }} · 当前 v{{ item.current_version.number }}</option></select></label>
        <p v-if="!items.length && !busy" class="muted">暂无可访问的匹配题目。</p>
        <div class="editor-row"><button class="button secondary compact" type="button" :disabled="offset === 0" @click="run(() => list(offset - 20))">上一页题目</button><button class="button secondary compact" type="button" :disabled="offset + 20 >= total" @click="run(() => list(offset + 20))">下一页题目</button></div>
      </template>
      <template v-if="question && version">
        <label>选择版本<select :value="version.id" @change="version = versions.find(v => v.id === $event.target.value)"><option v-if="!versions.some(v => v.id === version.id)" :value="version.id">v{{ version.number }}（当前选择）</option><option v-for="v in versions" :key="v.id" :value="v.id">v{{ v.number }}{{ v.id === question.current_version_id ? '（当前默认）' : '' }} · {{ v.content.title }}</option></select></label>
        <div class="editor-row"><button class="button secondary compact" type="button" :disabled="versionOffset === 0" @click="run(() => history(versionOffset - 20))">较新版本</button><button class="button secondary compact" type="button" :disabled="versionOffset + 20 >= versionTotal" @click="run(() => history(versionOffset + 20))">更早版本</button></div>
        <QuestionContentFields :content="version.content" disabled />
        <div class="editor-row"><button type="button" class="text-button" @click="insightsMode = 'usage'">查看使用情况</button><button type="button" class="text-button" @click="insightsMode = 'statistics'">查看全局统计</button></div>
        <button type="button" class="button primary" @click="emit('select', { question_id: question.id, version_id: version.id })">{{ purpose === 'bank' ? '确认加入题库' : `确认使用 v${version.number}` }}</button>
      </template>
      <button class="button secondary" type="button" @click="emit('cancel')">取消选择</button>
    </fieldset>
    <QuestionInsights v-if="insightsMode && question && version" :key="`${question.id}-${version.id}-${insightsMode}`" :api="api" :question-id="question.id" :version-id="version.id" :initial-mode="insightsMode" />
  </section>
</template>
