<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { questionLabels } from '../utils/answerFlow.js'

const props = defineProps({ api: { type: Function, required: true }, questionId: { type: String, required: true }, versionId: String, initialMode: { type: String, default: 'statistics' } })
const mode = ref(props.initialMode), selected = ref(null), versions = ref([])
const versionOffset = ref(0), versionTotal = ref(0), allVersions = ref(false)
const result = ref(null), offset = ref(0), loading = ref(false), error = ref('')
let alive = true, requestNumber = 0
onUnmounted(() => { alive = false; requestNumber++ })
const current = number => alive && number === requestNumber
async function run(work) {
  const number = ++requestNumber
  loading.value = true; error.value = ''
  try { await work(number) }
  catch (e) { if (current(number)) { error.value = e.message; result.value = null } }
  finally { if (current(number)) loading.value = false }
}
function fetchResult(next) {
  const query = new URLSearchParams({ offset: next, limit: 20 })
  if (mode.value === 'usage') {
    if (!allVersions.value) query.set('version_id', selected.value.id)
    return props.api(`/questions/${props.questionId}/usage?${query}`)
  }
  return props.api(`/questions/${props.questionId}/versions/${selected.value.id}/statistics?${query}`)
}
function load(next = 0) {
  return run(async number => {
    result.value = null
    const data = await fetchResult(next)
    if (current(number)) { result.value = data; offset.value = next }
  })
}
function initialize() {
  mode.value = props.initialMode; allVersions.value = false
  return run(async number => {
    result.value = null; selected.value = null; versions.value = []
    const [question, history] = await Promise.all([
      props.api(`/questions/${props.questionId}`), props.api(`/questions/${props.questionId}/versions?limit=20`),
    ])
    if (!current(number)) return
    const id = props.versionId || question.current_version_id
    const version = history.items.find(v => v.id === id) || await props.api(`/questions/${props.questionId}/versions/${id}`)
    if (!current(number)) return
    selected.value = version; versions.value = history.items; versionTotal.value = history.total; versionOffset.value = 0
    const data = await fetchResult(0)
    if (current(number)) { result.value = data; offset.value = 0 }
  })
}
function historyPage(next) {
  return run(async number => {
    const data = await props.api(`/questions/${props.questionId}/versions?offset=${next}&limit=20`)
    if (current(number)) { versions.value = data.items; versionOffset.value = next; versionTotal.value = data.total }
  })
}
function changeVersion(event) {
  selected.value = versions.value.find(v => v.id === event.target.value)
  load()
}
function changeMode(value) { mode.value = value; load() }
watch(() => [props.questionId, props.versionId, props.initialMode], initialize, { immediate: true })
</script>

<template>
  <section class="question-card question-insights" aria-label="题目使用情况与全局统计">
    <div class="editor-toolbar"><h4>题目分析<span v-if="selected"> · {{ selected.content.title }}</span></h4><button class="button secondary compact" type="button" :disabled="loading" @click="initialize">刷新分析</button></div>
    <div class="editor-row"><button class="button compact" :class="mode === 'usage' ? 'primary' : 'secondary'" type="button" :disabled="loading || !selected" @click="changeMode('usage')">使用情况</button><button class="button compact" :class="mode === 'statistics' ? 'primary' : 'secondary'" type="button" :disabled="loading || !selected" @click="changeMode('statistics')">全局统计</button></div>
    <template v-if="selected">
      <label>分析版本<select :value="selected.id" :disabled="loading" @change="changeVersion"><option v-if="!versions.some(v => v.id === selected.id)" :value="selected.id">v{{ selected.number }}（当前选择）</option><option v-for="v in versions" :key="v.id" :value="v.id">v{{ v.number }} · {{ v.content.title }}</option></select></label>
      <div class="editor-row"><button class="button secondary compact" type="button" :disabled="loading || versionOffset === 0" @click="historyPage(versionOffset - 20)">较新分析版本</button><button class="button secondary compact" type="button" :disabled="loading || versionOffset + 20 >= versionTotal" @click="historyPage(versionOffset + 20)">更早分析版本</button></div>
    </template>
    <label v-if="mode === 'usage' && selected" class="check-label"><input v-model="allVersions" type="checkbox" :disabled="loading" @change="load()" />查看全部版本的使用情况</label>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p><p v-if="loading" role="status">正在读取分析…</p>
    <template v-else-if="result && mode === 'usage'">
      <p class="field-hint">共 {{ result.total }} 份可见引用问卷。仅展示必要信息，他人的草稿不会出现；不因此开放问卷详情或答案。</p>
      <div v-if="result.items.length" class="table-wrap"><table><thead><tr><th>问卷名称</th><th>创建者</th><th>状态</th><th>所用版本</th></tr></thead><tbody><tr v-for="s in result.items" :key="s.survey_id"><td>{{ s.title }}</td><td>{{ s.creator_username || '账号不可用' }}</td><td>{{ { draft: '草稿', published: '已发布', closed: '已关闭' }[s.status] }}</td><td>{{ s.versions.map(v => `v${v.version_number}`).join('、') }}</td></tr></tbody></table></div><p v-else class="muted">暂无可见的使用记录。</p>
      <div class="editor-row"><button class="button secondary compact" type="button" :disabled="offset === 0" @click="load(offset - 20)">上一页使用记录</button><button class="button secondary compact" type="button" :disabled="offset + 20 >= result.total" @click="load(offset + 20)">下一页使用记录</button></div>
    </template>
    <template v-else-if="result">
      <p class="field-hint">{{ questionLabels[result.type] }} · 固定版本 v{{ result.version_number }}。每份问卷每账号取最新整份答卷；跨问卷不按账号去重，同卷多次出现分别计数。空答及跳过不计入，数字0计入；包含截止与关闭问卷，不含草稿。</p>
      <div class="stats-totals"><div><span>引用的已发布问卷</span><strong>{{ result.referenced_survey_count }}</strong></div><div><span>有有效回答的问卷</span><strong>{{ result.answered_survey_count }}</strong></div><div><span>有效回答次数</span><strong>{{ result.answered_count }}</strong></div></div>
      <p v-if="!result.answered_count" class="muted">暂无有效回答。</p>
      <div v-if="result.options.length" class="option-counts"><div v-for="option in result.options" :key="option.id" class="option-count"><span>{{ option.label }}</span><meter min="0" max="100" :value="option.percentage" :aria-label="`${option.label}：${option.count}次，占${option.percentage}%`"></meter><strong>{{ option.count }} 次 · {{ option.percentage }}%</strong></div><p class="field-hint">占比以有效回答次数为分母；多选各项占比之和可能超过100%。</p></div>
      <template v-if="result.type === 'number'">
        <p>平均值：<strong>{{ result.average_display }}</strong></p>
        <div v-if="result.distribution.length" class="table-wrap"><table><thead><tr><th>数值</th><th>次数</th><th>占比</th></tr></thead><tbody><tr v-for="row in result.distribution" :key="row.value"><td>{{ row.value }}</td><td>{{ row.count }}</td><td>{{ row.percentage }}%</td></tr></tbody></table></div>
        <p class="field-hint">相同数值合并计数，共 {{ result.distribution_total }} 个不同数值；分页不改变全量均值和占比。</p><div class="editor-row"><button class="button secondary compact" type="button" :disabled="offset === 0" @click="load(offset - 20)">上一页数值</button><button class="button secondary compact" type="button" :disabled="offset + 20 >= result.distribution_total" @click="load(offset + 20)">下一页数值</button></div>
      </template>
      <template v-if="result.type === 'text'">
        <p class="field-hint">以下为该版本跨问卷的有效文本回答，相同内容分别保留。仅展示回答内容，不附带填写者身份或问卷来源。</p>
        <ol v-if="result.text_answers.length" :start="result.text_offset + 1">
          <li v-for="(answer, index) in result.text_answers" :key="`${result.text_offset}-${index}`" class="answer-text">{{ answer }}</li>
        </ol>
        <p v-else-if="result.answered_count" class="muted">当前页暂无回答，请返回上一页或刷新分析。</p>
        <p class="field-hint">共 {{ result.answered_count }} 条，当前显示 {{ result.text_answers.length ? result.text_offset + 1 : 0 }}–{{ result.text_answers.length ? result.text_offset + result.text_answers.length : 0 }} 条。</p>
        <div class="editor-row"><button class="button secondary compact" type="button" :disabled="result.text_offset === 0" @click="load(Math.max(0, result.text_offset - result.text_limit))">上一页回答</button><button class="button secondary compact" type="button" :disabled="result.text_offset + result.text_limit >= result.answered_count" @click="load(result.text_offset + result.text_limit)">下一页回答</button></div>
      </template>
      <p class="field-hint">全局汇总不展示填写者身份或逐条答卷，使用次数不等于去重人数。</p>
    </template>
  </section>
</template>
