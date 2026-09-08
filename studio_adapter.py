"""Official visible Studio UI inventory. Route URLs were observed on 2026-09-08."""
from pathlib import Path
import time
from hunyuan_workbench import dump

ROUTES = {
    "concept": ("概念设计", "/studio/creation/concept"),
    "geometry": ("几何生成", "/studio/creation/geo"),
    "components": ("组件拆分", "/studio/creation/comp"),
    "retopology": ("低模生成", "/studio/creation/poly"),
    "uv": ("UV展开", "/studio/creation/uv"),
    "texture": ("纹理绘制", "/studio/creation/texture"),
    "rig": ("绑骨蒙皮", "/studio/creation/rs"),
    "animation": ("动画生成", "/studio/creation/ae"),
}

SUBMODES = {
    "concept": ["图生多视图"],
    "geometry": ["上传多视图", "添加多视图（Min2，Max8）"],
    "retopology": ["低模拓扑 - V1.5"],
    "texture": ["图生纹理", "神奇笔刷"],
    "animation": ["选择角色"],
}

def snapshot(page):
    return {
        "url": page.url.split("?")[0],
        "text": page.locator("body").inner_text(timeout=5000),
        "inputs": page.locator("input,textarea,select").evaluate_all("es=>es.map(e=>({tag:e.tagName,type:e.type,accept:e.accept,placeholder:e.getAttribute('placeholder'),multiple:e.multiple,role:e.getAttribute('role'),html:e.outerHTML.slice(0,1200),parent:e.parentElement.outerHTML.slice(0,2500)}))"),
        "controls": page.locator("button,[role=tab],[role=radio],[role=switch],[role=checkbox]").evaluate_all("es=>es.map(e=>({tag:e.tagName,role:e.getAttribute('role'),text:e.innerText,html:e.outerHTML.slice(0,1200)}))"),
        "generation_controls": page.get_by_text("立即生成", exact=True).evaluate_all("es=>es.map(e=>e.parentElement.outerHTML.slice(0,3500))"),
        "headings": page.locator("h1,h2,h3").all_text_contents(),
    }

def research_directory(flow):
    out = flow.core.root / "research"
    out.mkdir(exist_ok=True)
    return out


def probe_model_path(value):
    """Internal UI probes must receive an explicit caller-owned GLB path."""
    from hunyuan_workbench import inspect_glb
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("Supply an explicit GLB path for a model upload probe")
    fixture = Path(value).expanduser().resolve(strict=True)
    if not fixture.is_file() or fixture.suffix.lower() != ".glb":
        raise ValueError("Model upload probe requires a GLB file")
    inspect_glb(fixture)
    return fixture


def research(flow):
    out = research_directory(flow)
    records = {}
    started = time.monotonic()
    for key, (label, route) in ROUTES.items():
        flow.status("RESEARCH", label)
        flow.page.goto("https://3d.hunyuan.tencent.com" + route, wait_until="domcontentloaded", timeout=45000)
        flow.page.get_by_role("link", name=label, exact=True).wait_for(state="visible", timeout=15000)
        flow.page.wait_for_function("() => document.body.innerText.includes('今日剩余生成次数')", timeout=10000)
        flow.guard()
        data = snapshot(flow.page)
        (out / (key + ".json")).write_text(dump(data), encoding="utf-8")
        flow.page.screenshot(path=str(out / (key + ".png")))
        records[key] = {"label": label, "url": data["url"], "text": data["text"], "file": str(out / (key + ".json"))}
        for index, mode in enumerate(SUBMODES.get(key, [])):
            flow.status("RESEARCH", label + ": " + mode)
            control = flow.page.get_by_text(mode, exact=True)
            if control.count() != 1:
                records[key].setdefault("notes", []).append(mode + ": control ambiguous")
                continue
            try:
                control.click(timeout=3000)
            except Exception as error:
                records[key].setdefault("notes", []).append(mode + ": " + str(error)[:250])
                continue
            detail = snapshot(flow.page)
            detail_key = key + "_mode_" + str(index)
            (out / (detail_key + ".json")).write_text(dump(detail), encoding="utf-8")
            flow.page.screenshot(path=str(out / (detail_key + ".png")))
            records[key].setdefault("submodes", {})[mode] = {"text": detail["text"], "file": str(out / (detail_key + ".json"))}
    result = {"captured": time.time(), "elapsed_seconds": time.monotonic()-started, "features": records}
    (out / "inventory.json").write_text(dump(result), encoding="utf-8")
    return result

def probe(flow, model_path=None):
    """Inspect model-dependent options using an explicit GLB; no generation clicks."""
    fixture = probe_model_path(model_path)
    out = research_directory(flow)
    flow.page.goto("https://3d.hunyuan.tencent.com/studio/creation/comp", wait_until="domcontentloaded")
    control = flow.page.locator('input[type="file"][accept*=".glb"]')
    control.wait_for(state="attached", timeout=15000)
    flow.guard()
    control.set_input_files(str(fixture))
    flow.page.wait_for_function("() => !document.body.innerText.includes('您未选择模型') || document.body.innerText.includes('上传成功') || document.querySelector('[role=dialog]')", timeout=20000)
    data = snapshot(flow.page)
    (out / "model_upload_probe.json").write_text(dump(data), encoding="utf-8")
    flow.page.screenshot(path=str(out / "model_upload_probe.png"))
    return {"text": data["text"], "inputs": data["inputs"], "file": str(out / "model_upload_probe.json")}

def download_current(flow, format_name="glb", job_id=None):
    """Download using the current selected model's official export menu."""
    from hunyuan_workbench import digest, inspect_asset
    if format_name not in {"auto", "glb", "fbx", "stl", "usdz", "mp4", "gif"}:
        raise ValueError("Unsupported observed export format")
    flow.guard()
    button=flow.page.get_by_role("button",name="下载",exact=True)
    if not any(flow.page.get_by_text(f,exact=True).is_visible() for f in ('glb','fbx','stl')):
        button.click(timeout=5000)
    flow.page.get_by_text('fbx',exact=True).wait_for(state='visible',timeout=5000)
    available=[f for f in ('glb','fbx','stl','usdz','mp4','gif') if flow.page.get_by_text(f,exact=True).is_visible()]
    if format_name=='auto':
        # STL is appropriate only for raw geometry; never silently discard textures/rigs.
        feature=flow.core.get(job_id).get('feature','geometry') if job_id else None
        preferred=('glb','stl','fbx') if feature=='geometry' else ('glb','fbx')
        format_name=next((f for f in preferred if f in available),None)
    if format_name not in available: raise ValueError('Format unavailable for this asset. Available: '+', '.join(available))
    item = flow.page.get_by_text(format_name, exact=True)
    flow.status("DOWNLOADING", format_name)
    folder = flow.core.root / "downloads"
    folder.mkdir(exist_ok=True)
    with flow.page.expect_download(timeout=60000) as pending:
        item.click()
    download = pending.value
    url_kind=download.url.split(':',1)[0]
    (research_directory(flow)/'last-download-kind.json').write_text(dump({'scheme':url_kind,'format':format_name}),encoding='utf-8')
    basename = Path(download.suggested_filename).name
    if not basename or basename in {".", ".."}:
        raise ValueError("Invalid suggested download filename")
    destination = folder / (str(time.time_ns()) + "_" + basename)
    download.save_as(destination)
    if download.failure():
        raise ValueError("Download did not complete: " + download.failure())
    if not destination.exists() or destination.stat().st_size == 0:
        raise ValueError("Downloaded file is empty")
    report = {"path": str(destination), "bytes": destination.stat().st_size, "sha256": digest(destination), "format": format_name}
    report["inspection"] = inspect_asset(destination)
    if job_id:
        report["archive"] = flow.core.ingest(job_id, str(destination))
    destination.with_suffix(destination.suffix + ".json").write_text(dump(report), encoding="utf-8")
    return report

def dispatch(flow, request, job_id=None):
    action = request.get("action")
    if action=='close_page':
        flow.page.close()
        return {'closed':True,'job_id':job_id}
    if action == 'submit_and_watch':
        result=submit_current(flow,job_id)
        from lifecycle import watch_config
        result['watch']=watch_config(flow,job_id,auto_download=True)
        return result
    if action == 'run':
        import importlib,feature_adapter
        importlib.reload(feature_adapter)
        job=flow.core.get(job_id)
        if job.get('feature','geometry')=='geometry' and job.get('mode','multiview')=='multiview':
            prepared=prepare_geometry(flow,job_id)
        else:
            from feature_adapter import prepare_form
            prepared=prepare_form(flow,job_id)
        if not request.get('submit'): return {'job_id':job_id,'state':flow.core.get(job_id)['state'],'prepared':prepared}
        result=submit_current(flow,job_id)
        if result.get('state') in {'SUBMITTED','RUNNING','SUCCEEDED'}:
            from lifecycle import watch_config
            result['watch']=watch_config(flow,job_id,auto_download=True)
        return result
    if action in {"cards","adopt_completed","status","download_job","watch"}:
        import importlib, lifecycle
        lc = importlib.reload(lifecycle)
        if action == "cards": return lc.cards(flow)
        if action == "adopt_completed": return lc.adopt_completed(flow,job_id,request['thumbnail'],request['evidence'])
        if action == "status": return lc.tick(flow,job_id,request.get('auto_download',False),request.get('format','auto'))
        if action == "download_job": return lc.download_job(flow,job_id,request.get('format','auto'))
        if action == "watch": return lc.watch_config(flow,job_id,request.get('enabled',True),request.get('interval',20),request.get('auto_download',True),request.get('format','auto'))
    if action == "inspect_task":
        flow.guard()
        data = snapshot(flow.page)
        data['upload_sections']=flow.page.get_by_text('图片上传建议',exact=True).evaluate_all("es=>es.map(e=>e.parentElement.parentElement.outerHTML.replace(/<svg[\\s\\S]*?<\\/svg>/g,'<svg/>'))")
        data["panels"] = flow.page.locator("body").evaluate("e=>[...e.querySelectorAll('[data-id],[data-nodeid],[data-node-id],aside,[role=tabpanel]')].map(x=>({html:x.outerHTML.slice(0,20000)}))")
        data["cards"] = flow.page.locator(".container-option-box-bg").evaluate_all("es=>es.map(e=>{let a=e;const r=[];for(let i=0;i<7&&a;i++,a=a.parentElement)r.push({tag:a.tagName,class:a.className,attrs:[...a.attributes].map(x=>[x.name,x.value]),html:a.outerHTML.replace(/<svg[\\s\\S]*?<\\/svg>/g,'<svg/>').slice(0,12000)});return r})")
        data["image_ancestors"] = flow.page.locator("img").evaluate_all("es=>es.map(e=>({src:e.src.split('?')[0],ancestors:(()=>{let a=e;const r=[];for(let i=0;i<7&&a;i++,a=a.parentElement)r.push({tag:a.tagName,class:a.className,id:a.id,text:a.innerText?.slice(0,1200),html:a.outerHTML.slice(0,10000)});return r})()}))")
        out = research_directory(flow) / "current_task.json"
        out.write_text(dump(data),encoding="utf-8")
        flow.page.screenshot(path=str(out.with_suffix(".png")))
        return {"text":data["text"],"file":str(out)}
    if action == "prepare_geometry":
        return prepare_geometry(flow, job_id)
    if action == "finish_geometry":
        return finish_geometry(flow, job_id)
    if action == "submit":
        return submit_current(flow, job_id)
    if action == "inspect_route":
        feature = request["feature"]
        label, route = ROUTES[feature]
        fixture = probe_model_path(request["probe_model"]) if request.get("probe_model") else None
        flow.page.goto("https://3d.hunyuan.tencent.com" + route, wait_until="domcontentloaded", timeout=30000)
        flow.page.get_by_role("link", name=label, exact=True).wait_for(state="visible", timeout=12000)
        flow.guard()
        if fixture is not None:
            flow.page.locator('input[type="file"][accept*=".glb"]').set_input_files(str(fixture))
            try:
                flow.page.get_by_text("上传中...",exact=True).wait_for(state='hidden',timeout=15000)
            except Exception:
                pass
        for label in request.get("click", []):
            flow.page.get_by_text(label, exact=True).click(timeout=5000)
        if request.get("wait_text"):
            flow.page.get_by_text(request["wait_text"], exact=True).wait_for(state="visible", timeout=10000)
        data = snapshot(flow.page)
        out = research_directory(flow) / (feature + ("_loaded" if fixture is not None else "_detail") + ".json")
        out.write_text(dump(data), encoding="utf-8")
        flow.page.screenshot(path=str(out.with_suffix(".png")))
        return {"text": data["text"], "file": str(out), "inputs": data["inputs"]}
    raise ValueError("Unknown Studio operation")

def prepare_geometry(flow, job_id):
    from hunyuan_workbench import digest
    job = flow.core.get(job_id)
    if job["state"] not in {"PREPARED", "UPLOADING", "READY"}:
        raise ValueError("Already submitted or uncertain; do not upload again")
    flow.page.goto("https://3d.hunyuan.tencent.com/studio/creation/geo", wait_until="domcontentloaded", timeout=30000)
    from feature_adapter import open_multiview
    flow.page.get_by_text('上传多视图',exact=True).wait_for(state='visible',timeout=12000)
    flow.page.bring_to_front()
    open_multiview(flow.page)
    flow.guard()
    inputs = flow.page.locator('input[type="file"][accept*=".png"]')
    from feature_adapter import view_slots,upload_image
    slots=view_slots(inputs,job['views'])
    if job["state"] != "UPLOADING":
        flow.core.transition(job_id,"UPLOADING","Studio batch view upload started")
    uploaded = {}
    started = time.monotonic()
    for view, index in slots.items():
        info = job["views"][view]
        if digest(Path(info["path"])) != info["sha256"]:
            raise ValueError("Reference changed")
        flow.status("UPLOADING", job["name"] + ": " + view)
        upload_image(flow,inputs.nth(index),info)
        uploaded[view] = inputs.nth(index).evaluate("e=>[...e.parentElement.querySelectorAll('img')].map(i=>({src:i.src,width:i.naturalWidth,height:i.naturalHeight}))")
    out = Path(job["folder"]) / "browser"
    out.mkdir(exist_ok=True)
    (out / "studio-uploads.json").write_text(dump({"views":uploaded,"slots":slots,"elapsed_seconds":time.monotonic()-started}),encoding="utf-8")
    flow.page.get_by_text("模型面数", exact=True).and_(flow.page.locator('span')).click(timeout=5000)
    return finish_geometry(flow, job_id)

def finish_geometry(flow, job_id):
    job = flow.core.get(job_id)
    flow.guard()
    if flow.page.url.split('?')[0] != "https://3d.hunyuan.tencent.com/studio/creation/geo" or job["state"] != "UPLOADING":
        raise ValueError("Expected the current unsubmitted geometry job")
    if flow.page.get_by_text('上传背图',exact=True).is_visible():
        flow.page.get_by_text('模型面数',exact=True).and_(flow.page.locator('span')).click(timeout=5000)
    flow.page.bring_to_front()
    flow.page.mouse.click(990,830)
    flow.page.mouse.move(1000,800)
    tooltip = flow.page.get_by_text("更高面数具有更多细节，如模型面数超过50万，不支持进行自动绑骨",exact=True)
    if tooltip.count():
        tooltip.wait_for(state="hidden",timeout=5000)
    face_label = {50000:"50k",500000:"500k",1000000:"1M",1500000:"1.5M"}[job["face_count"]]
    face = flow.page.get_by_text(face_label, exact=True)
    face.click(timeout=5000)
    evidence = {"face": face.evaluate("e=>e.outerHTML"),
                "model": flow.page.get_by_text("3D生成 - V3.1", exact=True).is_visible(),
                "generation_control": flow.page.get_by_text("立即生成",exact=True).evaluate("e=>({disabled:e.closest('[type=button]')?.hasAttribute('disabled'),html:e.closest('[type=button]')?.outerHTML.slice(0,500)})"),
                "images": flow.page.locator("img").evaluate_all("es=>es.map(e=>({src:e.src,width:e.naturalWidth,height:e.naturalHeight}))")}
    out = Path(job["folder"]) / "browser"
    out.mkdir(exist_ok=True)
    (out / "studio-ready.json").write_text(dump(evidence), encoding="utf-8")
    flow.page.screenshot(path=str(out / "studio-ready.png"))
    import json
    uploads=json.loads((out/'studio-uploads.json').read_text(encoding='utf-8'))
    expected={i['src'] for images in uploads['views'].values() for i in images if '/game3d/assets/' not in i['src']}
    previews=flow.page.locator('img[alt^="preview-"]').evaluate_all('es=>es.map(e=>e.src)')
    if len(expected)!=len(job['views']) or set(previews)!=expected:
        raise ValueError('Uploaded reference previews do not match this job')
    if evidence["model"] and not evidence["generation_control"]["disabled"] and "bg-[#282e3c]" in evidence["face"]:
        flow.core.transition(job_id,"READY","Verified Studio model V3.1, selected face count and enabled generation control",expected="UPLOADING")
        from feature_adapter import form_signature
        flow.prepared_job_id=job_id
        flow.prepared_signature=form_signature(flow.page)
    return evidence

def submit_current(flow, job_id):
    import importlib,feature_adapter
    importlib.reload(feature_adapter)
    job = flow.core.get(job_id)
    if job["state"] != "READY":
        raise ValueError("Task is not READY; never resubmit an uncertain task")
    from feature_adapter import form_signature
    if getattr(flow,'prepared_job_id',None)!=job_id or getattr(flow,'prepared_signature',None)!=form_signature(flow.page):
        raise ValueError('Prepared form was changed or browser restarted. Run web-run without --submit to prepare it again.')
    flow.guard()
    from feature_adapter import generation_control
    button=generation_control(flow.page,job.get('feature','geometry'))
    before = flow.page.locator("body").inner_text()
    from lifecycle import CARD, retain_new_card
    before_handles=flow.page.locator(CARD).element_handles()
    flow.core.transition(job_id,"SUBMITTING","Reserved one official web generation click",expected="READY")
    out = Path(job["folder"]) / "browser"
    out.mkdir(exist_ok=True)
    try:
        button.click(timeout=5000)
        result=retain_new_card(flow,job_id,before_handles)
        data = snapshot(flow.page)
        data["image_ancestors"] = flow.page.locator("img").evaluate_all("es=>es.map(e=>({src:e.src.split('?')[0],ancestors:(()=>{let a=e;const r=[];for(let i=0;i<6&&a;i++,a=a.parentElement)r.push({tag:a.tagName,class:a.className,id:a.id,text:a.innerText?.slice(0,1600),data:[...a.attributes].filter(x=>x.name.startsWith('data-')).map(x=>[x.name,x.value])});return r})()}))")
        (out / "after-submit.json").write_text(dump(data),encoding="utf-8")
        flow.page.screenshot(path=str(out / "after-submit.png"))
        return {**result,"evidence":str(out/'after-submit.json')}
    except Exception:
        if flow.core.get(job_id)['state']=='SUBMITTING':
            flow.core.transition(job_id,"UNCERTAIN","Submission response was not conclusively observed",expected="SUBMITTING")
        raise
