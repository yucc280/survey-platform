<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { displayAnswer, questionLabels } from '../utils/answerFlow.js'

const props = defineProps({ survey: { type: Object, required: true }, api: { type: Function, required: true } })
const result = ref(null)
const selectedQuestion = ref('')
const loading = ref(false)
const error = ref('')
let requestVersion = 0
let alive = true
onUnmounted(() => { alive = false; requestVersion++ })
const questions = computed(() => result.value ? result.value.questions || [result.value.question] : [])
const sampleQuestions = computed(() => selectedQuestion.value ? props.survey.questions.filter(q => q.id === selectedQuestion.value) : props.survey.questions)
watch(() => props.survey.id, () => { selectedQuestion.value = ''; load() }, { immediate: true })
watch(selectedQuestion, load)
async function load() {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
  result.value = null
  const questionPath = selectedQuestion.value ? `/questions/${selectedQuestion.value}` : ''
  try {
    const value = await props.api(`/surveys/${props.survey.id}${questionPath}/statistics`)
    if (alive && version === requestVersion) result.value = value
  } catch (e) { if (alive && version === requestVersion) error.value = e.message }
  finally { if (alive && version === requestVersion) loading.value = false }
}
function responseAnswer(sample, question) {
  const answer = sample.answers.find(item => item.question_id === question.id)
  return answer ? displayAnswer(question, answer.value) : '未经过此题'
}
</script>

<template>
  <div class="detail-body statistics-page">
    <div class="editor-toolbar"><h3>{{ survey.title }} · 统计结果</h3><button class="button secondary compact" :disabled="loading" @click="load">刷新统计</button></div>
    <p class="muted">每个账号取最新一份完整答卷。匿名和实名按同一账号去重，跳过题目不会从历史答卷补回。</p>
    <label>统计范围<select v-model="selectedQuestion" class="stats-filter"><option value="">全部题目</option><option v-for="(q, index) in survey.questions" :key="q.id" :value="q.id">第{{ index + 1 }}题：{{ q.title }}</option></select></label>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <div v-if="loading" class="loading-state" role="status">正在读取统计…</div>
    <template v-else-if="result">
      <div class="stats-totals"><div><span>成功提交总份数</span><strong>{{ result.total_submissions }}</strong></div><div><span>去重参与人数</span><strong>{{ result.participant_count }}</strong></div></div>
      <p v-if="!result.participant_count" class="muted">暂无成功提交的答卷。</p>
      <article v-for="q in questions" :key="q.question_id" class="question-card">
        <span class="question-type">{{ questionLabels[q.type] }}</span><h4>{{ q.title }}</h4><p class="muted">有效回答：{{ q.answered_count }} 人</p>
        <div v-if="q.type === 'single' || q.type === 'multiple'" class="option-counts"><div v-for="option in q.options" :key="option.id" class="option-count"><span>{{ option.label }}</span><meter min="0" :max="Math.max(1, q.answered_count)" :value="option.count" :aria-label="`${option.label}：${option.count}人`"></meter><strong>{{ option.count }} 人</strong></div><p v-if="q.type === 'multiple'" class="field-hint">每项统计选择人数，多选各项人数之和可能超过有效回答人数。</p></div>
        <template v-else><p v-if="q.type === 'number'">平均值：<strong>{{ q.average === null ? '暂无数据' : q.average_display }}</strong></p><details v-if="q.values.length"><summary>查看回答内容（{{ q.values.length }} 条）</summary><ul class="value-list"><li v-for="(value, i) in q.values" :key="i" class="answer-text">{{ value }}</li></ul></details><p v-else class="muted">暂无有效回答。</p></template>
      </article>
      <section class="latest-samples"><h3>最新答卷样本</h3><p class="field-hint">只展示每个账号的最新答卷；匿名样本不显示用户名。</p>
        <details v-for="(sample, index) in result.latest_responses" :key="index" class="sample-card"><summary>样本 {{ index + 1 }} · {{ sample.is_anonymous ? '匿名填写者' : sample.username || '用户名不可用' }}</summary><dl><div v-for="q in sampleQuestions" :key="q.id" class="sample-answer"><dt>{{ q.title }}</dt><dd class="answer-text">{{ responseAnswer(sample, q) }}</dd></div></dl></details>
      </section>
    </template>
  </div>
</template>
