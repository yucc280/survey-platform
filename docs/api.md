# API 说明

## 1. 调用约定

- 本地地址：`http://127.0.0.1:8000`；交互式文档：`/docs`。
- 请求与响应使用 JSON；请求体设置 `Content-Type: application/json`。
- ID 使用字符串，时间使用带时区的 ISO 8601 格式。
- 除注册、登录和健康检查外，接口均需登录；匿名填写也需登录。
- 管理与统计接口仅供问卷创建者访问，填写接口可访问他人的开放问卷。

登录后，在请求头中携带令牌；使用 `/docs` 时可通过 **Authorize** 配置：

```http
Authorization: Bearer <access_token>
```

### 通用状态码

| 状态码 | 含义 |
| --- | --- |
| `200` | 查询或操作成功 |
| `201` | 注册、创建问卷或提交答卷成功 |
| `401` | 未登录、凭证错误或令牌无效/过期 |
| `404` | 资源不存在、ID 非法或无查看/管理权限 |
| `409` | 状态不允许、重复冲突或并发修改冲突 |
| `422` | 参数、配置、答案或答题路径不合法 |

## 2. 账号与健康检查

| 方法 | 路径 | 请求 | 成功响应 |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | `username`、`password` | `201`：`id`、`username`、`created_at` |
| POST | `/api/auth/login` | `username`、`password` | `200`：`access_token`、`token_type`、`expires_in` |
| GET | `/api/auth/me` | 无 | `200`：当前用户的 `id`、`username`、`created_at` |
| GET | `/api/health` | 无 | `200`：`{"status":"ok"}`，检查数据库连接 |

注册和登录请求示例：

```json
{"username": "demo_user", "password": "example_password"}
```

登录响应示例（令牌为占位值）：

```json
{
  "access_token": "<access_token>",
  "token_type": "bearer",
  "expires_in": 7200
}
```

用户名去首尾空白，区分大小写，长度 3～30，仅允许英文字母、数字和下划线；密码长度 6～30，不自动去空白。注册不自动登录，同名注册返回 `409`；登录凭证错误返回 `401`。令牌有效期两小时，当前无刷新令牌和服务端撤销接口。

## 3. 问卷管理

本节接口均需创建者登录。

### 3.1 创建、列表与详情

| 方法 | 路径 | 输入 | 成功响应 |
| --- | --- | --- | --- |
| POST | `/api/surveys` | 创建参数，见下表 | `201`：问卷详情 |
| GET | `/api/surveys` | 查询参数 `offset=0`、`limit=20`（1～100） | `200`：`items`、`total`、`offset`、`limit` |
| GET | `/api/surveys/{survey_id}` | 路径参数：问卷 ID | `200`：问卷详情 |

| 创建参数 | 类型 | 必填 | 默认值与限制 |
| --- | --- | --- | --- |
| `title` | String | 是 | 去首尾空白后 1～100 字符 |
| `description` | String | 否 | `""`，最多 1000 字符 |
| `allow_anonymous` | Boolean | 否 | `false` |
| `allow_repeat` | Boolean | 否 | `false` |

创建请求示例：

```json
{
  "title": "学习情况调查",
  "description": "了解数据库学习情况",
  "allow_anonymous": true,
  "allow_repeat": false
}
```

新问卷为 `draft`，`questions=[]`、`deadline=null`。详情返回 `id`、`owner_id`、`title`、`description`、`status`、两个开关、`deadline`、`questions`、`created_at`、`updated_at`。列表只返回本人的问卷，按创建时间降序、ID 降序排列，`items` 不包含 `questions`。

### 3.2 完整保存草稿

`PUT /api/surveys/{survey_id}` → `200`：保存后的问卷详情。

| 请求字段 | 要求 |
| --- | --- |
| `title` | 必填 |
| `questions` | 必填，最多 100 题；`[]` 删除全部题目 |
| `description` | 省略时重置为 `""` |
| `allow_anonymous`、`allow_repeat` | 省略时重置为 `false` |

**该接口完整替换编辑内容。** 请发送需要保留的字段，不要直接提交含只读字段的整份详情响应。

首次添加题目示例：

```json
{
  "title": "学习情况调查",
  "description": "了解数据库学习情况",
  "allow_anonymous": true,
  "allow_repeat": false,
  "questions": [
    {
      "type": "single",
      "title": "是否学过 MongoDB？",
      "required": true,
      "options": [{"label": "是"}, {"label": "否"}],
      "validation": {}
    },
    {
      "type": "number",
      "title": "每周学习小时数",
      "required": true,
      "validation": {"min_value": 0, "max_value": 168, "integer_only": true}
    }
  ]
}
```

题目配置：

| 字段 | 类型与说明 |
| --- | --- |
| `id` | 新题省略或传 `null`，后端生成；编辑时保留已有 ID |
| `type` | `single`、`multiple`、`text`、`number` |
| `title` | 去首尾空白后 1～200 字符 |
| `required` | Boolean，默认 `false` |
| `options` | 选择题 2～30 项，每项为 `{id, label}`；新选项省略 ID，文字为 1～100 字符；填空题不带选项或使用空数组 |
| `validation` | 按题型设置，见下表 |
| `jump_rules` | 有序数组；已有题目省略时保留，传 `[]` 清空，新题默认 `[]` |

| 题型 | `validation` 示例 |
| --- | --- |
| 单选 | `{}` |
| 多选 | `{"min_choices":1,"max_choices":2}`；上下限相同表示恰好选 N 项 |
| 文本 | `{"min_length":1,"max_length":100}` |
| 数字 | `{"min_value":0,"max_value":120,"integer_only":true}` |
| 手机号格式（数字题） | `{"integer_only":true,"phone_format":true}` |

上下界可省略或传 `null`；最小值不得超过最大值，数量和长度须为非负整数，参数须匹配题型。选择数量不能超过选项数；必答文本/多选的最大长度/数量不能为 0；整数范围须包含整数。手机号格式校验必须同时要求整数。

已有题目和选项编辑时应带回原 ID，删除则从数组移除。示例中的新项没有 ID，重复发送会生成新 ID。重排或删除后，跳转引用仍须合法；非草稿或并发变更返回 `409`，配置不合法返回 `422`。

### 3.3 配置跳转规则

`PUT /api/surveys/{survey_id}/questions/{question_id}/jump-rules` → `200`：问卷详情。

先保存题目并取得真实题目、选项 ID，再替换下例占位值：

```json
{
  "jump_rules": [
    {
      "condition": {"operator": "equals", "value": "<option_id>"},
      "target": {"kind": "question", "question_id": "<later_question_id>"}
    }
  ]
}
```

| 来源题型 | `operator` | `value` |
| --- | --- | --- |
| 单选 | `equals` | 本题一个选项 ID |
| 多选 | `contains` | 本题一个选项 ID |
| 多选 | `contains_all` | 非空、无重复的选项 ID 数组，允许回答包含额外选项 |
| 数字 | `gt` / `gte` / `lt` / `lte` / `eq` | 有限数值，不接受布尔值或数字字符串 |

每次替换该题全部规则，`{"jump_rules":[]}` 清空。按数组顺序执行第一条命中规则，否则顺序前进。目标须为后方题目，或 `{"kind":"end"}` 结束作答；结束目标不能带 `question_id`。文本题不支持规则，非法引用返回 `422`。

### 3.4 发布、截止、关闭与删除

| 方法 | 路径 | 请求体 | 成功响应 |
| --- | --- | --- | --- |
| POST | `/api/surveys/{survey_id}/publish` | `{}` 或 `{"deadline":null}`，也可设置未来时间 | `200`：已发布详情及 `fill_url` |
| PATCH | `/api/surveys/{survey_id}/deadline` | 必须明确提供 `deadline`，未来时间或 `null` | `200`：更新后的详情 |
| POST | `/api/surveys/{survey_id}/close` | 无 | `200`：`status=closed` 的详情 |
| DELETE | `/api/surveys/{survey_id}` | 无 | `200`：`{"message":"问卷草稿已删除"}` |

- 发布前至少有一道合法题目；发布后标题、说明、题目、规则及两个开关锁定。
- 截止时间必须带时区且在未来，例如 `{"deadline":"2030-12-31T23:59:00+08:00"}`，使用时替换为实际未来时间。
- 仅已发布且尚未到期时可调整或取消截止；到期后不能恢复接收。
- 关闭保留已有数据与统计，不支持重新开放；仅草稿可永久删除。
- 状态不允许或并发变更返回 `409`，时间或配置不合法返回 `422`。

## 4. 填写与提交

本节均需填写者登录，允许匿名也不例外。

| 方法 | 路径 | 请求 | 成功响应 |
| --- | --- | --- | --- |
| GET | `/api/fill/surveys/{survey_id}` | 无 | `200`：`id`、标题、说明、两个开关、截止、题目；不含创建者身份 |
| POST | `/api/fill/surveys/{survey_id}/validate` | `answers`、可选 `is_anonymous` | `200`：`valid`、`question_path`、规范化 `answers`、`is_anonymous`；不保存 |
| POST | `/api/fill/surveys/{survey_id}/responses` | 与预校验相同 | `201`：`id`、`survey_id`、`is_anonymous`、`submitted_at` |

请求示例（占位 ID 替换为实际值，仅提交当前路径上的答案）：

```json
{
  "is_anonymous": true,
  "answers": [
    {"question_id": "<single_question_id>", "value": "<option_id>"},
    {"question_id": "<number_question_id>", "value": "20"}
  ]
}
```

| 答案类型 | `value` 格式 |
| --- | --- |
| 单选 | 一个有效选项 ID 字符串 |
| 多选 | 无重复的有效选项 ID 数组 |
| 文本 | 字符串，去首尾空白后校验 |
| 数字 | JSON 数值或普通十进制字符串；数字字符串不接受科学计数法 |
| 路径上的非必答空答 | `null`，也可省略该题，由后端规范化 |

调用注意事项：

- 预校验检查完整候选答卷，不是逐题保存；确认提交才写入数据库。
- 只校验经过的题目；未知题目、重复题目、路径外答案、必答缺失返回 `422`。返回修改后需清除新路径外的旧答案。
- 数字上下界包含边界，`0` 是有效答案；整数题可接受 `"20.0"`，不接受 `"20.1"`，存储整数须在 64 位整数范围内，拒绝非有限数值。
- 手机号传原始 11 位 ASCII 数字字符串或整数，首位为 1、第二位为 3～9；不接受小数点、国家码、空格或连字符。
- `is_anonymous` 省略或为 `null` 时按问卷设置默认；允许匿名默认 `true`，否则 `false`。禁止匿名时明确传 `true` 返回 `422`。
- 用户身份、提交时间和内部约束字段由后端生成，不由客户端指定。

填写接口的业务错误：

| 状态码 | 情况 |
| --- | --- |
| `404` | 问卷不存在、ID 非法或仍为草稿 |
| `409` | 问卷关闭、已到截止，或禁止重复时本人已提交 |
| `422` | 答案、匿名设置或答题路径不合法 |

## 5. 创建者统计

| 方法 | 路径 | 成功响应 |
| --- | --- | --- |
| GET | `/api/surveys/{survey_id}/statistics` | `200`：问卷概览、`questions` 统计数组及最新答卷样本 |
| GET | `/api/surveys/{survey_id}/questions/{question_id}/statistics` | `200`：问卷概览、`question` 统计对象及该题样本 |

仅创建者可访问；问卷或题目不存在、无权限返回 `404`。到期或关闭后仍可查询。

| 响应字段 | 含义 |
| --- | --- |
| `total_submissions` | 全部成功提交份数，包含重复提交 |
| `participant_count` | 按账号去重的参与人数 |
| `statistics_basis` | 固定为 `latest_response_per_user` |
| `questions` / `question` | 整卷题目数组 / 单题对象 |
| `latest_responses` | 每账号最新整份答卷的样本，包含 `is_anonymous`、`username`、`answers` |

| 题目统计字段 | 含义 |
| --- | --- |
| `question_id`、`type`、`title` | 题目标识、类型和题干 |
| `answered_count` | 有效回答人数，不含跳过和空答 |
| `options` | 选择题各项的 `id`、`label`、`count`，未选中项为 0 |
| `values` | 填空题的非空内容 |
| `average`、`average_display` | 数字平均值；无样本时分别为 `null`、`暂无数据` |

题目统计统一使用每个账号最新的一整份答卷，不从历史答卷补回答案。数字 `0` 计入统计。匿名样本的 `username=null`，不返回内部账号 ID、答卷 ID 或身份关联；单题样本只含该题答案，跳过时 `answers=[]`。当前样本与填空内容不分页。

## 6. 典型调用顺序

1. 注册并登录，取得令牌。
2. 创建草稿 → 保存题目 → 用返回的 ID 配置跳转 → 发布，取得填写链接。
3. 填写者登录 → 获取填写问卷 → 预校验 → 确认提交。
4. 创建者调用整卷或单题统计接口。

数据库结构与内部执行逻辑见 `design.md`。
