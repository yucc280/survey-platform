// 只负责浏览器交互；后端在validate和提交时会重新计算路径并校验。
export const questionLabels = { single: '单选题', multiple: '多选题', text: '文本填空', number: '数字填空' }
const empty = value => value == null || value === '' || (Array.isArray(value) && !value.length)

export function questionError(q, value) {
  const v = q.type === 'text' && typeof value === 'string' ? value.trim() : value
  if (empty(v)) return q.required ? '这是一道必答题，请先作答。' : ''
  const config = q.validation || {}
  if (q.type === 'single') return q.options.some(o => o.id === v) ? '' : '请选择有效选项。'
  if (q.type === 'multiple') {
    if (!Array.isArray(v) || new Set(v).size !== v.length || v.some(id => !q.options.some(o => o.id === id))) return '请选择有效选项。'
    if (v.length < (config.min_choices ?? 0) || v.length > (config.max_choices ?? q.options.length)) return '选择数量不符合要求。'
  }
  if (q.type === 'text') {
    const length = [...v].length
    if (length < (config.min_length ?? 0) || length > (config.max_length ?? Infinity)) return '文字长度不符合要求。'
  }
  if (q.type === 'number') {
    const raw = String(v)
    if (config.phone_format && !/^1[3-9][0-9]{9}$/.test(raw)) return '手机号须为11位数字，首位1、第二位3～9，不带空格或分隔符。'
    if (!/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/.test(raw.trim())) return '请填写普通十进制数字，不使用科学计数法。'
    const n = Number(raw)
    if (!Number.isFinite(n)) return '请填写有限数字。'
    const fraction = raw.trim().split('.')[1] || ''
    if (config.integer_only && /[1-9]/.test(fraction)) return '该题必须填写整数。'
    if (config.min_value != null && n < config.min_value) return '数字小于允许的最小值。'
    if (config.max_value != null && n > config.max_value) return '数字大于允许的最大值。'
  }
  return ''
}

export function nextTarget(q, raw) {
  if (empty(raw)) return null
  if (q.type === 'number' && questionError(q, raw)) return null
  const value = q.type === 'number' ? Number(raw) : raw
  for (const rule of q.jump_rules || []) {
    const { operator: op, value: expected } = rule.condition
    const hit = op === 'equals' ? value === expected
      : op === 'contains' ? Array.isArray(value) && value.includes(expected)
      : op === 'contains_all' ? Array.isArray(value) && expected.every(item => value.includes(item))
      : op === 'gt' ? value > expected : op === 'gte' ? value >= expected
      : op === 'lt' ? value < expected : op === 'lte' ? value <= expected
      : op === 'eq' ? value === expected : false
    if (hit) return rule.target
  }
  return null
}

export function effectivePath(questions, answers) {
  const path = []
  const positions = new Map(questions.map((q, i) => [q.id, i]))
  let index = 0
  while (index < questions.length) {
    const q = questions[index]
    path.push(q)
    const target = nextTarget(q, answers[q.id])
    if (!target) index++
    else if (target.kind === 'end') break
    else {
      const next = positions.get(target.question_id)
      if (next == null || next <= index) throw new Error('跳转配置无效，请联系问卷创建者。')
      index = next
    }
  }
  return path
}

export function pruneAnswers(questions, answers) {
  const ids = new Set(effectivePath(questions, answers).map(q => q.id))
  return Object.fromEntries(Object.entries(answers).filter(([id]) => ids.has(id)))
}

export function displayAnswer(question, value) {
  if (empty(value)) return '未填写'
  const option = id => question.options.find(o => o.id === id)?.label || '未知选项'
  if (question.type === 'single') return option(value)
  if (question.type === 'multiple') return value.map(option).join('、')
  return String(value)
}
