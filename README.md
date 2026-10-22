# 基于 MongoDB 的在线问卷系统

一个支持问卷创建、发布、填写和结果统计的在线问卷系统。后端使用 FastAPI 与 MongoDB，前端使用 Vue 3，支持多种题型、答案校验和条件跳转。

## 一、功能概览

- **账号管理**：注册、登录和登录状态恢复；用户管理自己的问卷与统计结果。
- **问卷管理**：创建与编辑草稿、配置匿名及重复填写、发布、设置截止时间、关闭问卷，以及删除草稿（当前仅支持删除草稿）。
- **题目配置**：单选、多选、文本填空和数字填空，支持必答及各类输入限制。
- **条件跳转**：根据选择结果或数字条件跳到后续题目或结束填写，支持规则优先级。
- **填写提交**：通过链接进入，逐题回答、返回修改、提交前检查与预览，提交后生成回执。
- **结果统计**：查看整卷或单题统计，包括答卷份数、参与人数、选项计数、文本内容、数字平均值和去重样本。

## 二、环境与依赖

| 部分 | 技术与要求 |
| --- | --- |
| 后端 | Python、FastAPI、PyMongo，具体依赖见 `backend/requirements.txt` |
| 数据库 | 本地 MongoDB 服务 |
| 前端 | Vue 3、Vite、JavaScript，具体依赖见 `frontend/package.json` |
| 前端运行环境 | Node.js ≥ 22.12.0、npm |

## 三、数据与目录

业务数据保存在 MongoDB 中，默认使用本机的 `survey_pro1` 数据库。数据库文件由 MongoDB 管理，不放在项目代码目录中。本地示例数据目录为 `D:\Database_D\MongoDB_data\data`，可按实际环境调整。

```text
pro1/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 入口、路由挂载与健康检查
│   │   ├── database.py      # MongoDB 连接、索引与数据库依赖
│   │   ├── auth/            # 注册、登录、密码与令牌
│   │   ├── surveys/         # 问卷、题目、跳转与生命周期
│   │   ├── responses/       # 答案校验、填写路径与提交
│   │   └── stats/           # 整卷与单题统计
│   ├── tests/              # 自动测试程序
│   ├── requirements.txt    # 配置依赖
│   └── .env.example        # 后端配置示例
├── frontend/
│   ├── src/
│   │   ├── pages/          # 填写与统计页面
│   │   ├── components/     # 问卷编辑组件
│   │   ├── utils/          # 路径、答案处理逻辑及测试
│   │   └── App.vue         # 登录与工作台
│   ├── package.json
│   └── vite.config.js
├── docs/
│   ├── assignment/         # 原始需求资料
│   ├── design.md           # 系统、数据库与关键逻辑设计
│   ├── api.md              # 接口与认证说明
│   ├── testing.md          # 自动测试说明
│   └── ai-log.md           # AI 使用日志
├── AGENTS.md               # 开发协作规则
├── README.md
└── .gitignore
```

本地运行时会生成 `backend/.venv/`、`backend/.env` 和前端依赖目录等文件。

## 四、首次配置

首次运行无需手动创建数据库、集合或导入初始数据。后端启动时会检查数据库连接，并自动创建 users、surveys、responses 集合及必要索引；连接或索引创建失败时，后端将启动失败。系统不预置账号和问卷，启动后通过页面或 API 注册账号、创建问卷即可使用。

### 1. 准备 MongoDB

确认 MongoDB 已安装，且数据目录存在，另开终端启动数据库，并保持运行。以下为本机数据库路径示例，可自行选择真实 MongoDB 数据路径：

```powershell
mongod --dbpath="D:\Database_D\MongoDB_data\data"
```

### 2. 安装后端依赖

在项目根目录打开 PowerShell：

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

将生成的随机值填入 `backend/.env` 的 `JWT_SECRET`，并根据 `.env.example` 核对 MongoDB 连接配置。

- `.env` 仅首次创建；已有配置时不要再次复制覆盖。
- `JWT_SECRET` 使用本机生成的随机值，保持私密，不提交到代码仓库。
- 已有虚拟环境时，无需再次执行 `python -m venv .venv`。

### 3. 安装前端依赖

另开终端，在项目根目录执行：

```powershell
cd frontend
npm.cmd install
```

## 五、启动与访问

按 **MongoDB → 后端 → 前端** 的顺序启动，三个进程分别保持运行。

### 启动后端

在项目根目录打开终端：

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### 启动前端

在项目根目录另开终端：

```powershell
cd frontend
npm.cmd run dev
```

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:5173/` | 网页入口 |
| `http://127.0.0.1:8000/docs` | FastAPI 自动生成的接口文档与调试页面 |
| `/survey/{id}` | 前端问卷填写路径 |

日常启动无需重复安装依赖或生成密钥。停止前后端时，在对应终端按 `Ctrl+C`。


## 六、文档与测试

- [系统与数据库设计](docs/design.md)
- [API 说明](docs/api.md)
- [后端测试说明](docs/testing.md)

### 后端自动测试（推荐）

在 `backend/` 目录执行：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

这里会默认使用内存替身，跳过真实 MongoDB 测试。

因此推荐以下步骤运行真实数据库测试，先启动 MongoDB，再执行：

```powershell
$env:RUN_MONGO_TESTS = "1"
.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
Remove-Item Env:RUN_MONGO_TESTS
```

真实数据库下自动测试程序的说明和结果详见 [测试说明](docs/testing.md)。

### API 测试

后端启动后，访问 FastAPI 的接口文档与调试页面 http://127.0.0.1:8000/docs ，手动输入数据测试 API 逻辑。参数、认证方式和响应约定见 [API 说明](docs/api.md)。

在此对每个接口逐一进行了手工测试，返回的结果均与预期一致，证明了该 API 设计逻辑正确，功能齐全。

### 前端测试

数据库、后端和前端依次启动后，登陆前端访问系统，查看各功能交互是否正确。

通过登陆前端系统体验各功能，未发现使用问题，前端测试通过。

## 七、功能配置与使用

### 账号与登录

注册并登录后，可管理自己的问卷和查看统计。填写问卷也需先登录，匿名填写同样需要登录。

API 调试可访问 `/docs`，登录取得 `access_token` 后通过 **Authorize** 完成认证。接口说明见 `docs/api.md`。

### 题目与校验

| 题型 | 可配置内容 |
| --- | --- |
| 单选题 | 选项、是否必答 |
| 多选题 | 选项、是否必答、最少与最多选择数量 |
| 文本填空 | 是否必答、最少与最多字数 |
| 数字填空 | 是否必答、最小值、最大值、是否仅限整数 |

草稿修改需主动保存；新题目和新选项保存后，才能用于跳转配置。

### 跳转与问卷管理

- 支持按单选、多选和数字条件跳到后续题目或结束填写，按规则优先级匹配，未命中时顺序前进。
- 问卷至少包含一道题，且修改已保存后才能发布；发布后题目与跳转规则锁定。
- 截止时间可选，并可在截止前调整或取消。
- 问卷可主动关闭，关闭后不能重新开放或提交，但仍可查看统计。
- 仅草稿支持删除。

### 填写与提交

发布后可分享填写链接。填写者登录后逐题作答，也可返回修改；路径变化时，被跳过题目的旧答案会自动清除。

“检查并预览”仅执行后端校验，点击“确认提交”后才保存答卷。填写内容不自动保存。

问卷可配置是否允许匿名和重复填写；允许重复填写时，每次提交独立保存。

### 统计口径

创建者可查看整卷和单题统计：

- **总份数**：所有已保存答卷的数量，包含重复提交。
- **参与人数**：按账号去重的人数。
- **题目统计**：使用每个账号最新的一整份答卷。
- **样本展示**：展示脱敏样本，匿名样本不显示用户名。


