"""Form adapters for the observed Studio UI. No clicks on hidden API endpoints."""
from pathlib import Path
import json
import re
import time
from hunyuan_workbench import digest, dump
from studio_adapter import ROUTES, snapshot

VIEW_LABELS={'front':'上传正图','back':'上传背图','left':'上传左图','right':'上传右图','top':'上传顶图','bottom':'上传底图','left_front':'上传左45°图','right_front':'上传右45°图'}

def open_multiview(page):
    control(page,'上传多视图').click(timeout=5000)
    # This form may restore references from another session. Clear the visible
    # input previews, not assets, before filling every requested orientation.
    for _ in range(8):
        deletes=page.locator('[class*="preview-image-delete-"]').filter(visible=True)
        if not deletes.count(): break
        deletes.first.click(timeout=5000)
    named=page.get_by_text('添加多视图（Min2，Max8）',exact=True)
    if named.count()==1 and named.is_visible(): named.click(timeout=5000)
    else:
        bar=page.locator('div:has(> div > [class*="preview-images-container-"])').filter(visible=True)
        if bar.count()!=1: raise ValueError('Multiview upload bar changed')
        box=bar.bounding_box()
        bar.click(position={'x':box['width']-18,'y':box['height']/2},timeout=5000)
    page.wait_for_function("()=>document.querySelectorAll('input[type=file][accept*=\".png\"]').length===8",timeout=5000)

def view_slots(inputs,views):
    order=['front','back','left','right','top','bottom','left_front','right_front']
    labels=inputs.evaluate_all('es=>es.map(e=>e.parentElement.textContent.replaceAll("*","").trim())')
    if len(labels)!=8: raise ValueError('Expected the observed eight-view layout')
    for i,label in enumerate(labels):
        if label and label!=VIEW_LABELS[order[i]]: raise ValueError('View-slot order changed')
        if order[i] not in views:
            loaded=inputs.nth(i).evaluate("e=>[...e.parentElement.querySelectorAll('img')].some(i=>i.src&&!i.src.includes('/game3d/assets/'))")
            if loaded: raise ValueError('Unrequested populated view '+order[i]+'; clear that input before continuing')
    return {v:order.index(v) for v in views}

def control(page,label):
    loc=page.get_by_text(label,exact=True)
    choices=[]
    for i in range(loc.count()):
        e=loc.nth(i)
        if not e.is_visible(): continue
        if e.evaluate("e=>{let a=e;for(let i=0;i<3&&a;i++,a=a.parentElement)if(a.innerText===e.innerText && /cursor-pointer|t-button/.test(a.className))return true;return false}"):
            choices.append(e)
    if len(choices)==1: return choices[0]
    if loc.count()==1 and loc.is_visible(): return loc
    raise ValueError('Ambiguous visible control: '+label)

def generation_control(page,feature):
    name={'uv':'智能展开UV','components':'预分割'}.get(feature,'立即生成')
    loc=page.get_by_text(name,exact=True)
    if loc.count()!=1: raise ValueError('Generation control changed or ambiguous')
    disabled=loc.evaluate("e=>{const p=e.closest('[type=button]');return !p || p.hasAttribute('disabled') || p.classList.contains('t-is-disabled')}")
    if disabled: raise ValueError('Generation control is disabled; review the required inputs')
    return loc

def form_signature(page):
    """Only visible form DOM, excluding asset-list selection and authentication UI."""
    import hashlib
    data=page.locator('input,textarea').evaluate_all("es=>es.filter(e=>!e.closest('#assets-container')&&!['assets','layers','props'].includes(e.value)).map(e=>({type:e.type,value:e.value,checked:e.checked,files:[...(e.files||[])].map(f=>({name:f.name,size:f.size})),images:e.type==='file'?[...e.parentElement.querySelectorAll('img')].map(i=>i.src):[]}))")
    options=page.locator('div,span').evaluate_all("es=>es.filter(e=>['50k','500k','1M','1.5M','低','中','高','三角面','四边面'].includes(e.textContent.trim())&&e.children.length<2).map(e=>({text:e.textContent.trim(),class:e.className,parent:e.parentElement.className}))")
    return hashlib.sha256(json.dumps({'fields':data,'options':options},sort_keys=True).encode()).hexdigest()

def upload_image(flow,loc,info):
    if digest(Path(info['path']))!=info['sha256']: raise ValueError('Prepared image changed')
    before=loc.evaluate("e=>[...e.parentElement.querySelectorAll('img')].map(i=>i.src)")
    loc.set_input_files(info['path'])
    handle=loc.element_handle()
    flow.page.wait_for_function("({e,before})=>[...e.parentElement.querySelectorAll('img')].some(i=>i.complete&&i.naturalWidth>=128&&!i.src.includes('/game3d/assets/')&&!before.includes(i.src))",arg={'e':handle,'before':before},timeout=30000)
    return loc.evaluate("e=>[...e.parentElement.querySelectorAll('img')].map(i=>i.src).filter(s=>!s.includes('/game3d/assets/'))")

def upload_model(flow,info):
    if digest(Path(info['path']))!=info['sha256']: raise ValueError('Prepared model changed')
    loc=flow.page.locator('input[type=file][accept*=".glb"]')
    if loc.count()!=1: raise ValueError('Model upload control unavailable or ambiguous')
    loc.set_input_files(info['path'])
    expected=info.get('inspection',{}).get('mesh_triangles')
    if expected is not None:
        flow.page.get_by_text(str(expected),exact=True).wait_for(state='visible',timeout=40000)
    else:
        flow.page.get_by_text('上传中...',exact=True).wait_for(state='visible',timeout=5000)
    flow.page.get_by_text('上传中...',exact=True).wait_for(state='hidden',timeout=40000)
    flow.page.get_by_text('顶点数',exact=True).wait_for(state='visible',timeout=10000)
    if flow.page.get_by_text('上传失败',exact=False).is_visible(): raise ValueError('Model upload failed')
    return {'file':info['path'],'sha256':info['sha256'],'expected_triangles':expected}

def prepare_form(flow,job_id):
    job=flow.core.get(job_id)
    if job['state'] not in {'PREPARED','UPLOADING','READY'}: raise ValueError('Task already submitted or uncertain')
    feature,mode=job['feature'],job['mode']
    flow.page.goto('https://3d.hunyuan.tencent.com'+ROUTES[feature][1],wait_until='domcontentloaded',timeout=30000)
    flow.page.bring_to_front()
    flow.page.get_by_role('link',name=ROUTES[feature][0],exact=True).wait_for(state='visible',timeout=15000)
    flow.guard()
    if job['state']!='UPLOADING': flow.core.transition(job_id,'UPLOADING','Preparing '+feature+' form')
    evidence={'feature':feature,'mode':mode,'prepared_at':time.time()}
    if 'model_file' in job: evidence['model']=upload_model(flow,job['model_file'])
    if feature in {'concept','texture'}:
        label=({'text':'文生图','multiview':'图生多视图'} if feature=='concept' else {'text':'文生纹理','image':'图生纹理','multiview':'图生纹理','brush':'神奇笔刷'})[mode]
        control(flow.page,label).click(timeout=5000)
    if mode=='text':
        field=flow.page.locator('textarea')
        if field.count()!=1: raise ValueError('Prompt field is ambiguous')
        field.fill(job['prompt'])
        if field.input_value()!=job['prompt']: raise ValueError('Prompt did not persist')
        evidence['prompt']=job['prompt']
    elif mode=='multiview' and feature=='texture':
        open_multiview(flow.page)
        inputs=flow.page.locator('input[type=file][accept*=".png"]')
        slots=view_slots(inputs,job['views'])
        evidence['images']={}
        for view,info in job['views'].items():
            evidence['images'][view]=upload_image(flow,inputs.nth(slots[view]),info)
        flow.page.mouse.click(990,830)
    elif job.get('views'):
        if feature=='geometry': control(flow.page,'上传单图').click(timeout=5000)
        if feature=='texture': control(flow.page,'上传单图').click(timeout=5000)
        inputs=flow.page.locator('input[type=file][accept*=".png"]')
        if inputs.count()!=1: raise ValueError('Single image upload field is ambiguous')
        evidence['images']={'front':upload_image(flow,inputs,job['views']['front'])}
    if feature=='geometry':
        flow.page.mouse.click(990,830)
        face={50000:'50k',500000:'500k',1000000:'1M',1500000:'1.5M'}[job['face_count']]
        control(flow.page,face).click(timeout=5000)
        evidence['face_count']=job['face_count']
    if feature=='concept':
        switches=flow.page.get_by_role('switch')
        if switches.count()!=1: raise ValueError('A-pose switch is ambiguous')
        wanted=bool(job.get('a_pose',False))
        current='t-is-checked' in (switches.get_attribute('class') or '')
        if current!=wanted: switches.click(timeout=5000)
        if ('t-is-checked' in (switches.get_attribute('class') or ''))!=wanted: raise ValueError('A-pose setting did not persist')
        evidence['a_pose']=wanted
    if feature=='retopology':
        level={'low':'低','medium':'中','high':'高'}[job.get('level','low')]
        polygon={'triangle':'三角面','quad':'四边面'}[job.get('polygon','triangle')]
        for label in (level,polygon):
            control(flow.page,label).click(timeout=5000)
        evidence.update(level=level,polygon=polygon)
    if feature=='animation':
        control(flow.page,'选择角色').click(timeout=5000)
        target=flow.page.locator('img').filter(visible=True)
        matches=[target.nth(i) for i in range(target.count()) if target.nth(i).get_attribute('src')==job['character']]
        if len(matches)!=1: raise ValueError('Character thumbnail missing or ambiguous; inspect the role picker')
        matches[0].click(timeout=5000)
        control(flow.page,job['motion']).click(timeout=5000)
        evidence.update(character=job['character'],motion=job['motion'])
    out=Path(job['folder'])/'browser';out.mkdir(exist_ok=True)
    (out/'feature-ready.json').write_text(dump(evidence),encoding='utf-8')
    flow.page.screenshot(path=str(out/'feature-ready.png'))
    if feature=='texture' and mode=='brush':
        return {**evidence,'state':'UPLOADING','attention_required':True,'reason':'Choose the target region and brush strokes on the visible 3D model, then inspect the form before submission.'}
    generation_control(flow.page,feature)
    flow.core.transition(job_id,'READY','Verified feature inputs and enabled '+feature+' control',expected='UPLOADING')
    flow.prepared_job_id=job_id
    flow.prepared_signature=form_signature(flow.page)
    return {**evidence,'state':'READY'}
