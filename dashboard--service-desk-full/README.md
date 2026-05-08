# 产业金融服务台运维监控仪表盘

📊 **每日自动更新的运维监控仪表盘**

## 功能特点

- ✅ **每日9点自动更新**：通过 GitHub Actions 定时拉取最新工单数据
- ✅ **自动部署**：GitHub 推送后 Netlify 自动部署新版本
- ✅ **实时数据**：包含工单统计、满意度、响应时效等多维度分析
- ✅ **交互式图表**：使用 ECharts.js 支持悬停查看详情

## 数据来源

- **飞书多维表格**：[产业金融服务台工单列表](https://haidgroup.feishu.cn/base/REDACTED)
- **更新频率**：每天早上9:00（北京时间）

## 部署步骤

### 1. 上传代码到 GitHub

将本项目所有文件上传到你的 GitHub 仓库：
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/你的用户名/dashboard--service-desk.git
git push -u origin main
```

### 2. 在 GitHub 设置 Secrets

在 GitHub 仓库的 `Settings` → `Secrets and variables` → `Actions` 中添加以下 Secrets：

| Secret 名称 | 说明 | 获取方式 |
|-------------|------|----------|
| `FEISHU_APP_ID` | 飞书应用 ID | 飞书开放平台 → 应用凭证 |
| `FEISHU_APP_SECRET` | 飞书应用密钥 | 飞书开放平台 → 应用凭证 |
| `BITABLE_APP_TOKEN` | 多维表格 Token | 多维表格 URL 中获取（默认为 REDACTED）|

### 3. 在 Netlify 绑定 GitHub

1. 打开 [Netlify](https://app.netlify.com)
2. 点击 `Add new site` → `Import an existing project`
3. 选择 `GitHub`
4. 选择仓库 `dashboard--service-desk`
5. 配置：
   - **Build command**: （留空）
   - **Publish directory**: `public`
6. 点击 `Deploy site`

### 4. 验证部署

部署成功后，访问 Netlify 提供的 URL（如 `xxx.netlify.app`）即可看到仪表盘。

## 项目结构

```
dashboard--service-desk/
├── .github/
│   └── workflows/
│       └── daily-update.yml    # GitHub Actions 定时任务配置
├── scripts/
│   └── generate_dashboard.py   # 数据拉取和HTML生成脚本
├── public/
│   └── index.html              # 仪表盘页面（每天自动更新）
├── netlify.toml                # Netlify 配置文件
└── README.md                   # 说明文档
```

## 自动更新流程

```
每天 9:00（北京时间）
       ↓
GitHub Actions 自动触发
       ↓
1. 拉取飞书多维表格最新工单数据
       ↓
2. Python 脚本分析数据并生成 HTML
       ↓
3. 自动 commit 更新 public/index.html
       ↓
4. Netlify 检测到代码更新
       ↓
5. 自动重新部署
       ↓
6. 用户访问 URL 看到最新数据 🎉
```

## 手动触发更新

如果需要立即更新，可以：

1. 打开 GitHub 仓库
2. 点击 `Actions` 标签
3. 选择 `每日仪表盘更新` 工作流
4. 点击 `Run workflow` → `Run workflow`

## 查看数据指标

仪表盘包含以下数据：

| 指标 | 说明 |
|------|------|
| 总工单数 | 近30天累计工单数量 |
| 已解决 | 状态为"已解决"的工单数量 |
| 处理中 | 当前正在处理的工单数量 |
| 满意率 | 已评价工单中的满意比例 |
| 工单阶段分布 | 人工处理 / 机器人关闭 / 处理中 |
| 满意度分布 | 满意 / 一般 / 不满意 / 未评分 |
| 工单渠道分布 | 各渠道来源工单占比 |
| 每日趋势 | 近30天每日工单创建量 |
| 响应时效 | 首次回复时间分布 |

## 注意事项

1. **飞书应用权限**：确保应用有多维表格的读取权限
2. **API 频率限制**：GitHub Actions 每天最多执行60次，注意不要频繁触发
3. **数据延迟**：工单数据可能有1-2分钟的延迟

## 技术栈

- **前端**：HTML + CSS + JavaScript
- **图表**：ECharts.js 5.4.3
- **后端**：GitHub Actions（Python 脚本）
- **部署**：Netlify

## 许可证

内部使用
