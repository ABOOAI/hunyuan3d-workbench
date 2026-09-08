import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from playwright.sync_api import sync_playwright
from hunyuan_workbench import Workbench, inspect_asset
from browser_worker import BrowserFlow
import test_workbench as ledger_fixtures
from features import validate, prepare_feature
import lifecycle as lc

class FeatureTests(unittest.TestCase):
    setUp=ledger_fixtures.LedgerTests.setUp
    tearDown=ledger_fixtures.LedgerTests.tearDown
    def test_spec_rejects_unknown_or_silently_ignored_modes(self):
        for spec in [dict(feature='world',name='no'),dict(feature='texture',name='no',mode='text',prompt='a'),
                     dict(feature='concept',name='no',prompt='x'*151),dict(feature='concept',name='no',unexpected=True)]:
            with self.assertRaises(ValueError): validate(spec)
    def test_feature_prepare_persists_and_deduplicates(self):
        spec=dict(feature='concept',name='Character ref',mode='multiview',image=self.views['front'])
        a=prepare_feature(self.core,spec);b=prepare_feature(self.core,spec)
        self.assertEqual(a['id'],b['id']);self.assertTrue(Path(a['views']['front']['path']).exists())
    def test_fbx_html_error_page_rejected(self):
        p=self.root/'model.fbx';p.write_text('<html>expired</html>')
        with self.assertRaises(ValueError): inspect_asset(p)
    def test_archive_path_traversal_rejected(self):
        import zipfile
        p=self.root/'output.zip'
        with zipfile.ZipFile(p,'w') as z:z.writestr('../bad.txt','x')
        with self.assertRaises(ValueError): inspect_asset(p)

    def test_first_download_creates_its_own_metadata_directory(self):
        from studio_adapter import download_current
        self.assertFalse((self.core.root / 'research').exists())
        page = MagicMock()
        def export_item(label, **kwargs):
            item = MagicMock()
            item.is_visible.return_value = label == 'fbx'
            return item
        page.get_by_text.side_effect = export_item
        download = MagicMock()
        download.url = 'blob:https://3d.hunyuan.tencent.com/offline-fixture'
        download.suggested_filename = 'fixture.fbx'
        download.failure.return_value = None
        download.save_as.side_effect = lambda path: path.write_bytes(b'Kaydara FBX Binary  \x00\x1a\x00')
        page.expect_download.return_value.__enter__.return_value.value = download
        flow = SimpleNamespace(core=self.core, page=page, guard=lambda: None, status=lambda *args: None)
        result = download_current(flow, 'fbx')
        self.assertTrue(Path(result['path']).is_file())
        record = json.loads((self.core.root / 'research' / 'last-download-kind.json').read_text(encoding='utf-8'))
        self.assertEqual(record, {'scheme': 'blob', 'format': 'fbx'})

    def test_probe_requires_an_explicit_valid_glb(self):
        from studio_adapter import probe_model_path
        for value in (None, True, ''):
            with self.assertRaisesRegex(ValueError, 'explicit GLB'):
                probe_model_path(value)
        model = ledger_fixtures.LedgerTests.glb(self)
        self.assertEqual(probe_model_path(str(model)), model.resolve())
        with self.assertRaises(ValueError):
            probe_model_path(self.views['front'])

class StudioLifecycleTests(unittest.TestCase):
    setUp=ledger_fixtures.LedgerTests.setUp
    tearDown=ledger_fixtures.LedgerTests.tearDown
    prepare=ledger_fixtures.LedgerTests.prepare
    ready=ledger_fixtures.LedgerTests.ready
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(channel='chrome',headless=True,chromium_sandbox=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def page(self,html):
        context=self.browser.new_context()
        context.route('**/*',lambda r:r.fulfill(content_type='text/html',body='<meta charset="utf-8">'+html))
        self.addCleanup(context.close)
        page=context.new_page();page.goto('https://3d.hunyuan.tencent.com/studio/creation/geo')
        return page
    def test_new_card_identity_loading_not_success_and_restart_recovery(self):
        job=self.ready();jid=job['id']
        page=self.page('''<div id="assets-container"><div><img src="https://example.test/old.png"></div></div>
<button type="button" onclick="let e=document.createElement('div');e.id='new';e.innerHTML='<span class=bg-gradient-to-r></span><img src=https://cdn-game-3d.qstatic.com/game3d/assets/icon-loading.webp>';document.querySelector('#assets-container').prepend(e);">立即生成</button><button>下载</button>''')
        flow=BrowserFlow(page,self.core)
        before=page.locator(lc.CARD).element_handles()
        self.core.transition(jid,'SUBMITTING','fixture')
        page.get_by_text('立即生成',exact=True).click()
        result=lc.retain_new_card(flow,jid,before,timeout=1000)
        self.assertEqual(result['state'],'RUNNING')
        self.assertNotIn('thumbnail',lc.read_binding(flow,jid))
        page.locator('#new img').evaluate("e=>e.src='https://example.test/new.png'")
        self.assertEqual(lc.tick(flow,jid)['state'],'SUCCEEDED')
        fresh_flow=BrowserFlow(page,Workbench(self.core.root))
        handle,binding=lc.resolve_card(fresh_flow,jid)
        self.assertEqual(binding['thumbnail'],'https://example.test/new.png')
        self.assertEqual(handle.get_attribute('id'),'new')
        page.locator('#new').evaluate('e=>e.remove()')
        with self.assertRaisesRegex(ValueError,'TASK_IDENTITY_REQUIRED'):lc.resolve_card(fresh_flow,jid)
    def test_monitor_records_failure_without_resubmission(self):
        job=self.ready();jid=job['id']
        for s in ['SUBMITTING','SUBMITTED','RUNNING']:self.core.transition(jid,s,'fixture')
        page=self.page('<div id="assets-container"><div>生成失败</div></div>')
        flow=BrowserFlow(page,self.core);flow.task_handles={jid:page.locator(lc.CARD).element_handle()}
        lc.watch_config(flow,jid,interval=5)
        lc.watch_tick(flow)
        self.assertEqual(self.core.get(jid)['state'],'FAILED')
        saved=json.loads((self.core.root/'watches'/(jid+'.json')).read_text(encoding='utf-8'))
        self.assertFalse(saved['enabled'])
    def test_pending_restart_does_not_guess_the_only_card(self):
        job=self.ready();jid=job['id']
        for s in ['SUBMITTING','SUBMITTED','RUNNING']:self.core.transition(jid,s,'fixture')
        page=self.page('<div id="assets-container"><div>排队中</div></div>')
        flow=BrowserFlow(page,self.core);lc.save_binding(flow,jid,{'kind':'live-dom-element'})
        lc.watch_config(flow,jid,interval=5);lc.watch_tick(flow)
        saved=json.loads((self.core.root/'watches'/(jid+'.json')).read_text(encoding='utf-8'))
        self.assertTrue(saved['attention_required']);self.assertFalse(saved['enabled'])
        self.assertEqual(self.core.get(jid)['state'],'RUNNING')
    def test_disabled_pseudo_button_cannot_submit(self):
        from feature_adapter import generation_control
        page=self.page('<div type="button" disabled class="t-is-disabled"><span>立即生成</span></div>')
        with self.assertRaises(ValueError):generation_control(page,'concept')

    def test_changed_custom_face_option_changes_signature(self):
        from feature_adapter import form_signature
        page=self.page('<div id="face" class="selected">50k</div><textarea>jar</textarea>')
        before=form_signature(page)
        page.locator('#face').evaluate("e=>e.className=''")
        self.assertNotEqual(before,form_signature(page))

    def test_cached_download_rechecks_its_hash(self):
        job=self.ready();jid=job['id']
        for s in ['SUBMITTING','SUBMITTED','SUCCEEDED']:self.core.transition(jid,s,'fixture')
        source=ledger_fixtures.LedgerTests.glb(self)
        report=self.core.ingest(jid,str(source))
        Path(report['path']).write_bytes(b'changed after archival')
        with self.assertRaisesRegex(ValueError,'missing or changed'):
            lc.download_job(BrowserFlow(None,self.core),jid)

if __name__=='__main__':unittest.main(verbosity=2)
