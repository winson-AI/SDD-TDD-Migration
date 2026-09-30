"""Read-only Lean knowledge operations; managed caller owns every generated artifact."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path

from contracts import check_ref, file_ref, read_json, require
from lean_tools import foundation_gate, query_knowledge


def captured(function, *args, **kwargs):
    stream = StringIO()
    with redirect_stdout(stream):
        function(*args, **kwargs)
    return json.loads(stream.getvalue())


def knowledge_ref(path):
    path = Path(path).resolve()
    require(path.is_relative_to(query_knowledge.SKILL_ROOT.resolve()), 'knowledge reference escapes bundle')
    return file_ref(path)


def references(paths):
    return [knowledge_ref(path) for path in dict.fromkeys(str(p) for p in paths)]


def text(value, name):
    require(isinstance(value, str) and value.strip(), name + ' must be a nonempty string')
    return value


def run(operation, args, config, root):
    index = query_knowledge._load_json(query_knowledge.INDEX_PATH)
    adaptation = query_knowledge._resolve_relative('references/sdd-adaptation.md')
    refs = [query_knowledge.INDEX_PATH, adaptation]
    common = {'schema_version': 1, 'producer': 'lean-knowledge',
              'authority': 'bundled advisory snapshot; source, installed SDK and executed evidence remain authoritative',
              'sdd_adaptation_ref': knowledge_ref(adaptation)}
    if operation == 'knowledge-query':
        mode = args.get('mode')
        require(mode in ('topics', 'topic', 'foundation', 'external'),
                'knowledge mode must be topics, topic, foundation or external')
        if mode == 'topics':
            result = {'topics': query_knowledge._entries(index)}
        elif mode == 'topic':
            topic = query_knowledge._topic(index, text(args.get('topic_id'), 'topic_id'))
            path = query_knowledge._resolve_relative(topic['path'])
            refs.append(path)
            result = {'topic': topic, 'content': path.read_text(encoding='utf-8')}
        elif mode == 'external':
            result = captured(query_knowledge._external, index, text(args.get('query'), 'query'))
            refs.append(result['catalog'])
            for item in result['matches']:
                refs.extend([item['record_path'], item['cookbook_path']])
            result.update(status='candidates-found' if result['matches'] else 'no-match',
                          verification='catalog-discovery-only; probes and installation are not executed')
        else:
            require(type(args.get('full', False)) is bool, 'full must be boolean')
            result = captured(query_knowledge._foundation, index, text(args.get('query'), 'query'), full=args.get('full', False))
            refs.extend([result['catalog'], *result['matching_cookbooks']])
            refs.extend(Path(result['catalog']).parent / item['evidence_file']
                        for item in result['matches'] if item.get('evidence_file'))
        result['mode'] = mode
    elif operation == 'knowledge-diagnose':
        error = check_ref(args.get('error_ref'))
        result = captured(query_knowledge._diagnose, index, text(error.read_text(encoding='utf-8'), 'error log'))
        refs.append(result['catalog'])
        for match in result['matches']:
            refs.extend(match['cookbook_paths'] + match['topic_paths'])
        result.update(error_ref=args['error_ref'], status='candidates-found' if result['matches'] else 'no-match',
                      interpretation='pattern matches are diagnostic candidates, not a root-cause verdict')
    elif operation == 'foundation-resolve':
        requirements = args.get('requirements', [])
        require(isinstance(requirements, list) and all(isinstance(q, str) and q.strip() for q in requirements),
                'requirements must be a list of nonempty strings')
        require(type(args.get('no_new_dependencies', False)) is bool, 'no_new_dependencies must be boolean')
        result = foundation_gate.resolve(Path(config['target_root']), requirements, args.get('no_new_dependencies', False))
        catalog = Path(result['catalog'])
        refs.append(catalog)
        for item in result['requirements']:
            for key in ('cookbook', 'evidence_file'):
                if item.get(key): refs.append(catalog.parent / item[key])
        result['verification'] = 'catalog-resolution-only; build and runtime remain unverified'
    elif operation == 'foundation-verify':
        resolution = check_ref(args.get('resolution_ref')).resolve()
        require(resolution.is_relative_to(Path(root).resolve()), 'resolution must belong to this run')
        catalog = check_ref(args.get('catalog_ref')).resolve()
        # This reads the actual target TOML, never an archived substitute or an arbitrary project.
        require(catalog.is_relative_to(Path(config['target_root']).resolve()), 'version catalog must stay inside target root')
        from knowledge_gate import validate_resolution
        resolved = validate_resolution(args['resolution_ref'])
        require(resolved.get('producer') == 'lean-knowledge', 'managed Foundation resolution required')
        result = foundation_gate.verify(Path(config['target_root']), resolution, catalog)
        result.update(resolution_ref=args['resolution_ref'], catalog_ref=args['catalog_ref'],
                      verification='version-catalog-only; build and runtime remain unverified')
    else:
        raise ValueError('unsupported knowledge operation')
    return {**common, **result, 'knowledge_refs': references(refs)}
