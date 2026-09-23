"""Frozen path -> native task; native observations -> evidence-backed SDD results.

No model/device dependencies. Never infer an assertion from a final task sentence.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime/harmony'))
from AutoTest.storage import output_path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def ref(path):
    p = Path(path).resolve()
    return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def write(path, value):
    output_path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def validate_query(q):
    for key in ('run_id', 'module_id', 'path_id', 'name', 'freeze_id', 'code_baseline'):
        if not q.get(key):
            raise ValueError(f'missing frozen query {key}')
    assertions = q.get('expected_assertions', [])
    if not assertions or not q.get('steps'):
        raise ValueError('steps and nonempty assertions required')
    ids = set()
    for a in assertions:
        aid = a.get('assertion_id', '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', aid) or aid in ids:
            raise ValueError('unique assertion IDs required')
        ids.add(aid)
        if a.get('expected') is not True or not a.get('description'):
            raise ValueError('Harmony predicate requires frozen expected=true and description; request SPEC change for other observations')
        if a.get('verification') not in ('one_image_assert', 'multi_image_assert', 'cross_step_image_assert', 'refer_image_assert', 'video_assert', 'auto'):
            raise ValueError('explicit frozen verification mode required')
        if a.get('matcher') not in ('exact', 'semantic'):
            raise ValueError('explicit frozen exact/semantic matcher required')
        step = a.get('after_step')
        if type(step) is not int or not 1 <= step <= len(q['steps']):
            raise ValueError('assertion after_step must reference a frozen step')
    return q


def task_text(q):
    validate_query(q)
    lines = [f"PATH {q['path_id']} / {q['name']}",
             '执行下列冻结测试数据，不得从实现或最终任务文本推导通过；每个断言单独调用 verify，保留 [ASSERT:id]。',
             '前置条件：' + json.dumps(q.get('preconditions', []), ensure_ascii=False),
             '参数：' + json.dumps(q.get('parameters', {}), ensure_ascii=False),
             '依赖引用：' + json.dumps(q.get('dependency_refs', []), ensure_ascii=False)]
    for i, step in enumerate(q['steps'], 1):
        lines.append(f'步骤 {i}: ' + (step if isinstance(step, str) else json.dumps(step, ensure_ascii=False)))
        for a in q['expected_assertions']:
            if a['after_step'] == i:
                lines.append(f"预期结果：verify('[ASSERT:{a['assertion_id']}] {a['description']}')；匹配={a['matcher']}；验证方式={a['verification']}")
    return '\n'.join(lines)


class ObservationSink:
    def __init__(self, query, output):
        self.query, self.output = query, Path(output)
        self.observations = []
        self.error = None
        self.final_output = None

    def record(self, description, result, reason, tool, evidence, error=None):
        ids = re.findall(r'\[ASSERT:([A-Za-z0-9_.-]+)\]', description)
        event = {'sequence': len(self.observations) + 1, 'assertion_ids': ids,
                 'description': description, 'result': result, 'reason': reason,
                 'tool': tool, 'evidence_refs': [], 'error': error}
        for p in evidence:
            try:
                event['evidence_refs'].append(ref(p))
            except OSError:
                event['error'] = 'missing verification media'
        self.observations.append(event)
        # Flush every observation so a timeout cannot erase earlier failures.
        write(self.output / 'observations.json', self.observations)
        return event

    def report(self):
        write(self.output / 'observations.json', self.observations)
        raw_ref = ref(self.output / 'observations.json')
        expected = {a['assertion_id']: a for a in self.query['expected_assertions']}
        rows, blocked, failed, flaky = [], [], [], False
        if self.error:
            blocked.append(self.error)
        for event in self.observations:
            if len(event['assertion_ids']) != 1 or event['assertion_ids'][0] not in expected:
                blocked.append('unknown or combined assertion identity')
        for aid, a in expected.items():
            events = [e for e in self.observations if e['assertion_ids'] == [aid]]
            valid = [e for e in events if not e['error'] and e['evidence_refs'] and type(e['result']) is bool
                     and (a['verification'] == 'auto' or a['verification'] == e['tool'])]
            for e in valid[:]:
                try:
                    if any(ref(r['path']) != r for r in e['evidence_refs']): valid.remove(e)
                except OSError:
                    valid.remove(e)
            if not valid or len(valid) != len(events): blocked.append(f'{aid}: missing/invalid observation or media')
            values = {e['result'] for e in valid}
            if len(values) > 1:
                flaky = True
                blocked.append(f'{aid}: mixed pass/fail; preserve all attempts')
            passed = bool(valid) and len(valid) == len(events) and values == {True}
            if False in values: failed.append(aid)
            rows.append({'assertion_id': aid, 'expected': a['expected'],
                         'actual': True if passed else (False if False in values else None),
                         'passed': passed, 'evidence_ref': raw_ref})
        quality = 'yellow-blocked' if blocked else ('red-bug' if failed else 'green-passed')
        cause = None
        if quality != 'green-passed':
            cause = {'category': 'flaky' if flaky else ('tooling' if blocked else 'behavior'),
                     'summary': '; '.join(blocked + ([f'Failed frozen assertions: {failed}'] if failed else [])),
                     'confidence': 'observed' if not blocked else 'suspected',
                     'owner': self.query['module_id'], 'suspected_owner': self.query['module_id'],
                     'evidence_refs': [raw_ref], 'next_action': 'diagnose'}
        return {'schema_version': 1, 'producer': 'harmony-adapter',
                **{k:self.query[k] for k in ('run_id','module_id','path_id','freeze_id','code_baseline')},
                'query_sha256': digest(self.query), 'quality': quality, 'flaky': flaky,
                'assertions': rows, 'root_cause': cause, 'observations_ref': raw_ref,
                'final_output': self.final_output, 'skipped': False}
