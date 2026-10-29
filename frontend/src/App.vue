<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import SurveyEditor from './components/SurveyEditor.vue'
import SurveyFill from './pages/SurveyFill.vue'
import SurveyStatistics from './pages/SurveyStatistics.vue'
import QuestionLibrary from './pages/QuestionLibrary.vue'
import QuestionBanks from './pages/QuestionBanks.vue'
import { formatTime, request, surveyStatus } from './api.js'

const origin = window.location.origin
const sessionKey = 'survey_access_token'
function storedToken() { try { return sessionStorage.getItem(sessionKey) || '' } catch { return '' } }
const token = ref(storedToken())
const user = ref(null)
const initializing = ref(true)
const authMode = ref('login')
const credentials = reactive({ username: '', password: '' })
const authBusy = ref(false)
const listBusy = ref(false)
const detailBusy = ref(false)
const createBusy = ref(false)
const deleteBusy = ref(false)
const deleteDialog = ref(null)
const deleteTarget = ref(null)
const deleteError = ref('')
const notice = ref(null)
const surveys = ref([])
const total = ref(0)
const offset = ref(0)
const pageSize = 10
const selected = ref(null)
const selectedPanel = ref('details')
const workspaceTab = ref('surveys')
const initialQuestionId = ref('')
function openQuestion(id = '') { initialQuestionId.value = id; workspaceTab.value = 'questions' }
// 当前只有工作台与填写链接两种入口，用原生链接导航即可，无需引入路由库。
const fillSurveyId = window.location.pathname.match(/^\/survey\/([^/]+)\/?$/)?.[1] || ''
const createDialog = ref(null)
const draft = reactive({ title: '', description: '', allow_anonymous: false, allow_repeat: false })
let sessionVersion = 0
let detailVersion = 0
const pageNumber = computed(() => Math.floor(offset.value / pageSize) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

let noticeTimer
watch(notice, (value) => {
  clearTimeout(noticeTimer)
  if (value) noticeTimer = setTimeout(() => { notice.value = null }, 5000)
}, { flush: 'sync' })
onUnmounted(() => clearTimeout(noticeTimer))
function notify(message, kind = 'success') { notice.value = { message, kind } }
async function surveySaved(value) {
  if (!user.value || selected.value?.id !== value.id) return
  selected.value = value
  await loadSurveys()
}
function saveToken(value) {
  token.value = value
  try { value ? sessionStorage.setItem(sessionKey, value) : sessionStorage.removeItem(sessionKey) } catch { /* 存储受限时仅保留当前页面内存。 */ }
}
function clearSession() {
  sessionVersion++
  detailVersion++
  saveToken('')
  user.value = null
  surveys.value = []
  selected.value = null
  listBusy.value = false
  detailBusy.value = false
  total.value = 0
  offset.value = 0
  credentials.password = ''
  createDialog.value?.close()
  deleteDialog.value?.close()
  deleteTarget.value = null
}
function logout() { clearSession(); notify('已退出登录。') }
async function api(path, options = {}) {
  const usedToken = token.value
  try { return await request(path, { ...options, token: usedToken }) }
  catch (error) {
    if (error.status === 401 && token.value === usedToken) {
      clearSession()
      error.message = '登录已失效，请重新登录。'
      notify(error.message, 'error')
    }
    throw error
  }
}
async function authenticate() {
  if (authBusy.value) return
  authBusy.value = true
  notice.value = null
  try {
    const body = { username: credentials.username.trim(), password: credentials.password }
    if (authMode.value === 'register') {
      const registered = await request('/auth/register', { method: 'POST', body })
      credentials.username = registered.username
      credentials.password = ''
      authMode.value = 'login'
      notify('注册成功，请使用新账号登录。')
    } else {
      const result = await request('/auth/login', { method: 'POST', body })
      sessionVersion++
      saveToken(result.access_token)
      credentials.password = ''
      user.value = await api('/auth/me')
      const loaded = fillSurveyId ? true : await loadSurveys(0)
      if (user.value && loaded) notify('登录成功。')
    }
  } catch (error) { notify(error.message, 'error') }
  finally { authBusy.value = false }
}
async function loadSurveys(nextOffset = offset.value) {
  const version = sessionVersion
  listBusy.value = true
  try {
    const result = await api(`/surveys?offset=${nextOffset}&limit=${pageSize}`)
    if (version !== sessionVersion) return
    surveys.value = result.items
    total.value = result.total
    offset.value = nextOffset
    return true
  } catch (error) { if (version === sessionVersion || !user.value) notify(error.message, 'error') }
  finally { if (version === sessionVersion) listBusy.value = false }
}
function openCreate() {
  Object.assign(draft, { title: '', description: '', allow_anonymous: false, allow_repeat: false })
  notice.value = null
  createDialog.value.showModal()
}
async function createDraft() {
  if (createBusy.value) return
  if (!draft.title.trim()) { notify('请填写问卷标题。', 'error'); return }
  const version = sessionVersion
  createBusy.value = true
  try {
    const result = await api('/surveys', { method: 'POST', body: { ...draft, title: draft.title.trim() } })
    if (version !== sessionVersion) return
    selected.value = result
    selectedPanel.value = 'details'
    createDialog.value.close()
    const loaded = await loadSurveys(0)
    if (version === sessionVersion && loaded) notify('问卷草稿已创建。')
  } catch (error) { notify(error.message, 'error') }
  finally { createBusy.value = false }
}
async function showDetail(id, panel = 'details') {
  const version = sessionVersion
  const requestVersion = ++detailVersion
  detailBusy.value = true
  selected.value = null
  selectedPanel.value = panel
  try {
    const detail = await api(`/surveys/${id}`)
    if (version === sessionVersion && requestVersion === detailVersion) selected.value = detail
  } catch (error) { notify(error.message, 'error') }
  finally { if (requestVersion === detailVersion) detailBusy.value = false }
}
function openDelete(survey) {
  deleteTarget.value = { id: survey.id, title: survey.title, status: survey.status }
  deleteError.value = ''
  deleteDialog.value.showModal()
}
async function deleteDraft() {
  if (deleteBusy.value || deleteTarget.value?.status !== 'draft') return
  const target = deleteTarget.value
  const version = sessionVersion
  deleteBusy.value = true
  deleteError.value = ''
  try {
    await api(`/surveys/${target.id}`, { method: 'DELETE' })
    if (version !== sessionVersion) return
    deleteDialog.value.close()
    if (selected.value?.id === target.id) hideDetail()
    // 删除当前页最后一项时回到有效页码，避免出现空白的末页。
    const lastOffset = Math.floor(Math.max(0, total.value - 2) / pageSize) * pageSize
    const loaded = await loadSurveys(Math.min(offset.value, lastOffset))
    if (version === sessionVersion && loaded) notify('问卷草稿已删除。')
  } catch (error) {
    if (version === sessionVersion) deleteError.value = error.message
  } finally { deleteBusy.value = false }
}
function hideDetail() { detailVersion++; selected.value = null; detailBusy.value = false }
onMounted(async () => {
  if (token.value) {
    try { user.value = await api('/auth/me'); if (!fillSurveyId) await loadSurveys(0) }
    catch (error) { notify(error.message, 'error') }
  }
  initializing.value = false
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="/" aria-label="问卷工作台首页"><span class="brand-mark" aria-hidden="true">问</span>问卷工作台</a>
      <div v-if="user" class="account"><span>当前账号 <strong>{{ user.username }}</strong></span><button class="button ghost compact" @click="logout">退出登录</button></div>
      <span v-else class="topbar-note">在线问卷系统</span>
    </header>

    <main>
      <div v-if="notice" :class="['notice', notice.kind]" :role="notice.kind === 'error' ? 'alert' : 'status'">
        <span>{{ notice.message }}</span><button class="notice-close" aria-label="关闭提示" @click="notice = null">×</button>
      </div>
      <div v-if="initializing" class="loading-state" role="status">正在加载…</div>

      <section v-else-if="!user" class="auth-layout">
        <div class="intro">
          <p class="eyebrow">从一份问卷开始</p>
          <h1>把问题整理好，<br />让回答有据可查。</h1>
          <p class="intro-copy">创建自己的问卷，收集回答，查看结果。</p>
          <div class="intro-steps"><span><b>01</b> 创建问卷</span><span><b>02</b> 收集回答</span><span><b>03</b> 查看统计</span></div>
        </div>
        <section class="panel auth-panel" aria-labelledby="auth-title">
          <div class="auth-tabs"><button :class="{ active: authMode === 'login' }" :disabled="authBusy" @click="authMode = 'login'; notice = null">登录</button><button :class="{ active: authMode === 'register' }" :disabled="authBusy" @click="authMode = 'register'; notice = null">注册账号</button></div>
          <h2 id="auth-title">{{ authMode === 'login' ? '欢迎回来' : '创建你的账号' }}</h2>
          <p class="muted">{{ authMode === 'login' ? (fillSurveyId ? '请先登录，登录后继续填写当前问卷。' : '登录后管理你的问卷。') : '注册成功后即可登录。' }}</p>
          <form class="form-stack" @submit.prevent="authenticate">
            <label>用户名<input v-model="credentials.username" name="username" autocomplete="username" minlength="3" maxlength="30" pattern="[A-Za-z0-9_]{3,30}" placeholder="输入用户名" required :disabled="authBusy" /></label>
            <p class="field-hint">3～30 位英文字母、数字或下划线，区分大小写。</p>
            <label>密码<input v-model="credentials.password" name="password" type="password" :autocomplete="authMode === 'login' ? 'current-password' : 'new-password'" minlength="6" maxlength="30" placeholder="输入 6～30 位密码" required :disabled="authBusy" /></label>
            <button class="button primary wide" :disabled="authBusy" type="submit">{{ authBusy ? '处理中…' : authMode === 'login' ? '登录' : '注册账号' }}</button>
          </form>
        </section>
      </section>

      <SurveyFill v-else-if="fillSurveyId" :key="`${user.id}-${fillSurveyId}`" :survey-id="fillSurveyId" :api="api" @notice="notify" />

      <div v-else class="workspace">
        <aside class="sidebar"><div class="sidebar-caption">工作台</div><button class="workspace-nav" :class="{ 'nav-current': workspaceTab === 'surveys' }" @click="workspaceTab = 'surveys'">我的问卷 <span>{{ total }}</span></button><button class="workspace-nav" :class="{ 'nav-current': workspaceTab === 'questions' }" @click="openQuestion()">我的题目</button><button class="workspace-nav" :class="{ 'nav-current': workspaceTab === 'banks' }" @click="workspaceTab = 'banks'">我的题库</button><p class="sidebar-note">问卷内仍可直接创建临时题目。</p></aside>
        <QuestionLibrary v-if="workspaceTab === 'questions'" :key="`${user.id}-${initialQuestionId}`" :api="api" :user-id="user.id" :initial-question-id="initialQuestionId" @notice="notify" />
        <QuestionBanks v-else-if="workspaceTab === 'banks'" :key="user.id" :api="api" @notice="notify" @open-question="openQuestion" />
        <section v-else class="workspace-content">
          <div class="page-heading"><div><p class="eyebrow">工作台</p><h1>我的问卷</h1><p class="muted">共 {{ total }} 份问卷</p></div><button class="button primary" @click="openCreate">＋ 新建问卷</button></div>
          <section class="panel list-panel" aria-labelledby="list-title">
            <div class="panel-heading"><h2 id="list-title">问卷列表</h2><button class="button ghost compact" :disabled="listBusy" @click="loadSurveys()">{{ listBusy ? '加载中…' : '刷新列表' }}</button></div>
            <div v-if="listBusy" class="loading-state" role="status">正在读取问卷…</div>
            <div v-else-if="!surveys.length" class="empty-state"><div class="empty-icon" aria-hidden="true">▤</div><h3>这里还没有问卷</h3><p>先创建一份草稿，保存标题和问卷说明。</p><button class="button secondary" @click="openCreate">创建第一份问卷</button></div>
            <div v-else class="table-wrap"><table><thead><tr><th>问卷</th><th>状态</th><th>创建时间</th><th>截止时间</th><th class="align-right">操作</th></tr></thead><tbody><tr v-for="survey in surveys" :key="survey.id"><td><strong class="survey-title">{{ survey.title }}</strong><span class="survey-description">{{ survey.description || '暂无说明' }}</span></td><td><span :class="['badge', surveyStatus(survey).tone]">{{ surveyStatus(survey).label }}</span></td><td class="time-cell">{{ formatTime(survey.created_at) }}</td><td class="time-cell">{{ formatTime(survey.deadline) }}</td><td class="align-right"><div class="table-actions"><button class="text-button" @click="showDetail(survey.id)">查看详情</button><button class="text-button" @click="showDetail(survey.id, 'statistics')">查看统计</button><button class="text-button danger-text" :disabled="deleteBusy" @click="openDelete(survey)">删除</button></div></td></tr></tbody></table></div>
            <div class="pagination"><span>第 {{ pageNumber }} / {{ pageCount }} 页</span><div><button class="button ghost compact" :disabled="listBusy || offset === 0" @click="loadSurveys(offset - pageSize)">上一页</button><button class="button ghost compact" :disabled="listBusy || offset + pageSize >= total" @click="loadSurveys(offset + pageSize)">下一页</button></div></div>
          </section>

          <section v-if="detailBusy || selected" class="panel detail-panel" aria-labelledby="detail-title">
            <div class="panel-heading"><h2 id="detail-title">问卷详情</h2><button class="button ghost compact" @click="hideDetail">收起</button></div>
            <div v-if="detailBusy" class="loading-state" role="status">正在读取详情…</div>
            <template v-else-if="selected">
              <div class="detail-tabs"><button class="button compact" :class="selectedPanel === 'details' ? 'primary' : 'secondary'" @click="selectedPanel = 'details'">{{ selected.status === 'draft' ? '编辑问卷' : '问卷详情' }}</button><button class="button compact" :class="selectedPanel === 'statistics' ? 'primary' : 'secondary'" @click="selectedPanel = 'statistics'">统计结果</button><a v-if="selected.status !== 'draft'" class="button secondary compact" :href="`/survey/${selected.id}`">填写问卷</a></div>
              <div v-if="selected.status !== 'draft'" class="share-entry"><label>填写链接（需登录）<input :value="`${origin}/survey/${selected.id}`" readonly @focus="$event.target.select()" /></label></div>
              <SurveyEditor v-if="selectedPanel === 'details'" :key="selected.id" :survey="selected" :api="api" @saved="surveySaved" @notice="notify" />
              <SurveyStatistics v-else :key="selected.id" :survey="selected" :api="api" />
            </template>
          </section>
        </section>
      </div>
    </main>

    <dialog ref="createDialog" class="create-dialog" @cancel="createBusy && $event.preventDefault()">
      <form @submit.prevent="createDraft"><div class="dialog-heading"><div><p class="eyebrow">新问卷</p><h2>创建问卷草稿</h2></div><button class="notice-close" type="button" aria-label="关闭新建窗口" :disabled="createBusy" @click="createDialog.close()">×</button></div><div class="form-stack"><label>问卷标题 <span class="required-mark">*</span><input v-model="draft.title" name="title" maxlength="100" placeholder="例如：课程学习情况调查" required :disabled="createBusy" /></label><label>问卷说明<textarea v-model="draft.description" name="description" rows="4" maxlength="1000" placeholder="说明问卷的目的和填写要求（选填）" :disabled="createBusy"></textarea></label><div class="checkbox-group"><label class="check-label"><input v-model="draft.allow_anonymous" type="checkbox" :disabled="createBusy" /><span>允许匿名填写<small>填写者仍须登录，可选择不向创建者展示身份。</small></span></label><label class="check-label"><input v-model="draft.allow_repeat" type="checkbox" :disabled="createBusy" /><span>允许重复填写<small>每次提交独立保存，统计采用每人最新答卷。</small></span></label></div></div><p v-if="notice?.kind === 'error'" class="inline-error" role="alert">{{ notice.message }}</p><div class="dialog-actions"><button class="button secondary" type="button" :disabled="createBusy" @click="createDialog.close()">取消</button><button class="button primary" :disabled="createBusy" type="submit">{{ createBusy ? '创建中…' : '创建草稿' }}</button></div></form>
    </dialog>
    <dialog ref="deleteDialog" class="create-dialog" aria-labelledby="delete-title" @cancel="deleteBusy && $event.preventDefault()">
      <form @submit.prevent="deleteDraft">
        <div class="dialog-heading"><h2 id="delete-title">{{ deleteTarget?.status === 'draft' ? '删除问卷草稿' : '暂不支持删除' }}</h2><button class="notice-close" type="button" aria-label="关闭删除窗口" :disabled="deleteBusy" @click="deleteDialog.close()">×</button></div>
        <p class="delete-survey-title">{{ deleteTarget?.title }}</p>
        <p class="muted">{{ deleteTarget?.status === 'draft' ? '确认永久删除这份草稿及其中的题目和配置？删除后不可恢复。' : '当前尚不支持该状态下的问卷删除。问卷与已有答卷将继续保留。' }}</p>
        <p v-if="deleteError" class="inline-error" role="alert">{{ deleteError }}</p>
        <div class="dialog-actions">
          <button class="button secondary" type="button" :disabled="deleteBusy" @click="deleteDialog.close()">{{ deleteTarget?.status === 'draft' ? '取消' : '知道了' }}</button>
          <button v-if="deleteTarget?.status === 'draft'" class="button danger-text" type="submit" :disabled="deleteBusy">{{ deleteBusy ? '删除中…' : '确认删除' }}</button>
        </div>
      </form>
    </dialog>
    <footer>问卷工作台 · 课程项目</footer>
  </div>
</template>
