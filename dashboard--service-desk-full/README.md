# 产业金融服务台运维监控仪表盘

每日自动更新的运维监控仪表盘

## 功能特点

- 每日9点（北京时间）自动更新，通过 GitHub Actions 拉取飞书工单数据
- 推送后 Cloudflare Pages 自动部署
- 包含工单统计、满意度、响应时效等多维度分析
- 使用 ECharts.js 支持交互式图表

## 数据来源

- 飞书多维表格：产业金融服务台工单列表
- 更新频率：每天早上 9:00（北京时间）

## 部署步骤

### 1. 上传代码到 GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<你的用户名>/dashboard-service-desk.git
git push -u origin main
```

### 2. 在 GitHub 设置 Secrets

仓库 `Settings` → `Secrets and variables` → `Actions`：

| Secret 名称 | 说明 |
|-------------|------|
| `FEISHU_APP_ID` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 飞书应用密钥 |
| `BITABLE_APP_TOKEN` | 多维表格 Token（默认 `Ds5qb6T8aaPTmVsDipbcL8xUnyf`）|

### 3. 在 Cloudflare Pages 绑定 GitHub

1. 打开 [Cloudflare Dashboard](https://dash.cloudflare.com) → `Workers & Pages`
2. 点击 `Create` → `Pages` → `Connect to Git`
3. 选择 GitHub 仓库 `dashboard-service-desk`
4. 配置：
   - **Production branch**: `main`
   - **Build command**: （留空）
   - **Build output directory**: `dashboard--service-desk-full/public`
5. 点击 `Save and Deploy`

部署成功后，访问 Cloudflare 分配的 `xxx.pages.dev` 域名即可。

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
3. 自动 commit 更新 index.html
       ↓
4. Cloudflare Pages 检测到代码更新
       ↓
5. 自动重新部署
       ↓
6. 用户访问 URL 看到最新数据
```

## 手动触发更新

GitHub 仓库 → `Actions` → `每日仪表盘更新` → `Run workflow`

## 项目结构

```
dashboard-service-desk/
├── .github/
│   └── workflows/
│       └── daily-update.yml       # GitHub Actions 定时任务
├── dashboard--service-desk-full/
│   ├── scripts/
│   │   └── generate_dashboard.py  # 数据拉取和 HTML 生成
│   ├── public/
│   │   └── index.html             # 仪表盘页面（每天自动更新）
│   └── README.md
└── README.md
```

## 技术栈

- 前端：HTML + CSS + JavaScript
- 图表：ECharts.js 5.4.3
- 数据拉取：GitHub Actions（Python）
- 部署：Cloudflare Pages
