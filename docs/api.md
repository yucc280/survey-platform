# API 接口文档

## 1. 调用约定

- 本地服务：`http://127.0.0.1:8000`；交互式接口及模型：`/docs`。
- 请求与响应使用 JSON，请求体设置 `Content-Type: application/json`。
- ID 使用字符串；时间使用带时区的 ISO 8601 格式。
- 除注册、登录、健康检查外，均需登录，匿名填写也不例外。
- 请求头：`Authorization: Bearer <access_token>`。
- 题型仅支持 `single`（单选）、`multiple`（多选）、`text`（文本）、`number`（数字）。

### 状态码

| 状态码 | 含义 |
| --- | --- |
| 200 | 查询、更新或删除成功 |
| 201 | 创建资源或提交答卷成功 |
| 401 | 未登录、凭证错误或令牌无效 / 过期 |
| 404 | 资源不存在、ID 非法或无访问权限 |
| 409 | 状态不允许、重复、过期 revision 或并发冲突 |
| 422 | 参数、题目配置、答案或答题路径不合法 |

分页通常使用 `offset=0`、`limit=20`，`limit` 范围为 1～100。各接口的具体支持情况见对应说明。

### 权限与数据边界

| 资源 / 操作 | 权限 |
| --- | --- |
| 问卷管理、本卷统计 | 仅问卷创建者 |
| 填写、提交 | 登录用户，可填写他人开放问卷 |
| 题目编辑、恢复、转回临时题 | 仅题目创建者 |
| 本人题目 | 创建者可管理和复用 |
| 他人题目新引用 | 题目须为其创建者题库中的可用成员，通过题库 ID 查找选用 |
| 他人题库 | 登录后凭 ID 只读查看、选题；不能修改，也不能将他人题加入自己的题库 |
| 题目撤出题库 / 题库删除后 | 已有问卷及快照保留；已有引用者仍可读取所用版本及分析，无引用的新版本和新引用不再开放；题目仍在另一题库时可继续选用 |

系统无题目公开 / 私有状态、公开搜索或题库共享开关。题目版本不可覆盖，当前版本只是默认选用版本；恢复不改变既有问卷。

## 2. 账号与健康检查

| 方法 | 路径 | 请求 | 成功响应 |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | `username`、`password` | 201：`id`、`username`、`created_at` |
| POST | `/api/auth/login` | `username`、`password` | 200：`access_token`、`token_type`、`expires_in` |
| GET | `/api/auth/me` | 无 | 200：当前用户 `id`、`username`、`created_at` |
| GET | `/api/health` | 无 | 200：`{"status":"ok"}`，检查数据库连接 |

```json
{"username":"demo_user","password":"example_password"}
```

用户名去首尾空白、区分大小写，长度 3～30，仅限英文字母、数字、下划线；密码长度 6～30，不自动去空白。注册不自动登录，同名返回 409。令牌有效期两小时，登录返回 `token_type="bearer"`、`expires_in=7200`；无刷新或服务端撤销接口。

## 3. 问卷管理

本模块仅问卷创建者可访问。路径中的 `{survey_id}` 为问卷 ID，`{question_id}` 为该问卷内部题目 ID。

### 3.1 创建、列表与详情

| 方法 | 路径 | 输入 | 成功响应 |
| --- | --- | --- | --- |
| POST | `/api/surveys` | 创建参数，见下表 | 201：问卷详情 |
| GET | `/api/surveys` | 查询：`offset`、`limit` | 200：`items`、`total`、`offset`、`limit` |
| GET | `/api/surveys/{survey_id}` | 无 | 200：问卷详情 |

| 创建字段 | 要求 |
| --- | --- |
| `title` | 必填，去首尾空白后 1～100 字符 |
| `description` | 默认 `""`，最多 1000 字符 |
| `allow_anonymous` | Boolean，默认 `false` |
| `allow_repeat` | Boolean，默认 `false` |

新问卷为 `draft`，`questions=[]`、`deadline=null`。详情包含 `id`、`owner_id`、标题、说明、状态、两个开关、截止、题目、`created_at`、`updated_at`。列表只返回本人问卷，按创建时间和 ID 降序，列表项不含 `questions`。

### 3.2 完整保存草稿

`PUT /api/surveys/{survey_id}` → 200：保存后的完整问卷。

| 请求字段 | 要求 |
| --- | --- |
| `title` | 必填 |
| `questions` | 必填，最多 100 题；`[]` 清空题目 |
| `description` | 省略重置为 `""` |
| `allow_anonymous`、`allow_repeat` | 省略重置为 `false` |

这是完整替换接口，应发送需要保留的编辑字段，不直接回传含只读字段的整份详情。

```json
{
  "title":"学习情况调查",
  "description":"",
  "allow_anonymous":true,
  "allow_repeat":false,
  "questions":[
    {
      "type":"single",
      "title":"是否学过 MongoDB？",
      "required":true,
      "options":[{"label":"是"},{"label":"否"}],
      "validation":{}
    },
    {
      "type":"number",
      "title":"每周学习小时数",
      "required":true,
      "validation":{"min_value":0,"max_value":168,"integer_only":true}
    }
  ]
}
```

| 题目字段 | 说明 |
| --- | --- |
| `id` | 新题省略 / `null`，后端生成；编辑时保留原 ID |
| `type` | 四类题型之一 |
| `title` | 去首尾空白后 1～200 字符 |
| `required` | 默认 `false`，属于问卷配置 |
| `options` | 选择题 2～30 项，格式 `{id,label}`；新选项省略 ID，文字 1～100 字符；文本 / 数字题省略或传空数组 |
| `validation` | 按题型设置，见下表 |
| `jump_rules` | 有序数组；已有题省略时保留，`[]` 清空，新题默认 `[]` |
| `source`、选项 `source_option_id` | 可复用题目的来源及选项映射，保留后端读回值，不自行构造或移除 |

| 题型 | `validation` 示例 |
| --- | --- |
| 单选 | `{}` |
| 多选 | `{"min_choices":1,"max_choices":2}`，上下限相同表示恰好选 N 项 |
| 文本 | `{"min_length":1,"max_length":100}` |
| 数字 | `{"min_value":0,"max_value":120,"integer_only":true}` |
| 手机号（数字题） | `{"integer_only":true,"phone_format":true}` |

上下界可省略或为 `null`；最小值不能大于最大值，数量 / 长度须为非负整数，参数须匹配题型。选择数量不能超过选项数；必答文本 / 多选的最大长度 / 数量不能为 0；整数范围须包含整数；手机号必须同时要求整数。

编辑保留原题目和选项 ID，删除时从数组移除；无 ID 的项会重新生成身份。重排、删除后跳转仍须合法。

可复用题目只能原样保留版本题干、选项、校验及来源，可以调整问卷内必答、跳转、顺序或删除该位置；不能通过此接口新增来源、修改固定内容或解除来源。新增引用、换版本、转回临时题使用专用接口。旧临时题请求仍有效。非草稿 / 并发冲突返回 409，配置错误返回 422。

### 3.3 跳转配置

`PUT /api/surveys/{survey_id}/questions/{question_id}/jump-rules` → 200：问卷详情。

先保存题目取得实际 ID，再配置：

```json
{
  "jump_rules":[
    {
      "condition":{"operator":"equals","value":"<option_id>"},
      "target":{"kind":"question","question_id":"<later_question_id>"}
    }
  ]
}
```

| 来源题型 | `operator` | `value` |
| --- | --- | --- |
| 单选 | `equals` | 本题一个选项 ID |
| 多选 | `contains` | 本题一个选项 ID |
| 多选 | `contains_all` | 非空、无重复的选项 ID 数组；回答可包含额外选项 |
| 数字 | `gt` / `gte` / `lt` / `lte` / `eq` | 有限数值，不接受布尔值或数字字符串 |

每次替换全部规则，`{"jump_rules":[]}` 清空。按顺序执行首条命中规则，否则顺序前进。目标只能是后方题目或 `{"kind":"end"}`；结束目标不能带 `question_id`。文本题不支持规则，非法引用返回 422。

### 3.4 发布与状态操作

| 方法 | 路径 | 请求体 | 成功响应 |
| --- | --- | --- | --- |
| POST | `/api/surveys/{survey_id}/publish` | `{}`、`{"deadline":null}` 或未来截止时间 | 200：已发布详情及 `fill_url` |
| PATCH | `/api/surveys/{survey_id}/deadline` | 必须提供 `deadline`，未来时间或 `null` | 200：问卷详情 |
| POST | `/api/surveys/{survey_id}/close` | 无 | 200：`status=closed` 的详情 |
| DELETE | `/api/surveys/{survey_id}` | 无 | 200：`{"message":"问卷草稿已删除"}` |

发布前至少有一道合法题；发布后标题、说明、题目、规则及两个开关锁定。截止时间须带时区且在未来，例如 `{"deadline":"2030-12-31T23:59:00+08:00"}`。仅已发布、尚未到期时可调整 / 取消截止；到期或关闭后不能恢复接收。关闭保留数据与统计，仅草稿可永久删除。状态冲突返回 409，时间 / 配置错误返回 422。

### 3.5 可复用题目接入

以下 `{question_id}` 仍指问卷内部题目，正文中的 `question_id` 指独立逻辑题目。

| 方法 | 路径 | 请求体 | 成功响应 |
| --- | --- | --- | --- |
| POST | `/api/surveys/{survey_id}/library-questions` | `question_id`、`version_id` | 完整已保存问卷 |
| PUT | `/api/surveys/{survey_id}/questions/{question_id}/source` | `question_id`、`version_id` | 完整已保存问卷 |
| POST | `/api/surveys/{survey_id}/questions/{question_id}/save-to-library` | 无 | 201：独立题目及 v1 |

选入 / 替换请求：

```json
{"question_id":"<logical_question_id>","version_id":"<version_id>"}
```

- 选入：仅草稿，在末尾增加版本快照，必答默认 `false`，检查新增引用权限。
- 替换：仅草稿，保留原内部题目 ID、必答和跳转；替换导致规则失效则拒绝整个更新。
- 保存为可复用题目：本人问卷各状态均可，将临时题转换并关联新 v1，补充 `source` 和 `source_option_id`；内部 ID、内容、必答、跳转及答卷不变，历史答案可参与全局统计。已有来源返回 409。操作后重新读取问卷。

发布、填写、本卷统计仍使用问卷内部题目 ID，不使用逻辑题目 ID 替代。

## 4. 填写与提交

| 方法 | 路径 | 请求 | 成功响应 |
| --- | --- | --- | --- |
| GET | `/api/fill/surveys/{survey_id}` | 无 | 200：问卷 ID、标题、说明、两个开关、截止、题目，不含创建者身份 |
| POST | `/api/fill/surveys/{survey_id}/validate` | `answers`、可选 `is_anonymous` | 200：`valid`、`question_path`、规范化 `answers`、`is_anonymous`，不保存 |
| POST | `/api/fill/surveys/{survey_id}/responses` | 同预校验 | 201：`id`、`survey_id`、`is_anonymous`、`submitted_at` |

```json
{
  "is_anonymous":true,
  "answers":[
    {"question_id":"<internal_question_id>","value":"<option_id>"},
    {"question_id":"<number_question_id>","value":"20"}
  ]
}
```

| 答案类型 | `value` |
| --- | --- |
| 单选 | 一个有效选项 ID 字符串 |
| 多选 | 无重复的有效选项 ID 数组 |
| 文本 | 字符串，去首尾空白后校验 |
| 数字 | JSON 数值或普通十进制字符串；字符串不接受科学计数法 |
| 路径上的非必答空答 | `null` 或省略该题，由后端规范化 |

预校验检查完整候选答卷，确认提交才保存。只提交当前路径答案；未知 / 重复题目、路径外答案、必答缺失返回 422，返回修改后需清除新路径外旧答案。

数字范围含边界，`0` 有效；整数题接受 `"20.0"`，拒绝 `"20.1"`，存储整数限 64 位，拒绝非有限值。手机号须为原始 11 位 ASCII 数字字符串或整数，首位 1、第二位 3～9，不接受小数点、国家码、空格或连字符。

`is_anonymous` 省略或为 `null` 时按问卷设置默认：允许匿名则 `true`，否则 `false`；禁止匿名却传 `true` 返回 422。身份、时间及内部约束字段由后端生成。草稿 / 不存在返回 404；关闭、到期或禁止重复且本人已提交返回 409。

## 5. 独立题目与版本

本模块 `{question_id}` 指逻辑题目 ID，`{version_id}` 指属于该题的固定版本 ID。

| 方法 | 路径 | 输入 | 成功结果 |
| --- | --- | --- | --- |
| POST | `/api/questions` | `content` | 201：创建题目及当前 v1 |
| GET | `/api/questions` | 查询：`scope=mine`、`keyword`、`offset`、`limit` | 本人题目分页列表 |
| GET | `/api/questions/{question_id}` | 无 | 题目摘要及当前版本；非所有者受可访问版本范围限制 |
| GET | `/api/questions/{question_id}/versions` | 查询：`offset`、`limit` | 可访问版本历史分页 |
| GET | `/api/questions/{question_id}/versions/{version_id}` | 无 | 固定版本内容 |
| POST | `/api/questions/{question_id}/versions` | `expected_revision`、`content` | 201：新当前版本及 `revision` |
| PATCH | `/api/questions/{question_id}/current-version` | `expected_revision`、`version_id` | 200：切换当前版本，不增加版本数 |
| POST | `/api/questions/{question_id}/temporary` | `expected_revision` | 200：`message` |

`scope` 仅接受 `mine`；`keyword` 按任一版本题干进行不区分大小写的字面搜索。响应返回摘要与当前版本，历史内容通过历史接口单独读取；不返回 `is_public`，`scope=public` 返回 422。

创建示例：

```json
{
  "content":{
    "type":"number",
    "title":"你的年龄",
    "options":[],
    "validation":{"integer_only":true,"min_value":0,"max_value":120}
  }
}
```

`content` 使用第 3.2 节题型、题干、选项及校验规则，不包含 `required`、`jump_rules` 或来源字段。保存新版本时，已有选项 ID 只能来自当前版本，新选项省略 ID。

新版本 / 恢复 / 转回临时题须提交最新读回的 `revision` 作为 `expected_revision`，过期返回 409。恢复仅切换指针，后续新版本编号按历史最高编号递增，不覆盖旧版。

转回临时题仅创建者可操作：零引用可移出；所有版本合计仅一份自有问卷引用时，解除该卷各位置的来源和选项映射，保留内容与答卷。多份引用或唯一他人引用返回 409。题目以 `retired` 内部保留，不再出现在列表、详情、版本、选题及分析入口，原题库关系可手动移出。该操作与“移出题库成员”不同。

### 5.1 使用情况查询

`GET /api/questions/{question_id}/usage`

| 查询参数 | 说明 |
| --- | --- |
| `version_id` | 可选；省略查询全部版本，指定时仅查询该版本 |
| `offset`、`limit` | 分页 |

先校验题目访问权，再过滤他人草稿。只展示问卷名称、创建者、状态、所用版本等必要信息，不开放完整问卷和回答。仅本人可看到自己草稿引用；已发布 / 关闭记录按访问权限展示。使用查询与回答统计为独立接口。

## 6. 题库组织与 ID 分享

| 方法 | 路径 | 输入 | 成功结果 |
| --- | --- | --- | --- |
| POST | `/api/question-banks` | 正文：`name` | 创建本人题库 |
| GET | `/api/question-banks` | 查询：`offset`、`limit` | 本人题库分页列表 |
| GET | `/api/question-banks/{bank_id}` | 查询：`offset`、`limit` | 登录后凭 ID 读取详情及成员分页 |
| PATCH | `/api/question-banks/{bank_id}` | 正文：`name`、`expected_revision` | 更新名称 |
| PUT | `/api/question-banks/{bank_id}/questions/{question_id}` | 正文：`expected_revision` | 加入本人的逻辑题目，重复加入不重复存成员 |
| DELETE | `/api/question-banks/{bank_id}/questions/{question_id}` | 查询：`expected_revision` | 移出成员，不删除题目、版本或问卷 |
| DELETE | `/api/question-banks/{bank_id}` | 查询：`expected_revision` | 200：`message`，删除题库，保留题目及已有问卷 |

修改、成员操作及删除仅题库所有者可用，必须提交最新 `revision`，过期返回 409；越权返回 404。成员只保存逻辑题目 ID，不复制题目。旧不可访问成员也可移出清理。

详情中 `items` 只返回题库创建者自己的可用题，`total` 为可见数量，`question_count` 为组织关系数量，`unavailable_count` 为不可访问数量。删除后该题库 ID 返回 404。撤出成员或删除题库会限制后续新选用，既有引用处理见第 1 节。

## 7. 统计分析

### 7.1 当前问卷统计

| 方法 | 路径 | 成功响应 |
| --- | --- | --- |
| GET | `/api/surveys/{survey_id}/statistics` | 200：问卷概览、`questions`、最新答卷样本 |
| GET | `/api/surveys/{survey_id}/questions/{question_id}/statistics` | 200：问卷概览、`question`、该题样本 |

仅问卷创建者可访问，到期或关闭后仍可查询。临时题与可复用题均参与本卷统计。

| 响应字段 | 含义 |
| --- | --- |
| `total_submissions` | 全部成功提交份数，含重复提交 |
| `participant_count` | 按账号去重人数 |
| `statistics_basis` | `latest_response_per_user` |
| `questions` / `question` | 整卷题目统计数组 / 单题对象 |
| `latest_responses` | 每账号最新整份答卷样本，包含 `is_anonymous`、`username`、`answers` |
| 题目 `question_id`、`type`、`title` | 问卷内部 ID、题型、题干 |
| 题目 `answered_count` | 有效回答人数，排除空答和跳过 |
| 题目 `options` | 选项 `id`、`label`、`count`，未选项为 0 |
| 题目 `values` | 填空题非空内容 |
| 题目 `average`、`average_display` | 数字均值，无样本为 `null`、`暂无数据` |

取每账号最新整份答卷，不从历史补答案；数字 0 计入。匿名样本 `username=null`，不返回内部账号 ID、答卷 ID 或身份关联。单题样本只含该题答案，跳过时 `answers=[]`。当前样本与填空内容不分页。

### 7.2 固定版本跨问卷统计

`GET /api/questions/{question_id}/versions/{version_id}/statistics` → 200：该固定版本的全局统计。

查询参数 `offset=0`、`limit=20`（1～100）控制数字频次或文本内容分页，不改变全量均值、计数和占比。权限与固定版本读取一致，仅可复用题目支持。

| 响应字段 | 含义 |
| --- | --- |
| `question_id`、`version_id`、`version_number`、`type`、`title` | 指定固定版本，不受当前默认版本变化影响 |
| `referenced_survey_count` | 引用该版的已发布问卷数量，含截止 / 关闭，不含草稿；同卷多次引用只计一卷 |
| `answered_survey_count` | 上述问卷中至少有一次有效回答的问卷数量 |
| `answered_count` | 每卷每账号最新整份答卷中，该版本各出现位置的有效回答次数 |
| `options` | 固定版本选项的 ID、文字、`count`、`percentage`（0～100）；多选百分比总和可超过 100 |
| `average`、`average_display` | 数字均值，无样本为 `null`、`暂无数据` |
| `distribution` | 数字同值分组的 `value`、`count`、`percentage`，按数值升序分页 |
| `distribution_total`、`distribution_offset`、`distribution_limit` | 不同数值总数及频次分页信息 |
| `text_answers` | 非空文本字符串数组，分页展示，相同内容不合并；非文本题为空 |
| `text_offset`、`text_limit` | 文本页位置及大小，文本总数使用 `answered_count` |
| `statistics_basis`、`counting_unit` | 最新整份答卷口径及有效回答出现次数单位 |

相同版本跨卷合并，不同版本分别统计；同账号跨卷、同版本同卷不同位置分别计数。空答和跳过不计，数字 0 计入，最新答卷跳过不从历史补回。选项先通过来源映射回固定版本 ID，不按文字或位置猜测。

文本按问卷 ID、账号 ID 及答卷中位置固定顺序遍历，数据变化后刷新可能改变页内容。响应不附带用户名、填写账号、来源问卷、答卷 ID、内部题目 ID 或其他题答案；文本内容本身会展示。

例如 A 卷同账号先填 20 后填 30，B 卷该账号填 40，C 卷仅引用无回答：同版统计为引用问卷 3、有回答问卷 2、有效回答 2、均值 35。A 关闭或 B 截止后仍纳入。

无权访问 / 版本不属于该题返回 404，分页错误返回 422，选项来源不一致返回 409。
