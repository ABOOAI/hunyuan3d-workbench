"""Task identity, durable monitoring and export for the visible Studio asset panel.

The website does not expose a task id on these cards. During generation we retain
the exact newly inserted DOM element. Completed assets bind to their unique
thumbnail URL. An interrupted pending card with no unique identity is never guessed.
"""
from pathlib import Path
import json
import re
import time
from hunyuan_workbench import dump

CARD = '#assets-container > div'

def completed_thumbnail(value):
    return bool(value and value.startswith('https://') and '/game3d/assets/' not in value and 'icon-loading' not in value)

def binding_path(flow, job_id):
    p = Path(flow.core.get(job_id)["folder"]) / "browser" / "binding.json"
    p.parent.mkdir(exist_ok=True)
    return p

def read_binding(flow, job_id):
    p = binding_path(flow, job_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def save_binding(flow, job_id, data):
    p = binding_path(flow, job_id)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(dump(data),encoding="utf-8")
    tmp.replace(p)

def cards(flow):
    flow.guard()
    return flow.page.locator(CARD).evaluate_all("es=>es.map((e,index)=>({index,text:e.innerText,thumbnail:e.querySelector('img')?.src?.split('?')[0]||null,selected:!!e.querySelector('[class*=bg-gradient-to-r]'),progress:[...e.querySelectorAll('[role=progressbar]')].map(p=>({value:p.getAttribute('aria-valuenow'),max:p.getAttribute('aria-valuemax')}))}))")

def retain_new_card(flow, job_id, before_handles, timeout=25000):
    """Observe one added asset card, preserving the same element while it changes."""
    deadline = time.monotonic()+timeout/1000
    while time.monotonic()<deadline:
        candidates = flow.page.locator(CARD).element_handles()
        added = [e for e in candidates if not any(e.evaluate('(e,old)=>e===old', old) for old in before_handles)]
        if len(added)==1:
            if not hasattr(flow, 'task_handles'): flow.task_handles = {}
            flow.task_handles[job_id] = added[0]
            binding = {"kind":"live-dom-element", "route":flow.page.url.split('?')[0], "bound_at":time.time(),
                       "note":"Exact single new asset card after the reserved click; no official task id exposed"}
            save_binding(flow, job_id, binding)
            flow.core.transition(job_id,"SUBMITTED","Observed exactly one newly inserted Studio asset card",expected="SUBMITTING")
            return tick(flow, job_id)
        if len(added)>1:
            raise ValueError("Multiple new asset cards; cannot uniquely bind this submission")
        flow.page.wait_for_timeout(200)
    raise ValueError("No uniquely identifiable new asset card observed")

def resolve_card(flow, job_id):
    binding = read_binding(flow, job_id)
    handle = getattr(flow,'task_handles',{}).get(job_id)
    if handle is not None:
        try:
            if handle.evaluate('e=>e.isConnected'): return handle, binding
        except Exception: pass
    thumb = binding.get('thumbnail')
    if completed_thumbnail(thumb):
        try:
            flow.page.wait_for_function("s=>[...document.querySelectorAll('#assets-container > div img')].some(e=>e.src.split('?')[0]===s)",arg=thumb,timeout=5000)
        except Exception: pass
        # Query an observed thumbnail identity, not positional ordering.
        matches = []
        for e in flow.page.locator(CARD).element_handles():
            if e.evaluate("(e,s)=>e.querySelector('img')?.src?.split('?')[0]===s",thumb): matches.append(e)
        if len(matches)==1: return matches[0], binding
    raise ValueError("TASK_IDENTITY_REQUIRED: matching card is unavailable; preserve job and inspect assets. Never resubmit.")

def adopt_completed(flow, job_id, thumbnail, evidence):
    """Explicit recovery from independently reviewed submission evidence."""
    if not evidence or len(evidence)>2000: raise ValueError('Observed evidence required')
    if not completed_thumbnail(thumbnail): raise ValueError('A loading placeholder is not a completed asset identity')
    matches = [c for c in cards(flow) if c['thumbnail']==thumbnail]
    if len(matches)!=1 or not matches[0]['selected']:
        raise ValueError('Recovery requires one matching, selected completed card')
    job = flow.core.get(job_id)
    if job['state'] not in {'SUBMITTING','UNCERTAIN','SUBMITTED','RUNNING'}: raise ValueError('Recovery state is not ambiguous')
    save_binding(flow,job_id,{'kind':'thumbnail','thumbnail':thumbnail,'route':flow.page.url.split('?')[0], 'bound_at':time.time(),'evidence':evidence})
    if job['state'] in {'SUBMITTING','UNCERTAIN'}:
        flow.core.transition(job_id,'SUBMITTED',evidence,expected=job['state'])
    return tick(flow,job_id)

def tick(flow, job_id, auto_download=False, format_name='auto'):
    job = flow.core.get(job_id)
    if job['state'] in {'DOWNLOADED','FAILED'}: return {'job_id':job_id,'state':job['state']}
    if job['state'] not in {'SUBMITTED','RUNNING','SUCCEEDED','UNCERTAIN'}:
        raise ValueError('Task has no confirmed submission binding')
    flow.guard()
    handle,binding = resolve_card(flow,job_id)
    info = handle.evaluate("e=>({text:e.innerText,thumbnail:e.querySelector('img')?.src?.split('?')[0]||null,selected:!!e.querySelector('[class*=bg-gradient-to-r]')})")
    if not completed_thumbnail(info['thumbnail']): info['thumbnail']=None
    if re.search('生成失败|任务失败|处理失败',info['text']):
        flow.core.transition(job_id,'FAILED','Matching asset card: '+info['text'][:800],expected=job['state'])
    elif info['thumbnail'] and not re.search('生成中|排队|处理中',info['text']):
        binding.update(kind='thumbnail',thumbnail=info['thumbnail'],completed_observed_at=time.time())
        save_binding(flow,job_id,binding)
        if not info['selected']:
            handle.click(timeout=5000)
        flow.page.get_by_role('button',name='下载',exact=True).wait_for(state='visible',timeout=15000)
        # Recheck the selection after asynchronous loading.
        if not handle.evaluate("e=>!!e.querySelector('[class*=bg-gradient-to-r]')"):
            raise ValueError('Matching asset is no longer selected; export stopped')
        if job['state']!='SUCCEEDED':
            flow.core.transition(job_id,'SUCCEEDED','Matching completed thumbnail selected and official download control visible',expected=job['state'])
        if auto_download: return download_job(flow,job_id,format_name)
    elif job['state'] in {'SUBMITTED','UNCERTAIN'}:
        flow.core.transition(job_id,'RUNNING','Bound asset card is pending: '+(info['text'][:500] or 'generation placeholder'),expected=job['state'])
    state = flow.core.get(job_id)['state']
    report = {'job_id':job_id,'state':state,'observed_at':time.time(),'card_text':info['text'],'binding_kind':binding.get('kind')}
    (Path(job['folder'])/'browser'/'latest-status.json').write_text(dump(report),encoding='utf-8')
    return report

def download_job(flow,job_id,format_name='auto'):
    from studio_adapter import download_current
    job = flow.core.get(job_id)
    if job['state']=='DOWNLOADED':
        p=Path(job['folder'])/'output'/'inspection.json'
        archived=json.loads(p.read_text(encoding='utf-8'))
        if format_name=='auto' or Path(archived['path']).suffix.lower()=='.'+format_name:
            from hunyuan_workbench import digest
            if not Path(archived['path']).exists() or digest(Path(archived['path']))!=archived['sha256']:
                raise ValueError('Archived artifact is missing or changed; cannot reuse it as a verified download')
            return {'job_id':job_id,'state':'DOWNLOADED','cached':True,'archive':archived}
        extra=Path(job['folder'])/'output'/(format_name+'-download.json')
        if extra.exists():
            saved=json.loads(extra.read_text(encoding='utf-8'))
            from hunyuan_workbench import digest
            if Path(saved['path']).exists() and digest(Path(saved['path']))==saved['sha256']: return {**saved,'cached':True}
            raise ValueError('Additional export is missing or changed')
    if job['state'] not in {'SUCCEEDED','DOWNLOADED'}: tick(flow,job_id)
    if flow.core.get(job_id)['state'] not in {'SUCCEEDED','DOWNLOADED'}: raise ValueError('Task is not complete yet')
    handle,binding = resolve_card(flow,job_id)
    if not binding.get('thumbnail'): raise ValueError('Completion identity missing')
    if not handle.evaluate("e=>!!e.querySelector('[class*=bg-gradient-to-r]')"):
        handle.click(timeout=5000)
        flow.page.get_by_role('button',name='下载',exact=True).wait_for(state='visible',timeout=15000)
    if not handle.evaluate("e=>!!e.querySelector('[class*=bg-gradient-to-r]')"):
        raise ValueError('Selected asset mismatch')
    report=download_current(flow,format_name,job_id if job['state']!='DOWNLOADED' else None)
    report.update(job_id=job_id,binding=binding,state=flow.core.get(job_id)['state'])
    folder=Path(job['folder'])/'output'
    folder.mkdir(exist_ok=True)
    if 'archive' not in report:
        import shutil
        source=Path(report['path'])
        dest=folder/(job_id+'_'+report['format']+'_'+report['sha256'][:8]+source.suffix.lower())
        if not dest.exists(): shutil.copy2(source,dest)
        from hunyuan_workbench import digest
        if digest(dest)!=report['sha256']: raise ValueError('Additional export archive hash mismatch')
        report.update(source_download=str(source),path=str(dest))
    (folder/(format_name+'-download.json')).write_text(dump(report),encoding='utf-8')
    return report

def watch_config(flow, job_id, enabled=True, interval=20, auto_download=True, format_name='auto'):
    if not 5<=interval<=300: raise ValueError('Watch interval must be 5..300 seconds')
    if format_name not in {'auto','glb','fbx','stl','usdz','mp4','gif'}: raise ValueError('Unsupported format')
    job=flow.core.get(job_id)
    if job['state'] not in {'SUBMITTED','RUNNING','SUCCEEDED','DOWNLOADED','FAILED','UNCERTAIN'}:
        raise ValueError('Submit and bind this task before monitoring')
    data={'job_id':job_id,'enabled':bool(enabled),'interval':interval,'auto_download':bool(auto_download),'format':format_name,'next_check':0,'errors':0}
    folder=flow.core.root/'watches'
    folder.mkdir(exist_ok=True)
    (folder/(job_id+'.json')).write_text(dump(data),encoding='utf-8')
    return data

def watch_tick(flow, resolve_flow=None):
    """One bounded pass; browser worker calls this while idle. No model polling."""
    folder=flow.core.root/'watches'
    for p in folder.glob('hy_*.json'):
        data=json.loads(p.read_text(encoding='utf-8'))
        if not data['enabled'] or time.time()<data.get('next_check',0): continue
        try:
            target=resolve_flow(data['job_id']) if resolve_flow else flow
            result=tick(target,data['job_id'],data['auto_download'],data['format'])
            data.update(last_result=result,last_check=time.time(),errors=0)
            data.pop('last_error',None);data.pop('attention_required',None)
            if result['state'] in {'FAILED','DOWNLOADED'} or (result['state']=='SUCCEEDED' and not data['auto_download']): data['enabled']=False
        except Exception as error:
            data.update(last_error=str(error)[:1500],last_check=time.time(),errors=data.get('errors',0)+1)
            if 'TASK_IDENTITY_REQUIRED' in str(error) or 'HUMAN_ACTION_REQUIRED' in str(error):
                data.update(enabled=False,attention_required=True)
        data['next_check']=time.time()+min(300,data['interval']*2**min(data['errors'],4))
        tmp=p.with_suffix('.tmp');tmp.write_text(dump(data),encoding='utf-8');tmp.replace(p)
