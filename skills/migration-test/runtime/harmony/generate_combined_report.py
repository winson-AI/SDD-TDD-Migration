import os
import json
import sys
sys.dont_write_bytecode = True
import re
import argparse
from pathlib import Path
from datetime import datetime
from AutoTest.storage import output_path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "", "")))


def format_duration(seconds):
    """将秒数格式化为X分Y秒"""
    if seconds < 60:
        return f"{seconds:.2f}秒"
    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes}分{remaining_seconds:.2f}秒"


def generate_summary_report(results, total_duration, output_dir):
    """生成批量执行汇总HTML报告"""
    output_dir = str(output_path(output_dir))
    success_count = sum(1 for r in results if r.get('status') == 'success')
    fail_count = sum(1 for r in results if r.get('status') == 'fail')
    pass_rate = (success_count / len(results) * 100) if len(results) > 0 else 0

    # 生成用例列表HTML
    case_rows = ""
    for idx, case in enumerate(results, 1):
        status_class = "status-pass" if case['status'] == 'success' else "status-fail"
        status_text = "成功" if case['status'] == 'success' else "失败"
        duration = format_duration(case['duration'])
        report_link = f'<a href="{case["report_path"]}" target="_blank" class="report-link">查看报告</a>' if case[
            'report_path'] else '<span class="no-report">无报告</span>'

        error_msg = case.get('error', '')
        if not error_msg:
            error_msg = "无"

        token_usage = case.get('token_usage', '')
        if not token_usage:
            token_usage = "无"

        start_time = case.get('start_time', '')
        if start_time:
            try:
                dt = datetime.fromisoformat(start_time)
                start_time = dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                pass
        else:
            start_time = "无"

        case_rows += f"""
        <tr>
            <td>{idx}</td>
            <td>{case['name']}</td>
            <td>{start_time}</td>
            <td class="task-column">{case.get('task', '')}</td>
            <td><span class="status-badge {status_class}">{status_text}</span></td>
            <td class="reason-column">{error_msg}</td>
            <td class="token-column">{token_usage}</td>
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
            background-color: #4CAF50;
            width: {pass_rate}%;
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
        .task-column {{
            max-width: 300px;
            word-wrap: break-word;
            white-space: pre-wrap;
            font-size: 12px;
            line-height: 1.4;
        }}
        .reason-column {{
            max-width: 400px;
            word-wrap: break-word;
            white-space: pre-wrap;
            font-size: 12px;
            color: #F44336;
            line-height: 1.4;
        }}
        .token-column {{
            max-width: 200px;
            word-wrap: break-word;
            white-space: pre-wrap;
            font-size: 12px;
            color: #2196F3;
            line-height: 1.4;
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
            <div><strong>执行时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
            <div><strong>总耗时:</strong> {format_duration(total_duration)}</div>
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
                    <th>开始时间</th>
                    <th>测试步骤</th>
                    <th>执行状态</th>
                    <th>原因说明</th>
                    <th>Token消耗</th>
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
    with open(output_path(summary_path), "w", encoding="utf-8") as f:
        f.write(html_content)

    print("汇总报告已生成: file://{}".format(os.path.abspath(summary_path).replace('\\', '/')))


def parse_history_reports(history_dir, output_dir=None):
    all_results = []

    if not os.path.exists(history_dir):
        print(f"历史目录不存在: {history_dir}")
        return all_results
    
    for item in os.listdir(history_dir):
        item_path = os.path.join(history_dir, item)
        
        if not os.path.isdir(item_path) or item.startswith('.'):
            continue
        
        json_files = [f for f in os.listdir(item_path) if f.endswith('.json')]
        
        if not json_files:
            continue
        
        json_file = json_files[0]
        json_path = os.path.join(item_path, json_file)
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            test_case_name = data.get('test_case', item)
            test_case_task = data.get('task', '')
            
            start_time_str = data.get('start_time')
            end_time_str = data.get('end_time')
            
            duration = 0
            if start_time_str and end_time_str:
                try:
                    start_time = datetime.fromisoformat(start_time_str)
                    end_time = datetime.fromisoformat(end_time_str)
                    duration = (end_time - start_time).total_seconds()
                except Exception:
                    duration = 0
            
            events = data.get('events', [])
            status = "success"
            error = ""
            
            for event in reversed(events):
                if event.get('event_type') == 'task_end':
                    content = event.get('content', '')
                    normalized_content = content.replace('：', ':')
                    if re.search(r'任务结果[：:]\s*通过', normalized_content):
                        status = "success"
                        error = ""
                    elif re.search(r'任务结果[：:]\s*不通过', normalized_content):
                        status = "fail"
                        reason_match = re.search(r'(原因说明|原因|失败原因|原因分析)[：:](.*)', content, re.DOTALL)
                        if reason_match:
                            error = reason_match.group(2).strip()
                        else:
                            error = content.strip()
                    else:
                        status = "fail"
                        error = "任务结果未知或未完成"
                    break
            
            report_path = ""
            html_files = [f for f in os.listdir(item_path) if f.endswith('.html') and f != 'index.html']
            if html_files:
                html_abs_path = os.path.join(item_path, html_files[0])
                if output_dir:
                    report_path = os.path.relpath(html_abs_path, output_dir).replace('\\', '/')
                else:
                    report_path = html_abs_path
            
            token_usage = ""
            md_files = [f for f in os.listdir(item_path) if f.endswith('.md')]
            if md_files:
                md_path = os.path.join(item_path, md_files[0])
                try:
                    with open(md_path, 'r', encoding='utf-8') as f:
                        md_content = f.read()
                    token_match = re.search(r'\*\*Token消耗\*\*:\s*(.+)', md_content)
                    if token_match:
                        token_usage = token_match.group(1).strip()
                except Exception:
                    pass
            
            all_results.append({
                "name": test_case_name,
                "task": test_case_task,
                "status": status,
                "duration": duration,
                "start_time": start_time_str or "",
                "token_usage": token_usage,
                "report_dir": item_path,
                "report_path": report_path,
                "error": error
            })
            
        except Exception as e:
            print(f"读取报告文件失败 {json_path}: {e}")
            all_results.append({
                "name": item,
                "status": "fail",
                "duration": 0,
                "report_dir": item_path,
                "report_path": "",
                "error": str(e)
            })
    
    all_results.sort(key=lambda x: (x.get('task', ''), x.get('start_time', '')))
    
    return all_results


def main():
    parser = argparse.ArgumentParser(description='Aggregate existing Harmony history reports without executing tests.')
    parser.add_argument('--history-dir', required=True, help='Directory containing per-test report folders')
    parser.add_argument('--output', required=True, help='New directory for index.html')
    parser.add_argument('--root', help='Workflow run root; output must be inside runs/harmony/sandbox')
    args = parser.parse_args()
    history_dir = Path(args.history_dir).resolve()
    if not history_dir.is_dir(): parser.error('--history-dir must exist')
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'migration-ledger/scripts'))
    from runner_storage import harmony_output
    report_dir = harmony_output(args.root, args.output, 'sandbox')
    if report_dir.exists(): parser.error('--output must be a new directory')

    print(f"正在从历史目录读取报告: {history_dir}")

    all_results = parse_history_reports(history_dir, report_dir)
    
    if not all_results:
        print("未找到任何历史报告")
        return
    
    total_duration = sum(r['duration'] for r in all_results)
    
    success_count = sum(1 for r in all_results if r['status'] == 'success')
    fail_count = len(all_results) - success_count
    
    print(f"\n{'=' * 60}")
    print("历史报告汇总")
    print(f"{'=' * 60}")
    print(f"总用例数: {len(all_results)}")
    print(f"成功: {success_count}")
    print(f"失败: {fail_count}")
    print(f"总耗时: {format_duration(total_duration)}")
    print(f"通过率: {(success_count / len(all_results) * 100):.1f}%")
    print(f"{'=' * 60}")
    
    if fail_count > 0:
        print("\n失败用例:")
        for r in all_results:
            if r['status'] == 'fail':
                print(f"  - {r['name']}: {r.get('error', '未知错误')}")

    generate_summary_report(all_results, total_duration, report_dir)
    
    print(f"\n汇总报告已生成到: {report_dir}/index.html")


if __name__ == "__main__":
    main()
