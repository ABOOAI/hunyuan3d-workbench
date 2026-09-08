"""Versioned capabilities and validated job specifications, based on observed UI."""
from pathlib import Path
import hashlib
import json
import shutil
import time
import uuid
from hunyuan_workbench import inspect_image, inspect_glb, digest, dump, VIEWS

CATALOG = {
 'concept': {'label':'概念设计','modes':['text','multiview'],'inputs':'prompt or one character reference','status':'form_adapter','notes':['图生多视图当前仅限人物角色','提示词最多150字']},
 'geometry': {'label':'几何生成','modes':['single','multiview'],'inputs':'1 image or 3..8 named views','status':'live_generation_verified','notes':['V3.1: 50k/500k/1M/1.5M','几何结果可能没有纹理；纹理绘制单独处理']},
 'components': {'label':'组件拆分','modes':['presegment'],'inputs':'FBX/GLB/OBJ/STL','status':'form_adapter','notes':['预分割后可能需要人工调整组件']},
 'retopology': {'label':'低模生成','modes':['retopology'],'inputs':'FBX/GLB/OBJ','status':'form_adapter','notes':['低/中/高；三角形或四边形']},
 'uv': {'label':'UV展开','modes':['unwrap'],'inputs':'FBX/GLB/OBJ','status':'form_adapter','notes':[]},
 'texture': {'label':'纹理绘制','modes':['text','image','multiview','brush'],'inputs':'model + prompt or references','status':'form_adapter','notes':['神奇笔刷需要在模型上指定绘制区域，保留人工步骤']},
 'rig': {'label':'绑骨蒙皮','modes':['auto'],'inputs':'FBX/GLB/OBJ','status':'form_adapter','notes':['需要适合绑骨的角色；超过50万面不支持自动绑骨']},
 'animation': {'label':'动画生成','modes':['template'],'inputs':'visible character thumbnail + exact motion template','status':'form_adapter','notes':['从角色选择器选取已绑骨角色或内置角色；此处没有本地模型上传入口','当前工作台实测是动作模板；不宣称支持API中的文生动作功能']},
}

def capabilities():
    features={k:{**v,'ui_preparation':'live_verified','generation_e2e':k in {'geometry','texture'}} for k,v in CATALOG.items()}
    features['texture']['notes']=features['texture']['notes']+['已验证多视图纹理生成并自动下载GLB；其他模式仍需对应产物验收']
    return {'provider':'official-web-workbench','observed_date':'2026-09-08','world_generation':False,
            'features':features,'downloads':['auto','glb','fbx','stl','usdz','mp4','gif'],
            'download_note':'Formats are discovered per selected asset; not every asset supports every format.',
            'monitor':'Exact new asset DOM element during generation; unique thumbnail after completion. Pending jobs interrupted before a stable identity require review.'}

def validate(spec):
    if not isinstance(spec,dict): raise ValueError('Specification must be a JSON object')
    allowed={'feature','name','mode','prompt','views','image','model','height_m','revision','face_count','level','polygon','motion','a_pose','character'}
    unknown=set(spec)-allowed
    if unknown: raise ValueError('Unknown fields: '+', '.join(sorted(unknown)))
    feature=spec.get('feature')
    if feature not in CATALOG: raise ValueError('Choose a supported feature; world generation is excluded')
    name=spec.get('name','').strip()
    if not name or len(name)>100: raise ValueError('Name required, at most 100 characters')
    mode=spec.get('mode',CATALOG[feature]['modes'][0])
    if mode not in CATALOG[feature]['modes']: raise ValueError('Unsupported feature mode')
    result={**spec,'name':name,'mode':mode,'revision':spec.get('revision','v001')}
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,40}',result['revision']): raise ValueError('Invalid revision')
    if result.get('height_m') is not None and not 0<result['height_m']<=100: raise ValueError('Invalid height')
    if mode=='text':
        prompt=spec.get('prompt','').strip()
        if not prompt or len(prompt)>150: raise ValueError('Prompt must contain 1..150 characters')
        result['prompt']=prompt
    elif spec.get('prompt'): raise ValueError('Prompt is only used in text mode')
    images={}
    if feature in {'concept','geometry','texture'}:
        if mode in {'single','image'} or (feature=='concept' and mode=='multiview'):
            if not spec.get('image'): raise ValueError('One image path is required')
            images={'front':spec['image']}
        elif mode=='multiview':
            images=spec.get('views',{})
            if not 3<=len(images)<=8 or 'front' not in images or set(images)-set(VIEWS):
                raise ValueError('Project multiview preset requires 3..8 named views including front')
    inspected={k:inspect_image(Path(v)) for k,v in images.items()}
    if len({v['sha256'] for v in inspected.values()})!=len(inspected): raise ValueError('Duplicate views')
    if not images and (spec.get('image') or spec.get('views')): raise ValueError('This mode does not accept image inputs')
    result['views']=inspected
    if feature in {'components','retopology','uv','texture','rig'}:
        if not spec.get('model'): raise ValueError('Local model file is required')
        model=Path(spec['model']).resolve(strict=True)
        extensions={'.fbx','.glb','.obj'} | ({'.stl'} if feature=='components' else set())
        if not model.is_file() or model.suffix.lower() not in extensions: raise ValueError('Unsupported model format')
        if not 0<model.stat().st_size<=500*1024**2: raise ValueError('Local model guard: 1 byte..500 MiB')
        info={'path':str(model),'sha256':digest(model),'bytes':model.stat().st_size}
        if model.suffix.lower()=='.glb':
            info['inspection']=inspect_glb(model)
            if feature=='rig' and info['inspection']['mesh_triangles']>500000: raise ValueError('Automatic rigging requires at most 500000 faces')
        if model.suffix.lower()=='.obj':
            # Avoid uploading an OBJ whose companion files will silently be omitted.
            with model.open(encoding='utf-8',errors='replace') as f:
                if any(line.lstrip().startswith('mtllib ') for line in f): raise ValueError('OBJ uses external materials; export a bundled GLB for reliable upload')
        result['model_file']=info
    elif spec.get('model'): raise ValueError('This feature does not accept a model file')
    if feature=='geometry' and spec.get('face_count',50000) not in {50000,500000,1000000,1500000}: raise ValueError('Invalid face count')
    if feature=='retopology':
        if spec.get('level','low') not in {'low','medium','high'}: raise ValueError('Invalid retopology level')
        if spec.get('polygon','triangle') not in {'triangle','quad'}: raise ValueError('Invalid polygon type')
    if feature=='animation':
        if not spec.get('motion','').strip(): raise ValueError('Exact visible motion template is required')
        if not spec.get('character','').startswith('https://'): raise ValueError('Select a character thumbnail from the visible role picker; local models need rigging first')
    result.pop('model',None);result.pop('image',None)
    result.setdefault('height_m',None);result.setdefault('face_count',50000)
    return result

def prepare_feature(core,spec):
    cfg=validate(spec)
    if cfg['feature']=='geometry' and cfg['mode']=='multiview':
        return core.prepare(cfg['name'],{k:v['path'] for k,v in cfg['views'].items()},cfg['face_count'],cfg['height_m'],cfg['revision'])
    identity={k:v for k,v in cfg.items() if k not in {'views','model_file'}}
    identity['views']={k:v['sha256'] for k,v in cfg['views'].items()}
    if 'model_file' in cfg: identity['model_sha256']=cfg['model_file']['sha256']
    fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    with core.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT id FROM jobs WHERE fingerprint=?',(fingerprint,)).fetchone()
        if row: return core.get(row['id'])
        job_id='hy_'+uuid.uuid4().hex[:16]
        folder=core.root/'jobs'/job_id
        folder.mkdir(parents=True)
        for key,info in list(cfg['views'].items())+([('model',cfg['model_file'])] if 'model_file' in cfg else []):
            src=Path(info['path']);dst=folder/'references'/(key+src.suffix.lower());dst.parent.mkdir(exist_ok=True)
            shutil.copy2(src,dst)
            if digest(dst)!=info['sha256']: raise ValueError('Input changed during preparation')
            info.update(source_path=str(src),path=str(dst))
        cfg.update(folder=str(folder),provider='official-web-workbench',workbench_url='https://3d.hunyuan.tencent.com/')
        (folder/'manifest.json').write_text(dump(cfg),encoding='utf-8')
        con.execute('INSERT INTO jobs VALUES (?,?,?,?,?)',(job_id,fingerprint,'PREPARED',dump(cfg),time.time()))
    return core.get(job_id)
