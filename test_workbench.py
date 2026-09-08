import concurrent.futures
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from hunyuan_workbench import Workbench, default_state_root, digest, inspect_glb


class StateLocationTests(unittest.TestCase):
    def test_windows_default_uses_user_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            with patch('hunyuan_workbench.sys.platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': str(base)}, clear=True):
                core = Workbench()
                self.assertEqual(core.root, (base / 'hunyuan-workbench').resolve())
                self.assertTrue(core.db.is_file())

    def test_environment_root_is_read_at_construction(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('first', 'second'):
                expected = Path(folder) / name
                with patch.dict(os.environ, {'HUNYUAN_WORKBENCH_ROOT': str(expected)}):
                    self.assertEqual(Workbench().root, expected.resolve())

    def test_explicit_root_takes_precedence_and_expands_home(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            with patch.dict(os.environ, {'HUNYUAN_WORKBENCH_ROOT': str(base / 'unused')}), patch('pathlib.Path.expanduser', return_value=base / 'explicit'):
                self.assertEqual(Workbench('~/explicit').root, (base / 'explicit').resolve())
                self.assertFalse((base / 'unused').exists())

    def test_empty_override_uses_default_and_platform_fallbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for platform, suffix in (
                ('win32', Path('AppData') / 'Local'),
                ('darwin', Path('Library') / 'Application Support'),
                ('linux', Path('.local') / 'share'),
            ):
                with self.subTest(platform=platform), patch('hunyuan_workbench.sys.platform', platform), patch('hunyuan_workbench.Path.home', return_value=base), patch.dict(os.environ, {'HUNYUAN_WORKBENCH_ROOT': ''}, clear=True):
                    expected = base / suffix / 'hunyuan-workbench'
                    self.assertEqual(default_state_root(), expected)
                    self.assertEqual(Workbench().root, expected.resolve())

    def test_xdg_user_data_override(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('hunyuan_workbench.sys.platform', 'linux'), patch.dict(os.environ, {'XDG_DATA_HOME': folder}, clear=True):
                self.assertEqual(default_state_root(), Path(folder) / 'hunyuan-workbench')

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.core = Workbench(self.root / "state")
        self.views = {}
        for view, color in zip(("front", "right", "back"), ("red", "blue", "green")):
            p = self.root / (view + ".png")
            Image.new("RGB", (256, 256), color).save(p)
            self.views[view] = str(p)

    def tearDown(self): self.temp.cleanup()

    def prepare(self): return self.core.prepare("测试酒坛", self.views, height_m=.34)

    def ready(self):
        job = self.prepare()
        self.core.transition(job["id"], "UPLOADING", "fixture upload")
        self.core.transition(job["id"], "READY", "fixture verified")
        return job

    def test_prepare_deduplicates_and_preserves_sources(self):
        a, b = self.prepare(), self.prepare()
        self.assertEqual(a["id"], b["id"])
        for v, source in self.views.items():
            self.assertEqual(digest(Path(source)), digest(Path(a["views"][v]["path"])))

    def test_reject_duplicate_views(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.core.prepare("bad", {"front":self.views["front"],"right":self.views["front"],"back":self.views["back"]})

    def test_require_three_and_front(self):
        for views in ({"front":self.views["front"]}, {"right":self.views["right"],"left":self.views["front"],"back":self.views["back"]}):
            with self.assertRaises(ValueError): self.core.prepare("bad", views)

    def test_concurrent_submit_has_single_winner(self):
        job = self.ready()
        def reserve(_):
            try:
                self.core.transition(job["id"], "SUBMITTING", "reserve", expected="READY")
                return True
            except ValueError: return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(reserve, range(2))), 1)

    def test_uncertain_cannot_resubmit(self):
        job = self.ready()
        self.core.transition(job["id"], "SUBMITTING", "clicked")
        self.core.transition(job["id"], "UNCERTAIN", "timeout")
        with self.assertRaises(ValueError): self.core.transition(job["id"], "READY", "retry")
        from browser_worker import enqueue
        with self.assertRaises(ValueError): enqueue(self.core.root, "run", job["id"], True)

    def glb(self, **changes):
        doc = {"asset":{"version":"2.0"}, "meshes":[{"primitives":[{"attributes":{"POSITION":0}}]}],
               "accessors":[{"count":3,"componentType":5126,"type":"VEC3"}]}
        doc.update(changes)
        content = json.dumps(doc).encode()
        content += b" " * (-len(content)%4)
        data = struct.pack("<4sII", b"glTF", 2, 20+len(content)) + struct.pack("<II",len(content),0x4E4F534A) + content
        p = self.root / "triangle.glb"
        p.write_bytes(data)
        return p

    def test_glb_counts_and_truncation(self):
        p = self.glb()
        self.assertEqual(inspect_glb(p)["mesh_triangles"], 1)
        p.write_bytes(p.read_bytes()[:-1])
        with self.assertRaises(ValueError): inspect_glb(p)

    def test_external_resources_rejected(self):
        with self.assertRaisesRegex(ValueError, "external"):
            inspect_glb(self.glb(images=[{"uri":"../missing.png"}]))

    def test_archive_requires_success(self):
        job = self.prepare()
        with self.assertRaises(ValueError): self.core.ingest(job["id"], str(self.glb()))

    def test_archive_keeps_source_and_writes_background_script(self):
        job = self.ready()
        for state in ("SUBMITTING", "SUBMITTED", "SUCCEEDED"):
            self.core.transition(job["id"], state, "fixture")
        source = self.glb()
        original = digest(source)
        report = self.core.ingest(job["id"], str(source))
        self.assertEqual(report["sha256"], original)
        self.assertEqual(digest(source), original)
        result = self.core.blender_script(job["id"])
        self.assertTrue(Path(result["script"]).exists())

class BrowserFixtureTest(unittest.TestCase):
    setUp = LedgerTests.setUp
    tearDown = LedgerTests.tearDown
    prepare = LedgerTests.prepare
    def test_three_view_upload_and_single_submit_offline(self):
        from playwright.sync_api import sync_playwright
        from browser_worker import BrowserFlow
        html = '''<!doctype html><html><head><meta charset="utf-8"></head><body>
<span>多张图片</span><span>3D生成 - V3.1</span>
<button class="hy-multiple-views-upload-v2" onclick="document.querySelector('#panel').hidden=false">添加多视图（Min2，Max8）</button>
<div id="panel">CARDS</div>
<span onclick="document.querySelector('#panel').hidden=true">模型面数</span>
<button onclick="this.classList.add('selected')">50k</button>
<button onclick="document.querySelector('#result').textContent='任务提交成功';window.submits=(window.submits||0)+1">立即生成</button>
<p id="result"></p>
<script>for(const input of document.querySelectorAll('input')) input.addEventListener('change',()=>{input.parentElement.classList.add('isSuccess');input.parentElement.querySelector('img').src='/fixture.png?resourceId='+input.parentElement.dataset.view;});</script>
</body></html>'''.replace("CARDS", "".join(f'<div class="hy-upload-card hy-upload-card--{v}" data-view="{v}"><input type="file"><img></div>' for v in self.views))
        job = self.prepare()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True, chromium_sandbox=True)
            context = browser.new_context()
            image = Path(self.views["front"]).read_bytes()
            def route(request):
                if "fixture.png" in request.request.url:
                    request.fulfill(content_type="image/png", body=image)
                else: request.fulfill(content_type="text/html", body=html)
            context.route("**/*", route)
            page = context.new_page()
            page.goto("https://3d.hunyuan.tencent.com/")
            result = BrowserFlow(page, self.core).run(job["id"], submit=True)
            self.assertEqual(result["state"], "SUBMITTED")
            self.assertEqual(page.evaluate("window.submits"), 1)
            with self.assertRaises(ValueError): BrowserFlow(page,self.core).run(job["id"], True)
            browser.close()

if __name__ == "__main__": unittest.main(verbosity=2)
