#!/usr/bin/env python3
"""
产业金融服务台运维仪表盘生成脚本
每天9点自动执行，拉取飞书多维表格数据并生成HTML仪表盘
"""

import json
import os
import requests
from datetime import datetime, timedelta
from collections import Counter

# ==================== 配置区域 ====================
# 飞书应用凭证（通过GitHub Secrets传入）
FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')
BITABLE_APP_TOKEN = os.environ.get('BITABLE_APP_TOKEN', 'REDACTED')
TABLE_NAME = '飞书服务台 工单列表'

# ==================== 飞书API工具函数 ====================
def get_tenant_access_token():
    """获取飞书 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    data = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    
    if result.get('code') == 0:
        return result.get('tenant_access_token')
    else:
        raise Exception(f"获取token失败: {result}")

def get_bitable_records(token, app_token, table_name):
    """获取多维表格数据"""
    # 先获取 table_id
    list_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(list_url, headers=headers)
    tables = response.json().get('data', {}).get('items', [])
    
    table_id = None
    for table in tables:
        if table.get('name') == table_name:
            table_id = table.get('table_id')
            break
    
    if not table_id:
        raise Exception(f"找不到表: {table_name}")
    
    # 获取所有记录
    records = []
    page_token = None
    
    while True:
        records_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
            
        response = requests.get(records_url, headers=headers, params=params)
        result = response.json()
        
        if result.get('code') == 0:
            records.extend(result.get('data', {}).get('items', []))
            has_more = result.get('data', {}).get('has_more', False)
            if has_more:
                page_token = result.get('data', {}).get('page_token')
            else:
                break
        else:
            raise Exception(f"获取记录失败: {result}")
    
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
    # 计算响应时效分布
    response_times = data['response_times']
    response_buckets = {
        '<1分钟': 0,
        '1-5分钟': 0,
        '5-15分钟': 0,
        '15-30分钟': 0,
        '30-60分钟': 0,
        '>1小时': 0
    }
    
    for seconds in response_times:
        if seconds < 60:
            response_buckets['<1分钟'] += 1
        elif seconds < 300:
            response_buckets['1-5分钟'] += 1
        elif seconds < 900:
            response_buckets['5-15分钟'] += 1
        elif seconds < 1800:
            response_buckets['15-30分钟'] += 1
        elif seconds < 3600:
            response_buckets['30-60分钟'] += 1
        else:
            response_buckets['>1小时'] += 1
    
    # 准备每日数据（最近30天）
    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(29, -1, -1)]
    daily_values = [data['daily_counts'].get(d, 0) for d in dates]
    
    # 工单阶段数据
    stage_data = data['stages']
    stage_labels = list(stage_data.keys())
    stage_values = list(stage_data.values())
    
    # 满意度数据
    score_data = data['scores']
    score_labels = list(score_data.keys())
    score_values = list(score_data.values())
    
    # 渠道数据
    channel_data = data['channels']
    channel_labels = list(channel_data.keys())
    channel_values = list(channel_data.values())
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>产业金融服务台运维监控仪表盘</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #F5F7FA;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #3370FF 0%, #0D47A1 100%);
            color: white;
            padding: 24px 32px;
            border-radius: 12px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{
            font-size: 24px;
            font-weight: 600;
        }}
        .header .update-time {{
            font-size: 14px;
            opacity: 0.9;
        }}
        .card-row {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin-bottom: 20px;
        }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .card .label {{
            font-size: 14px;
            color: #646A7B;
            margin-bottom: 8px;
        }}
        .card .value {{
            font-size: 32px;
            font-weight: 700;
            color: #3370FF;
        }}
        .card .sub {{
            font-size: 13px;
            color: #969BAB;
            margin-top: 4px;
        }}
        .chart-row {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-bottom: 20px;
        }}
        .chart-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .chart-title {{
            font-size: 16px;
            font-weight: 600;
            color: #1F2329;
            margin-bottom: 16px;
        }}
        .chart {{
            height: 280px;
        }}
        .info-row {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
        }}
        .info-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .info-title {{
            font-size: 16px;
            font-weight: 600;
            color: #1F2329;
            margin-bottom: 16px;
        }}
        .stat-item {{
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #F1F3F5;
        }}
        .stat-item:last-child {{
            border-bottom: none;
        }}
        .stat-label {{
            color: #646A7B;
        }}
        .stat-value {{
            font-weight: 600;
            color: #1F2329;
        }}
        .legend {{
            margin-top: 12px;
            font-size: 13px;
            color: #969BAB;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 产业金融服务台运维监控仪表盘</h1>
            <div class="update-time">数据更新：{update_time}</div>
        </div>
        
        <div class="card-row">
            <div class="card">
                <div class="label">📋 总工单数</div>
                <div class="value">{data['total']}</div>
                <div class="sub">近30天累计</div>
            </div>
            <div class="card">
                <div class="label">✅ 已解决</div>
                <div class="value">{data['resolved']}</div>
                <div class="sub">解决率 {data['resolution_rate']}%</div>
            </div>
            <div class="card">
                <div class="label">⏳ 处理中</div>
                <div class="value">{data['processing']}</div>
                <div class="sub">需要关注</div>
            </div>
            <div class="card">
                <div class="label">😊 满意率</div>
                <div class="value">{round(score_data.get('满意', 0) / sum(score_data.values()) * 100, 1) if sum(score_data.values()) > 0 else 0}%</div>
                <div class="sub">已评价工单</div>
            </div>
        </div>
        
        <div class="chart-row">
            <div class="chart-card">
                <div class="chart-title">📈 工单阶段分布</div>
                <div class="chart" id="stageChart"></div>
                <div class="legend">人工处理 / 机器人关闭 / 处理中</div>
            </div>
            <div class="chart-card">
                <div class="chart-title">😊 满意度分布</div>
                <div class="chart" id="scoreChart"></div>
                <div class="legend">已评价：满意 / 一般 / 不满意</div>
            </div>
        </div>
        
        <div class="chart-row">
            <div class="chart-card">
                <div class="chart-title">📱 工单渠道分布</div>
                <div class="chart" id="channelChart"></div>
            </div>
            <div class="chart-card">
                <div class="chart-title">📅 每日工单创建趋势（近30天）</div>
                <div class="chart" id="dailyChart"></div>
            </div>
        </div>
        
        <div class="info-row">
            <div class="info-card">
                <div class="info-title">⏱️ 响应时效统计</div>
                <div class="stat-item">
                    <span class="stat-label"><1分钟</span>
                    <span class="stat-value">{response_buckets['<1分钟']}条</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">1-5分钟</span>
                    <span class="stat-value">{response_buckets['1-5分钟']}条</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">5-15分钟</span>
                    <span class="stat-value">{response_buckets['5-15分钟']}条</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">15-30分钟</span>
                    <span class="stat-value">{response_buckets['15-30分钟']}条</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">30-60分钟</span>
                    <span class="stat-value">{response_buckets['30-60分钟']}条</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">>1小时</span>
                    <span class="stat-value">{response_buckets['>1小时']}条</span>
                </div>
            </div>
            <div class="info-card">
                <div class="info-title">🔗 相关链接</div>
                <div class="stat-item">
                    <span class="stat-label">多维表格</span>
                    <span class="stat-value"><a href="https://haidgroup.feishu.cn/base/REDACTED" target="_blank">查看</a></span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">服务台</span>
                    <span class="stat-value"><a href="https://haidgroup.feishu.cn/serviceDesk/base/7036997285364023297" target="_blank">查看</a></span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">工单分析报告</span>
                    <span class="stat-value"><a href="https://haidgroup.feishu.cn/wiki/M2rnwOROBiZQbLkg5Eoclvz5nsg" target="_blank">查看</a></span>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // 工单阶段饼图
        var stageChart = echarts.init(document.getElementById('stageChart'));
        stageChart.setOption({{
            tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
            color: ['#3370FF', '#00B42A', '#FF7D00'],
            series: [{{
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: false,
                itemStyle: {{ borderRadius: 8, borderColor: '#fff', borderWidth: 2 }},
                label: {{ show: true, formatter: '{{b}}\\n{{c}}条' }},
                data: {json.dumps([{{'name': k, 'value': v}} for k, v in stage_data.items()])}
            }}]
        }});
        
        // 满意度饼图
        var scoreChart = echarts.init(document.getElementById('scoreChart'));
        scoreChart.setOption({{
            tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
            color: ['#00B42A', '#FF7D00', '#F53F3F', '#86909C'],
            series: [{{
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: false,
                itemStyle: {{ borderRadius: 8, borderColor: '#fff', borderWidth: 2 }},
                label: {{ show: true, formatter: '{{b}}\\n{{c}}条' }},
                data: {json.dumps([{{'name': k, 'value': v}} for k, v in score_data.items()])}
            }}]
        }});
        
        // 渠道饼图
        var channelChart = echarts.init(document.getElementById('channelChart'));
        channelChart.setOption({{
            tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
            color: ['#3370FF', '#00B42A', '#F53F3F', '#FF7D00', '#722ED1'],
            series: [{{
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: false,
                itemStyle: {{ borderRadius: 8, borderColor: '#fff', borderWidth: 2 }},
                label: {{ show: true, formatter: '{{b}}\\n{{c}}条' }},
                data: {json.dumps([{{'name': k, 'value': v}} for k, v in channel_data.items()])}
            }}]
        }});
        
        // 每日趋势图
        var dailyChart = echarts.init(document.getElementById('dailyChart'));
        dailyChart.setOption({{
            tooltip: {{ trigger: 'axis' }},
            xAxis: {{
                type: 'category',
                data: {json.dumps([d[5:] for d in dates])},
                axisLabel: {{ rotate: 45 }}
            }},
            yAxis: {{ type: 'value' }},
            series: [{{
                type: 'line',
                data: {json.dumps(daily_values)},
                smooth: true,
                areaStyle: {{ color: 'rgba(51, 112, 255, 0.2)' }},
                lineStyle: {{ color: '#3370FF', width: 2 }},
                itemStyle: {{ color: '#3370FF' }}
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
        # 获取 token
        print("正在获取飞书访问令牌...")
        token = get_tenant_access_token()
        print(f"✓ 获取成功")
        
        # 获取多维表格数据
        print("正在拉取多维表格数据...")
        records = get_bitable_records(token, BITABLE_APP_TOKEN, TABLE_NAME)
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
