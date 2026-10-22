export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

export async function request(path, { token, method = 'GET', body } = {}) {
  const headers = { Accept: 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 10000)
  try {
    const response = await fetch(`/api${path}`, {
      method, headers, signal: controller.signal,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
    let data
    try { data = await response.json() } catch { throw new ApiError('服务响应异常，请确认后端已启动。', response.status) }
    if (!response.ok) {
      const detail = data.detail
      const message = typeof detail === 'string' ? detail
        : Array.isArray(detail) ? detail.map(item => item.msg).join('；')
        : '操作未完成，请稍后重试。'
      throw new ApiError(message, response.status)
    }
    return data
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(error.name === 'AbortError' ? '请求超时，请稍后重试。' : '无法连接服务，请确认前后端均已启动。', 0)
  } finally {
    clearTimeout(timeout)
  }
}

export function formatTime(value) {
  if (!value) return '未设置'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间不可用'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(date)
}

export function surveyStatus(survey) {
  if (survey.status === 'draft') return { label: '草稿', tone: 'draft' }
  if (survey.status === 'closed') return { label: '已关闭', tone: 'muted' }
  if (survey.deadline && new Date(survey.deadline).getTime() <= Date.now()) return { label: '已截止', tone: 'muted' }
  return { label: '已发布', tone: 'published' }
}
