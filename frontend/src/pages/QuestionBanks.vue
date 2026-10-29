<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import QuestionVersionPicker from '../components/QuestionVersionPicker.vue'
import { questionLabels } from '../utils/answerFlow.js'

const props = defineProps({ api: { type: Function, required: true } })
const emit = defineEmits(['notice', 'open-question'])
const banks = ref([]), total = ref(0), offset = ref(0), busy = ref(false), error = ref('')
const newName = ref(''), editName = ref(''), selected = ref(null), members = ref([]), memberOffset = ref(0)
const picking = ref(false)
let alive = true
onUnmounted(() => { alive = false })
async function run(work) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await work() } catch (e) { if (alive) error.value = e.message }
  finally { if (alive) busy.value = false }
}
async function list(next = offset.value) {
  const data = await props.api(`/question-banks?offset=${next}&limit=20`)
  if (alive) { banks.value = data.items; total.value = data.total; offset.value = next }
}
async function open(id, next = 0) {
  const data = await props.api(`/question-banks/${id}?offset=${next}&limit=20`)
  if (!alive) return
  if (next > 0 && next >= data.total) return open(id, Math.max(0, Math.floor((data.total - 1) / 20) * 20))
  selected.value = data; members.value = data.items; memberOffset.value = next; editName.value = data.name
}
function create() {
  return run(async () => {
    const data = await props.api('/question-banks', { method: 'POST', body: { name: newName.value } })
    if (!alive) return
    newName.value = ''; picking.value = false; await list(0); if (alive) await open(data.id)
    if (alive) emit('notice', '题库已创建，可以添加已有的可复用题目。')
  })
}
function rename() {
  return run(async () => {
    await props.api(`/question-banks/${selected.value.id}`, { method: 'PATCH', body: { name: editName.value, expected_revision: selected.value.revision } })
    if (!alive) return
    await open(selected.value.id, memberOffset.value); await list()
    if (alive) emit('notice', '题库名称已保存。')
  })
}
function add(reference) {
  return run(async () => {
    await props.api(`/question-banks/${selected.value.id}/questions/${reference.question_id}`, { method: 'PUT', body: { expected_revision: selected.value.revision } })
    if (!alive) return
    picking.value = false; await open(selected.value.id); await list()
    if (alive) emit('notice', '题目已加入题库，未复制题目或创建版本。')
  })
}
function remove(id) {
  return run(async () => {
    await props.api(`/question-banks/${selected.value.id}/questions/${id}?expected_revision=${selected.value.revision}`, { method: 'DELETE' })
    if (!alive) return
    await open(selected.value.id, memberOffset.value); await list()
    if (alive) emit('notice', '已移出题库，题目、版本和问卷引用均保留。')
  })
}
function deleteBank() {
  if (!window.confirm('删除这个题库？分享ID将失效，题目和已有问卷仍然保留。')) return
  return run(async () => {
    await props.api(`/question-banks/${selected.value.id}?expected_revision=${selected.value.revision}`, { method: 'DELETE' })
    if (!alive) return
    selected.value = null; picking.value = false; await list(0)
    if (alive) emit('notice', '题库已删除，题目和已有问卷保留。')
  })
}
onMounted(() => run(() => list(0)))
</script>

<template>
  <div class="workspace-content">
    <div class="page-heading"><div><p class="eyebrow">分类组织</p><h1>我的题库</h1><p class="muted">题库组织自己创建的题目；将题库ID分享给他人即可选用。</p></div></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }} 如提示内容已变化，请刷新题库后重试。</p>
    <section class="panel detail-body">
      <form class="editor-row" @submit.prevent="create"><label>新题库名称<input v-model="newName" required maxlength="100" :disabled="busy" /></label><button class="button primary" :disabled="busy" type="submit">创建题库</button></form>
      <div class="editor-toolbar"><h2>题库列表（{{ total }}）</h2><button class="button secondary" :disabled="busy" @click="run(async () => { await list(); if (alive && selected) await open(selected.id, memberOffset) })">刷新题库</button></div>
      <p v-if="!banks.length && !busy" class="muted">还没有题库，可以先创建一个分类。</p>
      <div v-for="bank in banks" :key="bank.id" class="library-list-row"><div><strong>{{ bank.name }}</strong><p class="muted">{{ bank.question_count }} 道题目关联</p></div><button class="button secondary" :disabled="busy" @click="run(async () => { picking = false; await open(bank.id) })">管理题库</button></div>
      <div class="editor-row"><button class="button secondary compact" :disabled="busy || offset === 0" @click="run(() => list(offset - 20))">上一页题库列表</button><button class="button secondary compact" :disabled="busy || offset + 20 >= total" @click="run(() => list(offset + 20))">下一页题库列表</button></div>
    </section>
    <section v-if="selected" class="panel detail-body library-detail">
      <div class="editor-toolbar"><h2>{{ selected.name }}</h2><button class="button secondary compact" :disabled="busy" @click="selected = null; picking = false">收起题库</button></div>
      <p class="field-hint">题库分享 ID：<strong>{{ selected.id }}</strong>。其他登录用户可在问卷选题时输入此ID，只能浏览和选用。</p>
      <button class="text-button danger-text" :disabled="busy" @click="deleteBank">删除题库</button>
      <form class="editor-row" @submit.prevent="rename"><label>修改题库名称<input v-model="editName" required maxlength="100" :disabled="busy" /></label><button class="button secondary" type="submit" :disabled="busy">保存名称</button></form>
      <p class="field-hint">关联 {{ selected.question_count }} 道，当前可访问 {{ selected.total }} 道。移出只改变分类，不会删除题目或影响问卷。</p>
      <p v-if="selected.unavailable_count" class="inline-warning">{{ selected.unavailable_count }} 道题目当前不可访问，内容已隐藏；已有问卷快照仍然有效。</p>
      <div v-for="q in members" :key="q.id" class="library-list-row"><div><strong>{{ q.current_version.content.title }}</strong><p class="muted">{{ questionLabels[q.current_version.content.type] }} · 当前 v{{ q.current_version.number }}</p></div><div class="editor-row"><button class="text-button" :disabled="busy" @click="emit('open-question', q.id)">详情 / 版本 / 分析</button><button class="text-button danger-text" :disabled="busy" @click="remove(q.id)">移出题库</button></div></div>
      <p v-if="!members.length && !busy" class="muted">暂无可访问的成员题目。</p>
      <div class="editor-row"><button class="button secondary compact" :disabled="busy || memberOffset === 0" @click="run(() => open(selected.id, memberOffset - 20))">上一页成员</button><button class="button secondary compact" :disabled="busy || memberOffset + 20 >= selected.total" @click="run(() => open(selected.id, memberOffset + 20))">下一页成员</button><button class="button primary" :disabled="busy" @click="picking = !picking">添加已有题目</button></div>
      <QuestionVersionPicker v-if="picking" :key="selected.id" :api="api" purpose="bank" :disabled="busy" @select="add" @cancel="picking = false" />
    </section>
  </div>
</template>
