#!/usr/bin/env python3
"""Import MD/XMind into reviewable test candidates. Does not freeze or run a device."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
from harmony_contract import digest, ref, write
from harmony_adapter import ENGINE, resolve_env
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-ledger/scripts'))
from runner_storage import harmony_output, scope


def draft(markdown, module_id, source_ref):
    paths = []
    blocks = re.split(r'^## 用例描述[：:]\s*', markdown, flags=re.M)[1:]
    for block in blocks:
        name, _, body = block.partition('\n')
        # Keep original body verbatim: semantic splitting is the Test Designer's job.
        key = digest({'source':source_ref, 'name':name, 'body':body})[:12]
        paths.append({'path_id':f'PATH-{module_id}-{key}', 'name':name.strip(),
                      'case_id':f'CASE-{module_id}-{key}', 'requirement_id':None,
                      'source_ref':source_ref, 'original_case':body.strip(),
                      'required':True, 'scope':'module', 'preconditions':[], 'steps':[],
                      'parameters':{}, 'expected_assertions':[],
                      'review_required':['map original case ID and requirement ID',
                                         'split parameterized paths without dropping cases',
                                         'extract ordered steps and per-assertion after_step',
                                         'freeze description/expected=true/matcher/verification']})
    if not paths: raise ValueError('no standard test cases; preserve input and request design clarification')
    return {'schema_version':1, 'module_id':module_id, 'status':'draft-not-executable',
            'source_ref':source_ref, 'paths':paths}


async def convert(source, output, config, app_name):
    from AutoTest.storage import output_path
    output = output_path(output)
    sys.path.insert(0, str(ENGINE))
    from AutoTest.testcase_preprocessor.xmind_parser import extract_tree
    from AutoTest.testcase_preprocessor.converter import convert_tree_to_md
    from AutoTest.config import AppConfig
    from agents import set_tracing_disabled
    set_tracing_disabled(True)
    # Importing cases must not require unrelated device/executor credentials.
    key = 'xmind_convert_models' if config.get('xmind_convert_models') else 'decision_models'
    data = {key: resolve_env(config.get(key, []))}
    cfg = AppConfig(decision_models=data.get('decision_models',[]), xmind_convert_models=data.get('xmind_convert_models',[]))
    text = extract_tree(str(source))
    (output / 'xmind-tree.txt').write_text(text)
    md = await convert_tree_to_md(str(ENGINE), text, cfg, app_name=app_name)
    (output / 'converted.md').write_text(md)
    return md


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('input','module','output'): p.add_argument('--'+key, required=True)
    p.add_argument('--config'); p.add_argument('--app-name')
    p.add_argument('--root', help='Workflow run root; output must be inside runs/harmony/sandbox')
    args = p.parse_args()
    source = Path(args.input).resolve()
    out = harmony_output(args.root, args.output, 'sandbox')
    out.mkdir(parents=True, exist_ok=False)
    if source.suffix.lower() == '.xmind':
        from harmony_environment import prepare_environment, load_environment
        run_root = next(x for x in out.parents if x.parent.name == '.sdd-runs')
        config_path, env_path = prepare_environment(run_root, args.config)
        load_environment(env_path)
        with scope(out / 'runtime'):
            md = asyncio.run(convert(source,out,json.loads(config_path.read_text())['models'],args.app_name))
    else: md = source.read_text()
    result = draft(md,args.module,ref(source))
    (out/'source.md').write_text(md)
    result['normalized_source_ref'] = ref(out/'source.md')
    write(out/'test-design-draft.json',result)
