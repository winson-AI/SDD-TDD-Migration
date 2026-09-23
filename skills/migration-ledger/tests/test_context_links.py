"""Follow frozen knowledge links after relocation, source deletion and regeneration."""
import json
from pathlib import Path
import shutil
import unittest

import test_project_context
import test_ledger
from contracts import Rejected, check_ref, file_ref
import context_links as links
import project_context as pc
import openspec_projection as projection


class ContextLinkTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def knowledge(self):
        f=self.f
        guide=f.base/'guide'/'details.md'; guide.parent.mkdir()
        code=f.base/'guide'/'types (v1).kt'; code.write_text('class OriginalType')
        image=f.base/'guide'/'diagram.png'; image.write_bytes(b'fixture image')
        guide.write_text('[back](../architecture.md#root)\n[code](<types (v1).kt#L1>)\n![diagram](diagram.png)\n')
        f.arch.write_text('# Root\n[details](guide/details.md#api "Title")\n[ref][more]\n[more]: guide/details.md#api\n'
                          + '<'+code.as_uri()+'#L1>\n'
                          + '[remote](https://example.test/docs)\n[anchor](#root)\n'
                          + '`[example](missing-inline.md)`\n```md\n[example](missing-fenced.md)\n```\n')
        return guide,code,image

    def test_reproduces_old_hash_copy_breakage_and_freezes_full_link_closure(self):
        f=self.f; guide,code,image=self.knowledge()
        old=pc.archive(f.base/'old-files',f.arch.read_bytes(),'.md')
        self.assertFalse((Path(old['path']).parent/'guide/details.md').exists())
        result=f.prepare(); ref=result['input']['new_architecture']
        manifest=links.verify(ref['link_manifest_ref'])
        entries={e['source_path']:e for e in manifest['entries']}
        self.assertEqual(set(entries),{str(f.arch),str(guide),str(code),str(image)})
        self.assertFalse(manifest['warnings'])
        frozen=check_ref(ref).read_text()
        self.assertIn(entries[str(guide)]['readable_ref']['path']+'#api "Title"',frozen)
        self.assertIn('https://example.test/docs',frozen); self.assertIn('[anchor](#root)',frozen)
        self.assertIn('`[example](missing-inline.md)`',frozen)
        self.assertIn('[example](missing-fenced.md)',frozen)
        child=check_ref(entries[str(guide)]['readable_ref']).read_text()
        self.assertIn(ref['path']+'#root',child)
        # Raw originals keep their original content hash; every rewritten view has its own hash.
        self.assertEqual(check_ref(entries[str(f.arch)]['original_ref']).read_bytes(),f.arch.read_bytes())
        self.assertNotEqual(ref['sha256'],entries[str(f.arch)]['original_ref']['sha256'])
        f.arch.unlink(); shutil.rmtree(guide.parent)
        pc.verify_snapshot(result['project_context_ref'])
        for e in entries.values():
            check_ref(e['original_ref']); check_ref(e['readable_ref'])

    def test_linked_code_changes_only_affect_new_run_and_snapshot_tampering_is_rejected(self):
        f=self.f; _,code,_=self.knowledge()
        first=f.prepare(); old_ref=first['input']['new_architecture']
        old=links.verify(old_ref['link_manifest_ref'])
        original_code=next(e for e in old['entries'] if e['source_path']==str(code))['readable_ref']
        code.write_text('class NewType')
        self.assertTrue(f.prepare()['duplicate'])
        second=pc.prepare(f.root,f.base/'.sdd-runs/r2',f.run_request('r2'),f.actor)
        self.assertNotEqual(old_ref['path'],second['input']['new_architecture']['path'])
        self.assertEqual(check_ref(original_code).read_text(),'class OriginalType')
        pc.verify_snapshot(first['project_context_ref'])
        Path(original_code['path']).write_text('tampered')
        with self.assertRaises(Rejected): pc.verify_snapshot(first['project_context_ref'])

    def test_missing_targets_surface_and_external_urls_are_not_fetched(self):
        f=self.f
        f.arch.write_text('[missing](not-created.md)\n[remote](https://example.test/no-fetch)')
        result=f.prepare(); warnings=result['input']['document_link_warnings']
        self.assertEqual([w['reason'] for w in warnings],['missing-local-target'])
        self.assertIn(str(f.base/'not-created.md'),check_ref(result['input']['new_architecture']).read_text())

    def test_plain_override_mapping_uses_actual_input_not_project_default(self):
        f=self.f; alternative=f.base/'alternative.md'; alternative.write_text('override architecture')
        result=f.prepare(overrides={'architecture_path':str(alternative)})
        mapping,_=links.mapping(pc.verify_snapshot(result['project_context_ref']))
        self.assertEqual(mapping[str(alternative)],result['input']['new_architecture']['path'])
        self.assertNotIn(str(f.arch),mapping)

    def test_openspec_links_follow_context_hash_and_relocated_spec_design(self):
        f=self.f; self.knowledge(); prepared=f.prepare()
        flow=test_ledger.FlowTests(); flow.setUp(); self.addCleanup(flow.doCleanups)
        flow.global_plan(); plan=flow.plan()
        for ref in plan['definitions']:
            if ref['kind']=='spec':
                p=Path(ref['path']); p.write_text(p.read_text()+f'\n[design](design.md#decision)\n[architecture]({f.arch})\n')
                ref.update(file_ref(p))
            elif ref['kind']=='design':
                p=Path(ref['path']); p.write_text(p.read_text()+'\n[spec](spec.md#requirement-r1)\n')
                ref.update(file_ref(p))
        flow.call('plan',{'plan_ref':flow.ref('plan-with-links.json',plan)},role='spec-designer')
        state=flow.state(); state['project_context_ref']=prepared['project_context_ref']
        state['run_id']='r1'
        shutil.copytree(flow.root/'artifacts', f.run/'artifacts')
        projection.materialize(f.run,state,state['last_sequence'])
        change=f.base/'openspec/changes/r1-m001'
        spec=change/'specs/m001/spec.md'
        self.assertIn(str(change/'design.md')+'#decision',spec.read_text())
        self.assertIn(prepared['input']['new_architecture']['path'],spec.read_text())
        self.assertIn(str(spec)+'#requirement-r1',(change/'design.md').read_text())
        self.assertFalse(json.loads((change/'manifest.json').read_text())['link_warnings'])
        # Rebuild from sealed context and raw definition artifacts, after deleting live originals.
        f.arch.unlink(); shutil.rmtree(f.base/'guide'); shutil.rmtree(flow.base/'defs'); shutil.rmtree(change)
        projection.materialize(f.run,state,state['last_sequence'])
        self.assertIn(prepared['input']['new_architecture']['path'],spec.read_text())
