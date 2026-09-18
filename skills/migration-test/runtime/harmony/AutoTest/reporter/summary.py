"""批量执行汇总报告生成器"""
import os
import datetime
from ..logger import logger


def generate_summary_report(results, total_duration, output_dir):
    """生成批量执行汇总HTML报告"""
    if not output_dir:
        return

    success_count = sum(1 for r in results if r.get('case_result') == 'PASS')
    fail_count = sum(1 for r in results if r.get('case_result') == 'FAIL')
    pass_rate = (success_count / len(results) * 100) if len(results) > 0 else 0

    # 生成用例列表HTML
    case_rows = ""
    for idx, case in enumerate(results, 1):
        # 执行状态：完成为成功，异常或者超时为失败
        status_class = "status-pass" if case['status'] == 'success' else "status-fail"
        status_text = "成功" if case['status'] == 'success' else "失败"
        # 执行结果：同每个case内的执行结果(PASS/FAIL/UNKNOWN)
        case_result = case.get('case_result', 'UNKNOWN')
        if case_result == 'PASS':
            result_class = "status-pass"
            result_text = "通过"
        elif case_result == 'FAIL':
            result_class = "status-fail"
            result_text = "不通过"
        else:
            result_class = "status-unknown"
            result_text = "未知"
        duration = f"{case['duration']:.2f}s"
        report_link = f'<a href="{case["report_path"]}" target="_blank" class="report-link">查看报告</a>' if case[
            'report_path'] else '<span class="no-report">无报告</span>'

        case_rows += f"""
        <tr>
            <td>{idx}</td>
            <td>{case['name']}</td>
            <td><span class="status-badge {status_class}">{status_text}</span></td>
            <td><span class="status-badge {result_class}">{result_text}</span></td>
            <td>{duration}</td>
            <td>{report_link}</td>
        </tr>
        """

    # 生成完整HTML
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>批量测试执行汇总报告</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .overview {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .overview-card {{
            background-color: #f9f9f9;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            border-left: 4px solid #4CAF50;
        }}
        .overview-card.fail {{
            border-left-color: #F44336;
        }}
        .overview-card.total {{
            border-left-color: #2196F3;
        }}
        .overview-card.rate {{
            border-left-color: #FF9800;
        }}
        .card-title {{
            font-size: 14px;
            color: #666;
            margin-bottom: 10px;
        }}
        .card-value {{
            font-size: 32px;
            font-weight: bold;
            color: #333;
        }}
        .progress-bar {{
            width: 100%;
            height: 20px;
            background-color: #e0e0e0;
            border-radius: 10px;
            overflow: hidden;
            margin: 20px 0;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #4CAF50 0%, #8BC34A 100%);
            width: {pass_rate}%;
            transition: width 0.5s ease;
        }}
        .progress-text {{
            text-align: center;
            font-size: 14px;
            color: #666;
            margin-bottom: 30px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background-color: #f5f5f5;
            font-weight: 600;
            color: #333;
        }}
        tr:hover {{
            background-color: #fafafa;
        }}
        .status-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 15px;
            color: white;
            font-weight: bold;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .status-pass {{
            background-color: #4CAF50;
        }}
        .status-fail {{
            background-color: #F44336;
        }}
        .status-unknown {{
            background-color: #FF9800;
        }}
        .report-link {{
            display: inline-block;
            padding: 6px 12px;
            background-color: #2196F3;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 12px;
            transition: background-color 0.2s;
        }}
        .report-link:hover {{
            background-color: #1976D2;
        }}
        .no-report {{
            color: #999;
            font-size: 12px;
        }}
        .meta-info {{
            background-color: #f9f9f9;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            color: #666;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 批量测试执行汇总报告</h1>
        
        <div class="meta-info">
            <div><strong>执行时间:</strong> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
            <div><strong>总耗时:</strong> {total_duration:.2f}s</div>
        </div>

        <div class="overview">
            <div class="overview-card total">
                <div class="card-title">总用例数</div>
                <div class="card-value">{len(results)}</div>
            </div>
            <div class="overview-card">
                <div class="card-title">成功用例</div>
                <div class="card-value" style="color: #4CAF50;">{success_count}</div>
            </div>
            <div class="overview-card fail">
                <div class="card-title">失败用例</div>
                <div class="card-value" style="color: #F44336;">{fail_count}</div>
            </div>
            <div class="overview-card rate">
                <div class="card-title">执行通过率</div>
                <div class="card-value" style="color: #FF9800;">{pass_rate:.1f}%</div>
            </div>
        </div>

        <div class="progress-bar">
            <div class="progress-fill"></div>
        </div>
        <div class="progress-text">通过率: {pass_rate:.1f}% ({success_count}/{len(results)})</div>

        <h2>用例执行详情</h2>
        <table>
            <thead>
                <tr>
                    <th>序号</th>
                    <th>用例名称</th>
                    <th>执行状态</th>
                    <th>执行结果</th>
                    <th>执行耗时</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
                {case_rows}
            </tbody>
        </table>
    </div>
</body>
</html>"""

    # 保存汇总报告
    os.makedirs(output_dir, exist_ok=True)
    summary_path = os.path.join(output_dir, "index.html")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info("汇总报告已生成: file://{}".format(os.path.abspath(summary_path).replace('\\', '/')))
