import test from 'node:test'
import assert from 'node:assert/strict'
import { displayAnswer, effectivePath, nextTarget, pruneAnswers, questionError } from './answerFlow.js'

const rule = (operator, value, target) => ({ condition: { operator, value }, target })
const questions = [
  { id: 'q1', type: 'single', title: '入口', required: true, options: [{ id: 'a', label: '跳转' }, { id: 'b', label: '顺序' }], validation: {}, jump_rules: [rule('equals', 'a', { kind: 'question', question_id: 'q3' })] },
  { id: 'q2', type: 'text', title: '文本', options: [], validation: {}, required: true, jump_rules: [] },
  { id: 'q3', type: 'number', title: '数字', options: [], validation: {}, required: false, jump_rules: [] },
]
test('修改前面的回答后，跳过的必答题和旧答案被移除，当前路径答案保留', () => {
  const values = { q1: 'a', q2: '旧文本', q3: '0' }
  assert.deepEqual(effectivePath(questions, values).map(q => q.id), ['q1', 'q3'])
  assert.deepEqual(pruneAnswers(questions, values), { q1: 'a', q3: '0' })
  assert.deepEqual(effectivePath(questions, { q1: 'b' }).map(q => q.id), ['q1', 'q2', 'q3'])
})
test('结束目标和多条规则首条命中，不合并目标', () => {
  const q = { ...questions[0], jump_rules: [rule('equals', 'a', { kind: 'end' }), ...questions[0].jump_rules] }
  assert.deepEqual(nextTarget(q, 'a'), { kind: 'end' })
  assert.deepEqual(effectivePath([q, ...questions.slice(1)], { q1: 'a' }).map(item => item.id), ['q1'])
})
test('多选同时包含允许额外选项，空答不命中', () => {
  const q = { type: 'multiple', jump_rules: [rule('contains_all', ['a', 'b'], { kind: 'end' })] }
  assert.deepEqual(nextTarget(q, ['a', 'b', 'c']), { kind: 'end' })
  assert.equal(nextTarget(q, ['a']), null)
  assert.equal(nextTarget(q, []), null)
})
test('数字0有效，数值比较与空答区分', () => {
  const q = { ...questions[2], jump_rules: [rule('eq', 0, { kind: 'end' })] }
  assert.deepEqual(nextTarget(q, '0'), { kind: 'end' })
  assert.equal(nextTarget(q, ''), null)
})
test('无效向后循环配置拒绝计算，避免页面死循环', () => {
  const q = { ...questions[0], jump_rules: [rule('equals', 'a', { kind: 'question', question_id: 'q1' })] }
  assert.throws(() => effectivePath([q], { q1: 'a' }), /配置无效/)
})
test('文本去首尾空白、Unicode字符计数；选答空答不受最少长度限制', () => {
  const q = { ...questions[1], validation: { min_length: 1, max_length: 1 } }
  assert.equal(questionError(q, ' 😀 '), '')
  assert.match(questionError(q, '  '), /必答/)
  assert.equal(questionError({ ...q, required: false }, ''), '')
})
test('手机号检查原始格式，整数检查不依赖浮点舍入', () => {
  const q = { ...questions[2], validation: { integer_only: true, phone_format: true } }
  assert.equal(questionError(q, '13800138000'), '')
  for (const value of ['13800138000.0', ' 13800138000', '+8613800138000', '12800138000']) assert.notEqual(questionError(q, value), '')
  assert.notEqual(questionError({ ...q, validation: { integer_only: true } }, '1.00000000000000001'), '')
})
test('答案显示选项文字，不展示内部选项ID；数字0不显示为空', () => {
  assert.equal(displayAnswer(questions[0], 'a'), '跳转')
  assert.equal(displayAnswer(questions[2], 0), '0')
  assert.equal(displayAnswer(questions[1], null), '未填写')
})
