<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { formatTime, surveyStatus } from '../api.js'

const props = defineProps({ survey: { type: Object, required: true }, api: { type: Function, required: true } })
const emit = defineEmits(['saved', 'notice'])
const form = ref(null)
const baseline = ref('')
const busy = ref(false)
const error = ref('')
const newType = ref('single')
const actionDialog = ref(null)
const action = ref('publish')
const deadline = ref('')
let alive = true
onUnmounted(() => { alive = false })
const labels = { single: '单选题', multiple: '多选题', text: '文本填空', number: '数字填空' }
const operators = { equals: '选中', contains: '包含选项', contains_all: '同时包含', gt: '大于', gte: '大于等于', lt: '小于', lte: '小于等于', eq: '等于' }
const clone = value => JSON.parse(JSON.stringify(value))
watch(() => props.survey, value => {
  form.value = clone({ title: value.title, description: value.description,
    allow_anonymous: value.allow_anonymous, allow_repeat: value.allow_repeat, questions: value.questions })
  baseline.value = JSON.stringify(form.value)
  error.value = ''
}, { immediate: true })
const dirty = computed(() => JSON.stringify(form.value) !== baseline.value)
const editable = computed(() => props.survey.status === 'draft')
// 没有后端生成的稳定ID时，先保存题目，再配置跨题引用。
const structureSaved = computed(() => form.value.questions.every(q => q.id && q.options.every(o => o.id)))
const canChangeDeadline = computed(() => props.survey.status === 'published' && surveyStatus(props.survey).tone === 'published')

function move(items, index, step) {
  const target = index + step
  if (target < 0 || target >= items.length) return
  const [item] = items.splice(index, 1)
  items.splice(target, 0, item)
}
function addQuestion() {
  const type = newType.value
  form.value.questions.push({ type, title: '', required: false,
    options: ['single', 'multiple'].includes(type) ? [{ label: '' }, { label: '' }] : [],
    validation: type === 'number' ? { integer_only: false, phone_format: false } : {}, jump_rules: [] })
}
function ruleOperators(q) {
  return q.type === 'single' ? ['equals'] : q.type === 'multiple' ? ['contains', 'contains_all'] : ['gt', 'gte', 'lt', 'lte', 'eq']
}
function resetCondition(rule, q) {
  rule.condition.value = q.type === 'number' ? 0 : rule.condition.operator === 'contains_all' ? [] : q.options[0]?.id || ''
}
function addRule(q) {
  const rule = { condition: { operator: ruleOperators(q)[0], value: null }, target: { kind: 'end' } }
  resetCondition(rule, q)
  q.jump_rules.push(rule)
}
function setTarget(rule, value) {
  rule.target = value === 'end' ? { kind: 'end' } : { kind: 'question', question_id: value }
}
function payload() {
  const result = clone(form.value)
  for (const [index, q] of result.questions.entries()) {
    if (!q.title.trim()) throw new Error(`第${index + 1}题的题干不能为空。`)
    for (const option of q.options) if (!option.label.trim()) throw new Error(`第${index + 1}题有空白选项。`)
    // 数字输入框清空时Vue给出空字符串；接口以字段缺省表示不设边界。
    for (const [key, value] of Object.entries(q.validation)) {
      if (value === '' || value === null) delete q.validation[key]
      else if (typeof value !== 'boolean' && (typeof value !== 'number' || !Number.isFinite(value))) throw new Error(`第${index + 1}题的校验值必须是有限数字。`)
    }
    for (const rule of q.jump_rules) {
      if (q.type === 'number' && (typeof rule.condition.value !== 'number' || !Number.isFinite(rule.condition.value))) throw new Error(`第${index + 1}题的跳转条件须填写数字。`)
      if (rule.condition.operator === 'contains_all' && !rule.condition.value.length) throw new Error(`第${index + 1}题“同时包含”至少选择一个选项。`)
    }
  }
  return result
}
async function save() {
  if (busy.value) return
  error.value = ''
  busy.value = true
  try {
    const saved = await props.api(`/surveys/${props.survey.id}`, { method: 'PUT', body: payload() })
    if (!alive) return
    emit('saved', saved)
    emit('notice', '草稿已保存，可以继续配置跳转或发布。')
  } catch (e) { if (alive) { error.value = e.message; emit('notice', e.message, 'error') } }
  finally { busy.value = false }
}
function openAction(kind) {
  action.value = kind
  error.value = ''
  // datetime-local明确按北京时间解释，避免依赖电脑本地时区。
  deadline.value = props.survey.deadline ? new Date(new Date(props.survey.deadline).getTime() + 8 * 3600000).toISOString().slice(0, 16) : ''
  actionDialog.value.showModal()
}
async function performAction() {
  if (busy.value) return
  error.value = ''
  busy.value = true
  try {
    const kind = action.value
    const body = { deadline: deadline.value ? `${deadline.value}:00+08:00` : null }
    const saved = await props.api(`/surveys/${props.survey.id}/${kind}`, {
      method: kind === 'deadline' ? 'PATCH' : 'POST', ...(kind !== 'close' ? { body } : {}),
    })
    if (!alive) return
    actionDialog.value.close()
    emit('saved', saved)
    emit('notice', kind === 'publish' ? '问卷已发布，内容已锁定。' : kind === 'close' ? '问卷已关闭。' : '截止时间已更新。')
  } catch (e) { if (alive) { error.value = e.message; emit('notice', e.message, 'error') } }
  finally { busy.value = false }
}
function ruleText(rule, q) {
  const value = rule.condition.value
  const choiceText = v => q.options.find(o => o.id === v)?.label || '已失效选项'
  const condition = q.type === 'number' ? value : Array.isArray(value) ? value.map(choiceText).join('、') : choiceText(value)
  const target = rule.target.kind === 'end' ? '结束答题' : `第${form.value.questions.findIndex(item => item.id === rule.target.question_id) + 1}题`
  return `${operators[rule.condition.operator]} ${condition} → ${target}`
}
</script>

<template>
  <div class="detail-body editor">
    <div class="editor-toolbar">
      <span :class="['badge', surveyStatus(survey).tone]">{{ surveyStatus(survey).label }}</span>
      <span v-if="editable" class="muted">{{ dirty ? '有未保存修改' : '已保存' }} · 修改后请保存草稿</span>
      <span v-else class="muted">已发布内容锁定，不能修改题目或填写开关。</span>
    </div>
    <form @submit.prevent="save">
      <fieldset :disabled="busy" class="editor-fieldset">
        <div v-if="editable" class="form-stack">
          <label>问卷标题<input v-model="form.title" maxlength="100" required /></label>
          <label>问卷说明<textarea v-model="form.description" rows="3" maxlength="1000"></textarea></label>
          <div class="editor-row">
            <label class="check-label"><input v-model="form.allow_anonymous" type="checkbox" />允许匿名填写</label>
            <label class="check-label"><input v-model="form.allow_repeat" type="checkbox" />允许重复填写</label>
          </div>
        </div>
        <template v-else><h3>{{ form.title }}</h3><p class="description-full">{{ form.description || '暂无问卷说明。' }}</p>
          <p class="muted">匿名填写：{{ form.allow_anonymous ? '允许' : '不允许' }} · 重复填写：{{ form.allow_repeat ? '允许' : '不允许' }}</p>
        </template>
        <h4 class="questions-heading">题目 · {{ form.questions.length }} / 100</h4>
        <p v-if="!form.questions.length" class="muted">还没有题目，从下方选择题型添加。</p>
        <article v-for="(q, index) in form.questions" :key="q.id || `new-${index}`" class="question-card">
          <div class="editor-toolbar"><strong>第 {{ index + 1 }} 题 · {{ labels[q.type] }}</strong>
            <div v-if="editable" class="editor-row">
              <button type="button" class="text-button" :disabled="index === 0" @click="move(form.questions, index, -1)">上移</button>
              <button type="button" class="text-button" :disabled="index === form.questions.length - 1" @click="move(form.questions, index, 1)">下移</button>
              <button type="button" class="text-button danger-text" @click="form.questions.splice(index, 1)">删除题目</button>
            </div>
          </div>
          <label v-if="editable">题干<input v-model="q.title" maxlength="200" required /></label><h4 v-else>{{ q.title }}</h4>
          <label class="check-label"><input v-model="q.required" type="checkbox" :disabled="!editable" />必答</label>
          <div v-if="q.type === 'single' || q.type === 'multiple'" class="option-editor">
            <div v-for="(option, oi) in q.options" :key="option.id || `new-${oi}`" class="editor-row option-row">
              <label>选项 {{ oi + 1 }}<input v-if="editable" v-model="option.label" maxlength="100" required /><span v-else>{{ option.label }}</span></label>
              <button v-if="editable" class="text-button danger-text" type="button" :disabled="q.options.length <= 2" @click="q.options.splice(oi, 1)">删除选项</button>
            </div>
            <button v-if="editable" class="button secondary compact" type="button" :disabled="q.options.length >= 30" @click="q.options.push({ label: '' })">添加选项</button>
          </div>
          <div class="validation-grid">
            <template v-if="q.type === 'multiple'"><label>最少选择（可空）<input v-model.number="q.validation.min_choices" type="number" min="0" :max="q.options.length" step="1" :disabled="!editable" /></label><label>最多选择（可空）<input v-model.number="q.validation.max_choices" type="number" min="0" :max="q.options.length" step="1" :disabled="!editable" /></label></template>
            <template v-if="q.type === 'text'"><label>最少字符（可空）<input v-model.number="q.validation.min_length" type="number" min="0" step="1" :disabled="!editable" /></label><label>最多字符（可空）<input v-model.number="q.validation.max_length" type="number" min="0" step="1" :disabled="!editable" /></label></template>
            <template v-if="q.type === 'number'"><label>最小值（可空）<input v-model.number="q.validation.min_value" type="number" step="any" :disabled="!editable" /></label><label>最大值（可空）<input v-model.number="q.validation.max_value" type="number" step="any" :disabled="!editable" /></label>
              <label class="check-label"><input v-model="q.validation.integer_only" type="checkbox" :disabled="!editable || q.validation.phone_format" />仅允许整数</label><label class="check-label"><input v-model="q.validation.phone_format" type="checkbox" :disabled="!editable" @change="q.validation.phone_format && (q.validation.integer_only = true)" />校验11位手机号格式</label>
            </template>
          </div>
          <section class="rules-section">
            <h5>跳转规则</h5><p class="field-hint">按顺序判断，首条命中生效；未命中则进入下一题。</p>
            <p v-if="q.type === 'text'" class="muted">文本题按顺序进入下一题。</p>
            <template v-else>
              <div v-for="(rule, ri) in q.jump_rules" :key="ri" class="rule-card">
                <template v-if="editable">
                  <div class="editor-toolbar"><strong>规则 {{ ri + 1 }}</strong><div class="editor-row"><button type="button" class="text-button" :disabled="ri === 0" @click="move(q.jump_rules, ri, -1)">提高优先级</button><button type="button" class="text-button" :disabled="ri === q.jump_rules.length - 1" @click="move(q.jump_rules, ri, 1)">降低优先级</button><button type="button" class="text-button danger-text" @click="q.jump_rules.splice(ri, 1)">删除规则</button></div></div>
                  <div class="validation-grid">
                    <label>条件<select v-model="rule.condition.operator" @change="resetCondition(rule, q)"><option v-for="op in ruleOperators(q)" :key="op" :value="op">{{ operators[op] }}</option></select></label>
                    <label v-if="q.type === 'number'">比较数值<input v-model.number="rule.condition.value" type="number" step="any" required /></label>
                    <label v-else-if="rule.condition.operator !== 'contains_all'">条件选项<select v-model="rule.condition.value" required><option v-for="o in q.options.filter(item => item.id)" :key="o.id" :value="o.id">{{ o.label }}</option></select></label>
                    <div v-else><span class="field-label">同时包含的选项</span><label v-for="o in q.options.filter(item => item.id)" :key="o.id" class="check-label"><input v-model="rule.condition.value" type="checkbox" :value="o.id" />{{ o.label }}</label></div>
                    <label>跳转目标<select :value="rule.target.kind === 'end' ? 'end' : rule.target.question_id" @change="setTarget(rule, $event.target.value)"><option value="end">结束答题（进入提交确认）</option><option v-for="(target, ti) in form.questions" :key="target.id || ti" :value="target.id" :disabled="ti <= index || !target.id" :hidden="ti <= index || !target.id">第{{ ti + 1 }}题：{{ target.title }}</option></select></label>
                  </div>
                </template>
                <p v-else>{{ ruleText(rule, q) }}</p>
              </div>
              <p v-if="!q.jump_rules.length" class="field-hint">暂无跳转规则。</p>
              <button v-if="editable" type="button" class="button secondary compact" :disabled="!structureSaved" @click="addRule(q)">添加跳转规则</button>
            </template>
          </section>
        </article>
        <template v-if="editable">
          <div class="editor-row"><label>新题型<select v-model="newType"><option v-for="(label, type) in labels" :key="type" :value="type">{{ label }}</option></select></label><button class="button secondary" type="button" :disabled="form.questions.length >= 100" @click="addQuestion">添加题目</button></div>
          <p class="field-hint">先保存新题目和选项，再配置跳转。删除、重排题目或删除选项后，请同时修正引用它们的规则；保存时后端会检查。</p>
          <div class="editor-row"><button class="button primary" type="submit">{{ busy ? '处理中…' : '保存草稿' }}</button><button class="button secondary" type="button" :disabled="dirty || !form.questions.length" @click="openAction('publish')">发布问卷</button></div>
          <p v-if="dirty" class="field-hint">发布前必须先保存全部修改。收起详情、切换问卷/统计页签或刷新页面会丢失尚未保存的修改。</p>
        </template>
        <template v-else>
          <p class="muted">截止时间：{{ formatTime(survey.deadline) }}</p>
          <div class="editor-row"><button v-if="canChangeDeadline" class="button secondary" type="button" @click="openAction('deadline')">调整截止时间</button><button v-if="survey.status === 'published'" class="button secondary danger-text" type="button" @click="openAction('close')">关闭问卷</button></div>
          <p class="field-hint">填写入口和统计结果可在上方打开。已截止或关闭问卷不会再接收答卷。</p>
        </template>
      </fieldset>
    </form>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <dialog ref="actionDialog" class="create-dialog" @cancel="busy && $event.preventDefault()">
      <form @submit.prevent="performAction">
        <h2>{{ action === 'publish' ? '确认发布问卷' : action === 'close' ? '确认关闭问卷' : '调整截止时间' }}</h2>
        <p class="muted">{{ action === 'publish' ? '发布后标题、说明、题目、跳转和填写开关全部锁定，仅可在截止前调整截止时间。' : action === 'close' ? '关闭后立即停止接收答卷，不能重新开放；已有答卷保留。' : '仅能在原截止时间到达前调整，已截止问卷不能恢复。' }}</p>
        <label v-if="action !== 'close'">截止时间（北京时间，可空）<input v-model="deadline" type="datetime-local" :disabled="busy" /><small class="field-hint">留空表示不设置截止时间。</small></label>
        <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
        <div class="dialog-actions"><button class="button secondary" type="button" :disabled="busy" @click="actionDialog.close()">取消</button><button class="button primary" type="submit" :disabled="busy">{{ busy ? '处理中…' : '确认' }}</button></div>
      </form>
    </dialog>
  </div>
</template>
