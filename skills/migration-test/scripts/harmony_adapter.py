#!/usr/bin/env python3
"""Main adapter. Invoke ONLY through execute_test.py after Ledger authorization."""
import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace

from harmony_contract import ObservationSink, digest, ref, task_text, validate_query, write

ENGINE = Path(__file__).resolve().parents[1] / 'runtime/harmony'


def resolve_env(value):
    if isinstance(value, dict):
        if set(value) == {'env'}:
            names = value['env']
            names = [names] if isinstance(names, str) else names
            if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
                raise ValueError('environment reference requires a name or nonempty name list')
            for name in names:
                if os.environ.get(name): return os.environ[name]
            raise ValueError('missing environment variable: ' + ' / '.join(names))
        return {k:resolve_env(v) for k,v in value.items()}
    if isinstance(value, list): return [resolve_env(v) for v in value]
    return value


def public_config(value):
    if isinstance(value, dict):
        return {k:(v if isinstance(v, dict) and set(v) == {'env'} else '[redacted]')
                if k in ('api_key', 'execute_api_key', 'verify_api_key', 'decision_api_key', 'password', 'token')
                else public_config(v) for k,v in value.items()}
    if isinstance(value, list): return [public_config(v) for v in value]
    return value


@contextmanager
def device_lock(device, ip, port):
    key = digest([device, ip, port])
    path = Path(tempfile.gettempdir()) / f'sdd-harmony-device-{key}.lock'
    with path.open('a') as f:
        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('device busy: another test owns the device lease')
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)


def configure(raw):
    from dataclasses import fields
    from AutoTest.config import AppConfig, ContextCompressionConfig, ReflectionConfig, SpecialTestConfig, config_manager
    # XMind import is a separate operation; UI execution needs no converter key.
    data = resolve_env({k: v for k, v in raw.items() if k != 'xmind_convert_models'})
    allowed = {f.name for f in fields(AppConfig)}
    if set(data) - allowed: raise ValueError('unknown AppConfig keys: ' + str(sorted(set(data) - allowed)))
    for key, typ in [('context_compression', ContextCompressionConfig), ('reflection', ReflectionConfig), ('special_test', SpecialTestConfig)]:
        if key in data: data[key] = typ(**data[key])
    cfg = AppConfig(**data)
    if not cfg.decision_models or not cfg.execute_model_name or not cfg.verify_model_name:
        raise ValueError('planner, executor and verify model configurations required')
    if cfg.execute_provider not in ('general', 'glm', 'mcp_agent', 'hypium_mcp_agent'):
        raise ValueError('explicit supported execute_provider required; no silent fallback')
    # Original factories use both the model list and first-model convenience fields.
    first = cfg.decision_models[0]
    for target, source in [('decision_model_name','name'),('decision_base_url','base_url'),('decision_api_key','api_key')]:
        setattr(cfg, target, first.get(source, ''))
    cfg.keep_raw_video = True  # preserve evidence used by earlier video assertions
    config_manager._config = cfg
    return cfg


def observing_verifier(base, sink):
    class Verified(base):
        def verify(self, description):
            ids = re.findall(r'\[ASSERT:([A-Za-z0-9_.-]+)\]', description)
            definitions = {a['assertion_id']:a for a in sink.query['expected_assertions']}
            if len(ids) != 1 or ids[0] not in definitions:
                sink.record(description, None, 'unbound assertion', '', [], 'unknown assertion ID')
                return False, '必须使用一个冻结 ASSERT ID'
            a = definitions[ids[0]]
            frozen = f"[ASSERT:{ids[0]}] {a['description']}\n匹配规则：{a['matcher']}；exact 必须精确匹配，semantic 仅按冻结描述的语义判断。"
            try:
                # Retain original selector, timeline lookup, media handling and model calls.
                result, reason, tool, media = self._verify(frozen)
                error = None
                if not media or type(result) is not bool: error = 'verification unavailable'
                if re.search(r'调用失败|执行异常|无法解析|没有视频|无法获取|无法加载|Error:|超时|Video verification failed|Video file|end_time must', reason, re.I):
                    error = 'verification infrastructure/parse failure'
                if a['verification'] != 'auto' and tool != a['verification']:
                    error = 'selected verification mode differs from frozen mode'
                sink.record(description, result, reason, tool, media, error)
                return result if not error else False, reason
            except Exception as exc:
                sink.record(description, None, str(exc), '', [], 'verification exception')
                return False, 'verification exception; inspect observations'

        def _select_tool_and_steps(self, description):
            selected = super()._select_tool_and_steps(description)
            ids = re.findall(r'\[ASSERT:([A-Za-z0-9_.-]+)\]', description)
            a = next(a for a in sink.query['expected_assertions'] if a['assertion_id'] == ids[0])
            if a['verification'] != 'auto': selected['tool'] = a['verification']
            return selected
    return Verified


async def run_engine(q, config, out, sink):
    sys.path.insert(0, str(ENGINE))
    from AutoTest.logger import configure_logger
    cfg = configure(config['models'])
    if any(a['verification'] == 'video_assert' for a in q['expected_assertions']) and not cfg.verify_video_enable:
        raise ValueError('frozen video assertion requires verify_video_enable')
    configure_logger(log_file=str(out / 'engine.log'))
    spec = importlib.util.spec_from_file_location('sdd_harmony_main', ENGINE / 'main.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    native.VerifyAgent = observing_verifier(native.VerifyAgent, sink)
    from AutoTest.layered_agent_cli import planner_agent
    planner_agent.PLANNER_INSTRUCTIONS += '\nSDD 冻结断言优先于通用文案匹配规则。每个 verify 必须包含单个 [ASSERT:id]，按路径指定时机执行，禁止把几个预期合并。'
    task = task_text(q)
    from AutoTest.layered_agent_cli.agent_registry import agent_registry
    knowledge = config.get('knowledge_ref')
    if knowledge:
        if ref(knowledge['path']) != knowledge: raise ValueError('knowledge digest changed')
        knowledge_text = Path(knowledge['path']).read_text()
        agent_registry.set_knowledge(knowledge_text)
        # Original batch entry attaches knowledge to task text for planner visibility.
        task += '\n知识库：\n（仅辅助执行，不得修改冻结步骤或断言）\n' + knowledge_text
    # Fresh process/workdir per path isolates global registries and default memory writes.
    args = SimpleNamespace(task=task, task_name=q['path_id'] + ' ' + q['name'],
                           report_dir=str(out / 'reports'), device=config['device'],
                           ip=config.get('ip','127.0.0.1'), port=config.get('port',8710),
                           memory_dir=str(out / 'memory'))
    Path(args.memory_dir).mkdir()
    replay = config.get('recording_ref')
    if replay:
        if ref(replay['path']) != replay: raise ValueError('recording digest changed')
        meta = json.loads(Path(replay['path']).read_text())
        # Cross-baseline recordings are navigation hints; every verify is rerun live.
        if meta.get('task') != task: raise ValueError('recording belongs to a different frozen path')
        shutil.copyfile(replay['path'], Path(args.memory_dir) / (hashlib.md5(task.encode()).hexdigest()[:16] + '.json'))
    return await (native.playback_cli(args, cfg) if replay else native.decision_cli(args, cfg))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('query-file','result-file','config'): p.add_argument('--' + key, required=True)
    p.add_argument('--device', help='Explicit Harmony serial; overrides config and HARMONY_DEVICE')
    a = p.parse_args()
    q = json.loads(Path(a.query_file).read_text())
    result_path = Path(a.result_file).resolve()
    out = result_path.parent / 'harmony'
    out.mkdir(exist_ok=False)
    sink = ObservationSink(q, out)
    environment = {'python':sys.version, 'engine_snapshot_ref':ref(ENGINE / 'UPSTREAM.json')}
    try:
        validate_query(q)
        config = json.loads(Path(a.config).read_text())
        config['device'] = a.device or config.get('device') or os.environ.get('HARMONY_DEVICE', '')
        environment.update({'config_ref':ref(a.config), 'device':config.get('device'),
                            'ip':config.get('ip','127.0.0.1'), 'port':config.get('port',8710),
                            'recording_ref':config.get('recording_ref'), 'knowledge_ref':config.get('knowledge_ref')})
        environment['configuration'] = public_config(config)
        environment['packages'] = {}
        for name in ('openai','openai-agents','hypium','hypium-mcp','opencv-python','imageio-ffmpeg'):
            try: environment['packages'][name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError: environment['packages'][name] = None
        if not config.get('device'): raise ValueError('explicit device serial required')
        # Native relative media/memory files are contained in the attempt directory.
        old_cwd = Path.cwd()
        with device_lock(config['device'], config.get('ip','127.0.0.1'), config.get('port',8710)):
            try:
                os.chdir(out)
                sink.final_output = asyncio.run(run_engine(q, config, out, sink))
                if not sink.final_output or str(sink.final_output).startswith('Error:'):
                    sink.error = 'engine stopped without a complete run; inspect engine.log'
            finally: os.chdir(old_cwd)
    except Exception as exc:
        # Do not copy model exception text (may include credentials) into public receipts.
        detail = str(exc) if isinstance(exc, (ImportError, FileNotFoundError)) else 'engine unavailable or invalid configuration; inspect host environment'
        # Our own validation messages carry useful context and no resolved secret values.
        if isinstance(exc, ValueError) and ('required' in str(exc) or 'missing' in str(exc) or 'device busy' in str(exc)):
            detail = str(exc)
        sink.error = f'{type(exc).__name__}: {detail}'
    report = sink.report()
    write(out / 'environment.json', environment)
    report['environment_hash'] = digest(environment)
    report['environment_ref'] = ref(out / 'environment.json')
    report['artifacts'] = [ref(f) for f in sorted(out.rglob('*')) if f.is_file()]
    report['engine_snapshot_ref'] = ref(ENGINE / 'UPSTREAM.json')
    write(result_path, report)
    return 0 if report['quality'] == 'green-passed' else (1 if report['quality'] == 'red-bug' else 2)


if __name__ == '__main__':
    sys.exit(main())
