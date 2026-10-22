<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { formatTime } from '../api.js'
import { displayAnswer, effectivePath, pruneAnswers, questionError, questionLabels } from '../utils/answerFlow.js'

const props = defineProps({ surveyId: { type: String, required: true }, api: { type: Function, required: true } })
const emit = defineEmits(['notice'])
const survey = ref(null)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const answers = ref({})
const position = ref(0)
const anonymous = ref(false)
const reviewing = ref(false)
const validated = ref(null)
const receipt = ref(null)
let alive = true
onUnmounted(() => { alive = false })
const path = computed(() => survey.value ? effectivePath(survey.value.questions, answers.value) : [])
const current = computed(() => path.value[position.value])

onMounted(load)
async function load() {
  loading.value = true
  error.value = ''
  try {
    const value = await props.api(`/fill/surveys/${props.surveyId}`)
    if (!alive) return
    survey.value = value
    anonymous.value = value.allow_anonymous
    answers.value = {}
    position.value = 0
    reviewing.value = false
    receipt.value = null
  } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) loading.value = false }
}
function update(value) {
  answers.value = pruneAnswers(survey.value.questions, { ...answers.value, [current.value.id]: value })
  validated.value = null
  error.value = ''
}
function toggleOption(id, checked) {
  const values = answers.value[current.value.id] || []
  update(checked ? [...values, id] : values.filter(value => value !== id))
}
async function next() {
  if (busy.value) return
  error.value = questionError(current.value, answers.value[current.value.id])
  if (error.value) return
  if (position.value < path.value.length - 1) position.value++
  else await review()
}
async function review() {
  if (busy.value) return
  for (let i = 0; i < path.value.length; i++) {
    const q = path.value[i]
    const message = questionError(q, answers.value[q.id])
    if (message) { position.value = i; error.value = message; return }
  }
  busy.value = true
  try {
    const body = { is_anonymous: anonymous.value, answers: path.value.map(q => ({ question_id: q.id, value: answers.value[q.id] ?? null })) }
    const result = await props.api(`/fill/surveys/${props.surveyId}/validate`, { method: 'POST', body })
    if (!alive) return
    validated.value = result
    reviewing.value = true
  } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) busy.value = false }
}
async function submit() {
  if (busy.value || !validated.value) return
  busy.value = true
  error.value = ''
  try {
    // 保留原始数字字符串，手机号和整数由后端再次精确校验，不用JS浮点重写输入。
    const body = { is_anonymous: anonymous.value, answers: path.value.map(q => ({ question_id: q.id, value: answers.value[q.id] ?? null })) }
    const result = await props.api(`/fill/surveys/${props.surveyId}/responses`, { method: 'POST', body })
    if (!alive) return
    receipt.value = result
    emit('notice', '答卷提交成功。')
  } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) busy.value = false }
}
function back() {
  reviewing.value = false
  validated.value = null
  error.value = ''
  position.value = Math.max(0, position.value - 1)
}
function editAt(index) {
  reviewing.value = false
  validated.value = null
  error.value = ''
  position.value = index
}
function hints(q) {
  const v = q.validation || {}
  if (q.type === 'multiple') return `可选数量：${v.min_choices ?? 0}～${v.max_choices ?? q.options.length}项`
  if (q.type === 'text') return `字符数：${v.min_length ?? 0}～${v.max_length ?? '不限'}`
  if (q.type === 'number') return v.phone_format ? '填写11位手机号，不带国家码、空格或分隔符。' : `${v.integer_only ? '整数' : '数字'}；范围：${v.min_value ?? '不限'}～${v.max_value ?? '不限'}`
  return '请选择一个选项。'
}
</script>

<template>
  <section class="fill-page panel">
    <div v-if="loading" class="loading-state" role="status">正在读取问卷…</div>
    <template v-else-if="survey">
      <div class="fill-heading"><p class="eyebrow">填写问卷</p><h1>{{ survey.title }}</h1><p class="description-full">{{ survey.description }}</p><p class="muted">截止时间：{{ formatTime(survey.deadline) }}</p></div>
      <div v-if="receipt" class="submission-success">
        <h2>提交成功</h2><p>你的答卷已保存。</p><p>提交方式：{{ receipt.is_anonymous ? '匿名' : '实名' }}</p><p>提交时间：{{ formatTime(receipt.submitted_at) }}</p>
        <div class="editor-row"><button v-if="survey.allow_repeat" class="button secondary" @click="load">再填写一次</button><a class="button primary" href="/">返回工作台</a></div>
      </div>
      <template v-else>
        <p class="field-hint">仅成功提交后保存答卷，刷新或离开页面不会保存当前填写内容。</p>
        <div v-if="reviewing" class="answer-review">
          <h2>确认并提交</h2><p class="muted">以下是本次实际经过的题目；跳过的题目不提交。</p>
          <article v-for="(q, index) in path" :key="q.id" class="review-item"><div class="editor-toolbar"><strong>第{{ survey.questions.findIndex(item => item.id === q.id) + 1 }}题：{{ q.title }}</strong><button class="text-button" :disabled="busy" @click="editAt(index)">修改此题</button></div><p class="answer-text">{{ displayAnswer(q, validated.answers.find(a => a.question_id === q.id)?.value) }}</p></article>
          <p>提交方式：{{ anonymous ? '匿名，创建者看不到你的账号名' : '实名，创建者可看到你的账号名' }}</p>
          <div class="editor-row"><button class="button secondary" :disabled="busy" @click="editAt(0)">返回修改</button><button class="button primary" :disabled="busy" @click="submit">{{ busy ? '提交中…' : '确认提交' }}</button></div>
        </div>
        <form v-else-if="current" @submit.prevent="next" novalidate>
          <fieldset :disabled="busy" class="editor-fieldset">
            <div class="fill-progress"><span>答题进度：第 {{ position + 1 }} 步</span><span>原问卷共 {{ survey.questions.length }} 题，按回答跳转</span></div>
            <div class="editor-toolbar"><span class="question-type">{{ questionLabels[current.type] }}</span><span class="muted">{{ current.required ? '必答' : '选答' }}</span></div>
            <h2>第{{ survey.questions.findIndex(q => q.id === current.id) + 1 }}题：{{ current.title }}</h2>
            <p class="muted">{{ hints(current) }}</p>
            <div v-if="current.type === 'single' || current.type === 'multiple'" class="fill-options">
              <label v-for="option in current.options" :key="option.id" class="fill-option"><input :type="current.type === 'single' ? 'radio' : 'checkbox'" :name="current.id" :value="option.id" :checked="current.type === 'single' ? answers[current.id] === option.id : (answers[current.id] || []).includes(option.id)" @change="current.type === 'single' ? update(option.id) : toggleOption(option.id, $event.target.checked)" /><span>{{ option.label }}</span></label>
              <button v-if="!current.required" class="text-button" type="button" @click="update(current.type === 'multiple' ? [] : null)">清空选择</button>
            </div>
            <label v-else-if="current.type === 'text'">你的回答<textarea :value="answers[current.id] ?? ''" rows="5" @input="update($event.target.value)"></textarea></label>
            <label v-else>你的回答<input :value="answers[current.id] ?? ''" type="text" :inputmode="current.validation.phone_format || current.validation.integer_only ? 'numeric' : 'decimal'" autocomplete="off" @input="update($event.target.value)" /></label>
            <div v-if="position === 0" class="fill-identity"><label v-if="survey.allow_anonymous" class="check-label"><input v-model="anonymous" type="checkbox" />匿名提交（仍需登录，创建者不显示你的账号名）</label><p v-else class="muted">本问卷以实名方式提交，创建者可看到你的账号名。</p></div>
            <div class="editor-row"><button class="button secondary" type="button" :disabled="position === 0" @click="back">上一题</button><button class="button primary" type="submit">{{ busy ? '校验中…' : position === path.length - 1 ? '检查并预览' : '下一题' }}</button></div>
          </fieldset>
        </form>
      </template>
    </template>
    <div v-else><h1>暂时无法填写</h1><p>请确认问卷已发布，仍在开放，并且你有可用的填写次数。</p><button class="button secondary" @click="load">重新检查</button></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <a v-if="!receipt" class="text-button" href="/">返回工作台</a>
  </section>
</template>
