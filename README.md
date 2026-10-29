# 基于 MongoDB 的在线问卷系统

本项目使用 Python、FastAPI、PyMongo、MongoDB 和 Vue 3 实现一个问卷系统。第二阶段在原有问卷创建、填写和统计的基础上，扩展独立题目、版本管理、题库分享和跨问卷统计，保留原有问卷与答卷的关联。

## 1. 主要功能

| 功能 | 说明 |
| --- | --- |
| 账号管理 | 注册、登录和身份认证；管理本人问卷、题目与题库 |
| 问卷管理 | 创建与编辑草稿、发布、设置截止、主动关闭和删除草稿 |
| 题目与填写 | 单选、多选、文本、数字四类题型，支持必答、输入校验、条件跳转、预览确认、匿名与重复填写设置 |
| 独立题目 | 保存常用题目、生成固定版本、查看历史、恢复旧版本，在不同问卷中选择不同版本 |
| 题库分享 | 组织本人题目，其他登录用户凭题库 ID 只读浏览并选用 |
| 使用查询 | 查看题目或指定版本被哪些问卷使用，隐藏他人草稿 |
| 统计分析 | 整卷及单题统计、固定版本跨问卷汇总、选项占比、数字均值与频次、文本回答分页 |

填写问卷也需要登录，匿名表示向问卷创建者隐藏账号身份。问卷发布后内容锁定，源题更新或恢复版本不改变已有问卷；题库移出成员或删除后，已有引用与答案保留。

本卷题目统计按每账号最新一整份答卷计算；全局统计按相同固定版本跨问卷汇总，每卷分别取最新整份答卷，空答或跳过不从历史补回，数字 0 正常计入。

## 2. 项目结构

```text
pro1/
├── backend/
│   ├── app/
│   │   ├── main.py             # 应用入口与路由
│   │   ├── database.py         # 数据库连接与索引
│   │   ├── auth/               # 账号与认证
│   │   ├── surveys/            # 问卷配置、版本接入与跳转
│   │   ├── responses/          # 填写校验与提交
│   │   ├── questions/          # 独立题目、版本、题库与使用查询
│   │   └── stats/              # 本卷及跨问卷统计
│   ├── tests/                  # 后端自动测试
│   ├── seed_stage2_demo.py     # 可选演示数据脚本
│   ├── requirements.txt        # Python 依赖
│   └── .env.example            # 后端配置示例
├── frontend/
│   ├── src/
│   │   ├── pages/              # 题目、题库、填写与统计页面
│   │   ├── components/         # 编辑、选题与分析组件
│   │   ├── utils/              # 答案及路径处理、逻辑测试
│   │   └── App.vue             # 登录与工作台
│   ├── package.json
│   └── package-lock.json
├── docs/                       # 接口、设计、测试和 AI 使用文档
└── README.md
```

业务数据保存在 MongoDB 中，包含 `users`、`surveys`、`responses`、`questions` 和 `question_banks` 五个集合。数据库文件由 MongoDB 管理，不随代码仓库分发。

## 3. 环境与首次配置

需要准备 Python（项目使用 3.12.7）、Node.js ≥ 22.12.0、npm 和 MongoDB。以下命令使用 Windows PowerShell，各终端从项目根目录开始。

### 3.1 启动 MongoDB

如果 MongoDB 已作为系统服务运行，无需重复启动。否则指定自己已有的数据目录启动，例如：

```powershell
mongod --dbpath="D:\MongoDB\data"
```

示例目录需提前创建，可替换为自己的实际路径，本机数据库目录是"D:\Database_D\MongoDB_data\data"。保持数据库运行，默认连接地址为 `mongodb://127.0.0.1:27017`。

### 3.2 配置后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

将最后一条命令生成的随机值填入 `.env` 的 `JWT_SECRET`，配置如下：

```dotenv
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DATABASE=survey_pro1
JWT_SECRET=<替换为生成的随机值>
```

后端启动时检查密钥、数据库连接并创建必要索引，无需手动创建集合或导入账号。已有 `.env` 时不要再次复制覆盖。统一使用 `backend/.venv`，无需在根目录另建虚拟环境；下述命令直接指定其中的 Python，不依赖终端是否激活环境。

### 3.3 安装前端依赖

在项目根目录另开终端：

```powershell
cd frontend
npm.cmd ci
```

虚拟环境、`node_modules` 和构建产物可通过依赖文件重新生成，不需要上传仓库；含本地配置与密钥的 `.env` 不上传，保留 `.env.example`。

## 4. 启动与使用

按 MongoDB → 后端 → 前端的顺序启动，各进程分别保持运行。完成首次配置后，日常启动无需重复安装依赖或生成密钥。

后端终端：

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

前端终端：

```powershell
cd frontend
npm.cmd run dev
```

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:5173/` | 网页入口 |
| `http://127.0.0.1:8000/docs` | 交互式 API 文档与调试 |
| `http://127.0.0.1:8000/api/health` | 数据库连接健康检查 |

前端开发服务器将 `/api` 请求转发到本地 8000 端口。停止服务时在对应终端按 `Ctrl+C`。

基本使用流程：

1. 注册并登录，创建问卷草稿，添加题目、校验和跳转规则，保存后发布。
2. 分享生成的填写链接；填写者登录后作答，检查预览，再确认提交。
3. 创建者查看本卷统计；可复用题还可查看对应固定版本的全局统计。
4. 需要复用时，在“我的题目”创建题目，或将自己问卷中的临时题保存为可复用题；加入“我的题库”后复制题库 ID 分享给其他用户选用。

保存临时题为可复用题会关联当前原题与已有答案。题库“移出成员”只改变题目分类；“我的题目”转回临时题仅允许未引用或只有一份本人问卷引用的情况，多份引用或他人引用时拒绝操作。

### 可选：创建演示数据

在已配置后端环境且 MongoDB 运行时，于 `backend/` 目录执行：

```powershell
.\.venv\Scripts\python.exe seed_stage2_demo.py
```

脚本通过应用 API 写入当前配置数据库，创建四类题目、版本、草稿、发布问卷及示例答卷，无需另行启动后端 HTTP 服务。演示账号为 `stage2_demo_1028`，密码为 `Stage2Demo28`，仅用于本地体验。其他电脑需要运行脚本才会生成这些数据。

脚本发现指定演示发布问卷已存在时跳过创建，不重置后续编辑；它不是完整的数据恢复工具，也未覆盖全部题库分享场景。系统正常使用不依赖该脚本。

## 5. 测试与文档

### 后端测试

在 `backend/` 目录执行，默认运行内存替身测试并跳过真实库测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

启动 MongoDB 后，可启用完整测试。真实库测试使用随机命名的临时数据库，并在结束后清理：

```powershell
$env:RUN_MONGO_TESTS = "1"
try {
    .\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
} finally {
    Remove-Item Env:RUN_MONGO_TESTS
}
```

自动测试和构建不能代替页面交互验收，实际验证范围以测试文档为准。

### 项目文档

| 文档 | 内容 |
| --- | --- |
| [API 接口说明](docs/api.md) | 当前项目接口、参数、认证与权限 |
| [第一阶段设计](docs/design.md) | 原系统结构、数据库和基础逻辑 |
| [第二阶段设计](docs/design-2.md) | 版本复用、题库分享、兼容与全局统计 |
| [第一阶段测试](docs/testing.md) | 基础功能的测试设计与结果 |
| [第二阶段测试](docs/testing-2.md) | 新功能及旧功能回归的测试设计与结果 |
| [第一阶段 AI 日志](docs/ai-log.md) | 第一阶段 AI 协作与贡献记录 |
| [第二阶段 AI 日志](docs/ai-log-2.md) | 第二阶段 AI 协作与贡献记录 |
