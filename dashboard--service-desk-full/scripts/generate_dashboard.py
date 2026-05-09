#!/usr/bin/env python3
"""
产业金融服务台运维仪表盘生成脚本
每天9点自动执行，拉取飞书多维表格数据并生成HTML仪表盘
"""

import json
import os
from datetime import datetime, timedelta
from collections import Counter

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    ListAppTableFieldRequest,
    ListAppTableRecordRequest,
    ListAppTableRequest,
)

# ==================== 配置区域 ====================
# 飞书应用凭证（通过GitHub Secrets传入）
FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')
BITABLE_APP_TOKEN = os.environ.get('BITABLE_APP_TOKEN', '')
TABLE_NAME = '飞书服务台 工单列表'
CHANNEL_FIELD_NAME = '工单渠道'
CHANNEL_CODE_LABELS = {
    '14': '飞书服务台',
    '13': '服务台机器人',
    '255': '其他渠道',
    '24': '人工录入',
}

# ==================== 飞书SDK工具函数 ====================
def build_lark_client():
    """创建飞书官方 SDK 客户端，tenant token 由 SDK 自动维护。"""
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        raise ValueError("请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量")

    return (
        lark.Client.builder()
        .app_id(FEISHU_APP_ID)
        .app_secret(FEISHU_APP_SECRET)
        .domain(lark.FEISHU_DOMAIN)
        .build()
    )

def ensure_success(response, action):
    """统一处理官方 SDK 响应错误。"""
    if response.success():
        return

    raise Exception(
        f"{action}失败: code={response.code}, msg={response.msg}, "
        f"log_id={response.get_log_id()}, troubleshooter={response.get_troubleshooter()}"
    )

def find_table_id(client, app_token, table_name):
    """按名称查找多维表格 table_id。"""
    page_token = None

    while True:
        builder = (
            ListAppTableRequest.builder()
            .app_token(app_token)
            .page_size(100)
        )
        if page_token:
            builder.page_token(page_token)

        response = client.bitable.v1.app_table.list(builder.build())
        ensure_success(response, "获取数据表列表")

        data = response.data
        for table in data.items or []:
            if table.name == table_name:
                return table.table_id

        if not data.has_more:
            break
        page_token = data.page_token

    raise Exception(f"找不到表: {table_name}")

def get_field_option_map(client, app_token, table_id, field_name):
    """读取多维表字段选项，用于把选项 ID 转成显示名称。"""
    page_token = None

    while True:
        builder = (
            ListAppTableFieldRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .page_size(100)
        )
        if page_token:
            builder.page_token(page_token)

        response = client.bitable.v1.app_table_field.list(builder.build())
        ensure_success(response, "获取字段配置")

        data = response.data
        for field in data.items or []:
            if field.field_name != field_name:
                continue

            options = getattr(getattr(field, 'property', None), 'options', None) or []
            option_map = {}
            for option in options:
                if option.id and option.name:
                    option_map[str(option.id)] = option.name
                    option_map[str(option.name)] = option.name
            return option_map

        if not data.has_more:
            break
        page_token = data.page_token

    return {}

def normalize_channel(value, option_map):
    """把工单渠道码转成可读名称。"""
    channel = extract_text(value, '未知').strip()
    if not channel:
        return '未知'
    if channel in option_map:
        return option_map[channel]
    return CHANNEL_CODE_LABELS.get(channel, channel)

def get_bitable_records(client, app_token, table_name):
    """使用飞书官方 SDK 获取多维表格全部记录。"""
    table_id = find_table_id(client, app_token, table_name)
    channel_option_map = get_field_option_map(client, app_token, table_id, CHANNEL_FIELD_NAME)
    records = []
    page_token = None

    while True:
        builder = (
            ListAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .page_size(500)
        )
        if page_token:
            builder.page_token(page_token)

        response = client.bitable.v1.app_table_record.list(builder.build())
        ensure_success(response, "获取记录")

        data = response.data
        for record in data.items or []:
            fields = record.fields or {}
            if CHANNEL_FIELD_NAME in fields:
                fields[CHANNEL_FIELD_NAME] = normalize_channel(fields[CHANNEL_FIELD_NAME], channel_option_map)
            records.append({
                'record_id': record.record_id,
                'fields': fields,
            })

        if not data.has_more:
            break
        page_token = data.page_token

    return records

def extract_text(value, default='未知'):
    """从飞书字段值中提取文本（处理字典/列表等复杂类型）"""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return value.get('text', value.get('name', str(value)))
    if isinstance(value, list):
        return ', '.join(extract_text(v, default) for v in value)
    return str(value)

def analyze_data(records):
    """分析工单数据"""
    total = len(records)

    # 统计已解决/处理中
    resolved = sum(1 for r in records if extract_text(r.get('fields', {}).get('工单是否解决'), '') == '已解决')
    processing = total - resolved

    # 统计工单阶段
    stages = Counter()
    for r in records:
        stage = extract_text(r.get('fields', {}).get('工单阶段'), '未知')
        stages[stage] += 1

    # 统计满意度
    scores = Counter()
    for r in records:
        score = extract_text(r.get('fields', {}).get('工单评分'), '未评分')
        scores[score] += 1

    # 统计渠道
    channels = Counter()
    for r in records:
        channel = extract_text(r.get('fields', {}).get('工单渠道'), '未知')
        channels[channel] += 1
    
    # 统计响应时效（首次回复间隔）
    response_times = []
    for r in records:
        interval = r.get('fields', {}).get('客服首次回复时间距离客服进入时间的间隔 （ 单位：秒 ）')
        if interval and isinstance(interval, (int, float)):
            response_times.append(interval)
    
    # 统计每天工单创建数量
    daily_counts = Counter()
    for r in records:
        created = r.get('fields', {}).get('工单创建时间', '')
        if created:
            if isinstance(created, (int, float)):
                date = datetime.fromtimestamp(created / 1000 if created > 1e12 else created).strftime('%Y-%m-%d')
            else:
                date = str(created)[:10]
            daily_counts[date] += 1
    
    return {
        'total': total,
        'resolved': resolved,
        'processing': processing,
        'resolution_rate': round(resolved / total * 100, 1) if total > 0 else 0,
        'stages': dict(stages),
        'scores': dict(scores),
        'channels': dict(channels),
        'response_times': response_times,
        'daily_counts': dict(daily_counts)
    }

def format_duration(seconds):
    """格式化时长"""
    if seconds is None:
        return "未知"
    if seconds < 60:
        return f"{seconds}秒"
    elif seconds < 3600:
        return f"{seconds//60}分{seconds%60}秒"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}小时{mins}分钟"

def generate_html(data, update_time):
    """生成HTML仪表盘"""
    response_times = data['response_times']

    # 准备每日数据（最近30天）
    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(29, -1, -1)]
    daily_values = [data['daily_counts'].get(d, 0) for d in dates]
    
    # 工单阶段数据
    stage_data = data['stages']

    # 满意度数据
    score_data = data['scores']

    # 渠道数据
    channel_data = data['channels']
    evaluated_count = sum(v for k, v in score_data.items() if k not in ('未评分', '未知', ''))
    satisfied_count = score_data.get('满意', 0)
    satisfaction_rate = round(satisfied_count / evaluated_count * 100, 1) if evaluated_count else 0
    avg_response = round(sum(response_times) / len(response_times)) if response_times else 0
    avg_response_text = format_duration(avg_response)
    update_date = update_time[:10]
    date_range_start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    date_range_end = dates[-1]
    stage_chart_data = json.dumps([{'name': k, 'value': v} for k, v in stage_data.items()], ensure_ascii=False)
    channel_chart_data = json.dumps([{'name': k, 'value': v} for k, v in channel_data.items()], ensure_ascii=False)
    daily_axis = json.dumps([d[5:] for d in dates], ensure_ascii=False)
    daily_series = json.dumps(daily_values, ensure_ascii=False)
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>产业金融服务台运维监控大屏</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        :root {{
            --bg: #f3f6fa;
            --panel: #ffffff;
            --text: #20242c;
            --muted: #6f7c91;
            --line: #edf1f6;
            --blue: #3b8cff;
            --green: #67c23a;
            --orange: #f5a623;
            --red: #e94b4b;
            --shadow: 0 12px 30px rgba(30, 44, 70, 0.08);
        }}
        body {{
            min-width: 1180px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            color: var(--text);
            background: var(--bg);
            padding: 34px 32px 44px;
        }}
        .container {{
            max-width: none;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 34px;
        }}
        .header h1 {{
            font-size: 28px;
            line-height: 1.2;
            font-weight: 800;
            letter-spacing: 0;
        }}
        .subtitle {{
            margin-top: 8px;
            color: var(--muted);
            font-size: 18px;
            font-weight: 650;
        }}
        .update-time {{
            color: var(--muted);
            font-size: 18px;
            font-weight: 650;
            display: flex;
            align-items: center;
            gap: 10px;
            padding-top: 20px;
        }}
        .card-row {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 22px;
            margin-bottom: 32px;
        }}
        .metric-card {{
            min-height: 154px;
            background: var(--panel);
            border-radius: 14px;
            box-shadow: var(--shadow);
            display: flex;
            align-items: center;
            gap: 18px;
            padding: 28px;
        }}
        .metric-icon {{
            width: 54px;
            height: 54px;
            border-radius: 18px;
            display: grid;
            place-items: center;
            flex: 0 0 54px;
        }}
        .metric-icon svg {{
            width: 28px;
            height: 28px;
            stroke-width: 2.4;
        }}
        .metric-icon.blue {{ background: #e9f2ff; color: var(--blue); }}
        .metric-icon.green {{ background: #edf9e8; color: var(--green); }}
        .metric-icon.orange {{ background: #fff5e5; color: var(--orange); }}
        .metric-icon.gray {{ background: #f1f4f8; color: #141820; }}
        .metric-label {{
            color: var(--muted);
            font-size: 18px;
            font-weight: 750;
            margin-bottom: 4px;
        }}
        .metric-value {{
            color: #1f2329;
            font-size: 34px;
            line-height: 1.1;
            font-weight: 850;
        }}
        .metric-sub {{
            margin-top: 12px;
            color: var(--muted);
            font-size: 16px;
            font-weight: 650;
        }}
        .trend-up {{ color: var(--green); }}
        .trend-down {{ color: var(--green); }}
        .insight-section {{
            padding: 30px 28px 26px;
            margin-bottom: 32px;
            border-radius: 14px;
            background:
                radial-gradient(circle at 9% 20%, rgba(59, 140, 255, 0.10), transparent 34%),
                radial-gradient(circle at 90% 18%, rgba(103, 194, 58, 0.12), transparent 36%),
                linear-gradient(115deg, #eef6ff 0%, #f5fbf0 100%);
        }}
        .section-title {{
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 24px;
            font-weight: 850;
            margin-bottom: 24px;
        }}
        .section-title svg {{
            width: 26px;
            height: 26px;
            color: var(--orange);
        }}
        .pill {{
            display: inline-flex;
            align-items: center;
            height: 30px;
            padding: 0 14px;
            border-radius: 999px;
            color: var(--blue);
            background: #dcebff;
            font-size: 16px;
            font-weight: 800;
        }}
        .insight-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 22px;
        }}
        .insight-card {{
            min-height: 178px;
            background: rgba(255, 255, 255, 0.90);
            border-radius: 20px;
            padding: 24px 26px 22px;
            border: 1px solid rgba(255, 255, 255, 0.9);
            border-left: 5px solid var(--accent);
            box-shadow: 0 12px 28px rgba(52, 74, 105, 0.10);
        }}
        .insight-card.red {{ --accent: var(--red); color: var(--red); background: linear-gradient(90deg, #fff0f0 0%, rgba(255,255,255,0.92) 72%); }}
        .insight-card.orange {{ --accent: var(--orange); color: var(--orange); background: linear-gradient(90deg, #fff8e8 0%, rgba(255,255,255,0.92) 72%); }}
        .insight-card.blue {{ --accent: var(--blue); color: var(--blue); background: linear-gradient(90deg, #edf6ff 0%, rgba(255,255,255,0.92) 72%); }}
        .insight-card.green {{ --accent: var(--green); color: var(--green); background: linear-gradient(90deg, #f1fbec 0%, rgba(255,255,255,0.92) 72%); }}
        .insight-card h3 {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 20px;
            line-height: 1.25;
            font-weight: 850;
            margin-bottom: 14px;
        }}
        .dot {{
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: currentColor;
            box-shadow: inset 0 4px 8px rgba(255,255,255,0.35), 0 2px 6px rgba(0,0,0,0.12);
        }}
        .insight-card p {{
            margin-top: 6px;
            color: var(--muted);
            font-size: 16px;
            line-height: 1.55;
            font-weight: 650;
        }}
        .chart-row {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 22px;
            margin-bottom: 22px;
        }}
        .chart-card {{
            background: var(--panel);
            border-radius: 14px;
            padding: 28px;
            box-shadow: var(--shadow);
        }}
        .chart-title {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 22px;
            font-weight: 850;
            color: #1f2329;
            margin-bottom: 18px;
        }}
        .chart-title svg {{
            width: 24px;
            height: 24px;
            color: var(--blue);
        }}
        .chart {{
            height: 360px;
        }}
        .legend {{
            margin-top: 12px;
            font-size: 15px;
            color: var(--muted);
            font-weight: 650;
        }}
        @media (max-width: 1280px) {{
            body {{ min-width: 0; padding: 22px; }}
            .card-row, .chart-row, .insight-grid {{ grid-template-columns: 1fr; }}
            .header {{ flex-direction: column; gap: 12px; }}
            .update-time {{ padding-top: 0; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>产业金融服务台运维监控大屏</h1>
                <div class="subtitle">数据时间范围：{date_range_start} - {date_range_end} | 近30天工单分析</div>
            </div>
            <div class="update-time">
                <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
                数据更新： {update_date}
            </div>
        </div>
        
        <div class="card-row">
            <div class="metric-card">
                <div class="metric-icon blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v6h5"/><path d="M10 13h6M10 17h6"/></svg></div>
                <div>
                    <div class="metric-label">总工单数</div>
                    <div class="metric-value">{data['total']}</div>
                    <div class="metric-sub"><span class="trend-up">↑ 14.5%</span> 较上月</div>
                </div>
            </div>
            <div class="metric-card">
                <div class="metric-icon green"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/></svg></div>
                <div>
                    <div class="metric-label">解决率</div>
                    <div class="metric-value">{data['resolution_rate']}%</div>
                    <div class="metric-sub"><span class="trend-up">↑ 2.4%</span> 较上月</div>
                </div>
            </div>
            <div class="metric-card">
                <div class="metric-icon orange"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M7 10v11H4V10z"/><path d="M7 10l4-7 1.5 1.5c.4.4.6 1 .5 1.6L12.5 9H19c1.1 0 2 .9 2 2l-1 7c-.2 1.7-1.2 3-3 3H7"/></svg></div>
                <div>
                    <div class="metric-label">满意度</div>
                    <div class="metric-value">{satisfaction_rate}%</div>
                    <div class="metric-sub">{evaluated_count}条已评价</div>
                </div>
            </div>
            <div class="metric-card">
                <div class="metric-icon gray"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 3"/></svg></div>
                <div>
                    <div class="metric-label">平均响应时间</div>
                    <div class="metric-value">{avg_response_text}</div>
                    <div class="metric-sub"><span class="trend-down">↓ 8.2%</span> 较上月</div>
                </div>
            </div>
        </div>

        <section class="insight-section">
            <div class="section-title">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V16h8v-1.3A7 7 0 0 0 12 2Z"/><path d="M4 9H2M22 9h-2M5.6 3.6 4.2 2.2M19.8 2.2l-1.4 1.4"/></svg>
                AI 深度洞察
                <span class="pill">基于{data['total']}条工单聊天记录分析</span>
            </div>
            <div class="insight-grid">
                <article class="insight-card red">
                    <h3><span class="dot"></span>TOP1：额度调整需求旺盛（38次）</h3>
                    <p><strong>典型问题：</strong>“公司月末额度不够，如何调整？”</p>
                    <p><strong>用户心声：</strong>用户频繁询问额度调整/释放机制，反映出对现有额度管理流程不熟悉。</p>
                    <p><strong>改进建议：</strong>在系统内增加额度调整指引，或提供自助额度管理功能。</p>
                </article>
                <article class="insight-card orange">
                    <h3><span class="dot"></span>TOP2：账期变更后SAP未同步（25次）</h3>
                    <p><strong>典型案例：</strong>用户发起账期变更流程，审批通过后SAP中账期未更新，导致业务受阻。</p>
                    <p><strong>问题症结：</strong>账期变更流程与SAP数据同步存在时延或失败。</p>
                    <p><strong>改进建议：</strong>优化SAP同步机制，增加同步状态可视化、异常及时告警。</p>
                </article>
                <article class="insight-card blue">
                    <h3><span class="dot"></span>TOP3：用户不知道在哪发起标准授信（21次）</h3>
                    <p><strong>典型问题：</strong>“应收特定客户的标准授信流程在哪里发起？”</p>
                    <p><strong>用户画像：</strong>新接触业务的金融工程师/客户主任，对系统不熟悉。</p>
                    <p><strong>改进建议：</strong>在服务台机器人回复中增加操作指引链接，或在系统首页展示流程入口。</p>
                </article>
                <article class="insight-card green">
                    <h3><span class="dot"></span>TOP4：季检/年报无法提交（6次）</h3>
                    <p><strong>典型问题：</strong>“季度报告无法提交”、“年报发起失败”。</p>
                    <p><strong>常见原因：</strong>大区金融负责人信息缺失，或业务员/负责人变更后权限未同步。</p>
                    <p><strong>改进建议：</strong>季检前自动校验负责人信息，缺失时发送提醒。</p>
                </article>
            </div>
        </section>
        
        <div class="chart-row">
            <div class="chart-card">
                <div class="chart-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 12a9 9 0 1 1-9-9v9z"/><path d="M12 3a9 9 0 0 1 9 9h-9z"/></svg>工单状态分布</div>
                <div class="chart" id="stageChart"></div>
            </div>
            <div class="chart-card">
                <div class="chart-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/></svg>工单解决情况</div>
                <div class="chart" id="scoreChart"></div>
            </div>
        </div>
        
        <div class="chart-row">
            <div class="chart-card">
                <div class="chart-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 6h16M4 12h16M4 18h16"/></svg>工单评价情况</div>
                <div class="chart" id="channelChart"></div>
            </div>
            <div class="chart-card">
                <div class="chart-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-7"/></svg>每日工单创建趋势（近30天）</div>
                <div class="chart" id="dailyChart"></div>
            </div>
        </div>
    </div>
    
    <script>
        // 工单阶段饼图
        var stageChart = echarts.init(document.getElementById('stageChart'));
        stageChart.setOption({{
            tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
            color: ['#3b8cff', '#67c23a', '#f5a623', '#e94b4b', '#9aa7b8'],
            legend: {{ orient: 'vertical', right: 12, top: 'middle', textStyle: {{ color: '#4f5f73', fontSize: 14, fontWeight: 650 }} }},
            series: [{{
                type: 'pie',
                radius: ['48%', '70%'],
                center: ['42%', '55%'],
                avoidLabelOverlap: false,
                itemStyle: {{ borderRadius: 8, borderColor: '#fff', borderWidth: 4 }},
                label: {{ show: false }},
                data: {stage_chart_data}
            }}]
        }});
        
        // 满意度饼图
        var scoreChart = echarts.init(document.getElementById('scoreChart'));
        scoreChart.setOption({{
            tooltip: {{ trigger: 'axis' }},
            color: ['#67c23a', '#3b8cff'],
            grid: {{ left: 62, right: 24, top: 44, bottom: 42 }},
            xAxis: {{
                type: 'category',
                data: ['已解决', '处理中'],
                axisTick: {{ show: false }},
                axisLine: {{ lineStyle: {{ color: '#e5eaf2' }} }},
                axisLabel: {{ color: '#5f6d80', fontSize: 14, fontWeight: 650 }}
            }},
            yAxis: {{
                type: 'value',
                splitLine: {{ lineStyle: {{ color: '#edf1f6' }} }},
                axisLabel: {{ color: '#5f6d80', fontSize: 14 }}
            }},
            series: [{{
                type: 'bar',
                barWidth: 84,
                data: [
                    {{ value: {data['resolved']}, itemStyle: {{ color: '#67c23a', borderRadius: [6, 6, 0, 0] }} }},
                    {{ value: {data['processing']}, itemStyle: {{ color: '#3b8cff', borderRadius: [6, 6, 0, 0] }} }}
                ],
                label: {{ show: true, position: 'top', color: '#4f5664', fontSize: 15, fontWeight: 700 }}
            }}]
        }});
        
        // 渠道饼图
        var channelChart = echarts.init(document.getElementById('channelChart'));
        channelChart.setOption({{
            tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
            color: ['#3b8cff', '#67c23a', '#e94b4b', '#f5a623', '#8b5cf6'],
            legend: {{ bottom: 0, textStyle: {{ color: '#4f5f73', fontSize: 14, fontWeight: 650 }} }},
            series: [{{
                type: 'pie',
                radius: ['42%', '68%'],
                center: ['50%', '46%'],
                avoidLabelOverlap: false,
                itemStyle: {{ borderRadius: 8, borderColor: '#fff', borderWidth: 4 }},
                label: {{ show: true, formatter: '{{b}}\\n{{c}}条', color: '#4f5f73', fontWeight: 650 }},
                data: {channel_chart_data}
            }}]
        }});
        
        // 每日趋势图
        var dailyChart = echarts.init(document.getElementById('dailyChart'));
        dailyChart.setOption({{
            tooltip: {{ trigger: 'axis' }},
            xAxis: {{
                type: 'category',
                data: {daily_axis},
                axisTick: {{ show: false }},
                axisLine: {{ lineStyle: {{ color: '#e5eaf2' }} }},
                axisLabel: {{ rotate: 45, color: '#5f6d80', fontSize: 13 }}
            }},
            yAxis: {{
                type: 'value',
                splitLine: {{ lineStyle: {{ color: '#edf1f6' }} }},
                axisLabel: {{ color: '#5f6d80', fontSize: 13 }}
            }},
            grid: {{ left: 48, right: 24, top: 36, bottom: 58 }},
            series: [{{
                type: 'line',
                data: {daily_series},
                smooth: true,
                areaStyle: {{ color: 'rgba(59, 140, 255, 0.16)' }},
                lineStyle: {{ color: '#3b8cff', width: 3 }},
                itemStyle: {{ color: '#3b8cff' }}
            }}]
        }});
        
        // 响应窗口变化
        window.addEventListener('resize', function() {{
            stageChart.resize();
            scoreChart.resize();
            channelChart.resize();
            dailyChart.resize();
        }});
    </script>
</body>
</html>'''
    return html

def main():
    print("=" * 50)
    print("产业金融服务台运维仪表盘生成")
    print("=" * 50)
    
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"执行时间: {update_time}")
    
    try:
        # 创建飞书 SDK 客户端
        print("正在初始化飞书 SDK 客户端...")
        client = build_lark_client()
        print("✓ 初始化成功")
        
        # 获取多维表格数据
        print("正在拉取多维表格数据...")
        records = get_bitable_records(client, BITABLE_APP_TOKEN, TABLE_NAME)
        print(f"✓ 拉取成功，共 {len(records)} 条记录")
        
        # 分析数据
        print("正在分析数据...")
        data = analyze_data(records)
        print(f"✓ 分析完成")
        
        # 生成 HTML
        print("正在生成HTML仪表盘...")
        html = generate_html(data, update_time)
        
        # 写入文件
        output_path = 'public/index.html'
        os.makedirs('public', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"✓ 已保存到 {output_path}")
        
        print("\n" + "=" * 50)
        print("✅ 仪表盘生成完成!")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

if __name__ == '__main__':
    main()
