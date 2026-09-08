"""Public CLI and stdio MCP: one request per complete browser operation."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from hunyuan_workbench import Workbench, VERSION, VIEWS, dump, inspect_asset
from features import capabilities, prepare_feature
from browser_worker import start, enqueue, poll

def request(core,action,job_id=None,wait=0,**options):
    if action=='download_job' and job_id:
        job=core.get(job_id)
        if job['state']=='DOWNLOADED':
            report_path=Path(job['folder'])/'output'/'inspection.json'
            saved=json.loads(report_path.read_text(encoding='utf-8'))
            fmt=options.get('format','auto')
            extra=Path(job['folder'])/'output'/(fmt+'-download.json')
            if fmt=='auto' or Path(saved['path']).suffix.lower()=='.'+fmt or extra.exists():
                from lifecycle import download_job
                from browser_worker import BrowserFlow
                return download_job(BrowserFlow(None,core),job_id,fmt)
    result=enqueue(core.root,'studio',job_id,text=json.dumps({'action':action,**options}))
    deadline=time.monotonic()+max(0,min(wait,60))
    while time.monotonic()<deadline:
        current=poll(core.root,result['request_id'])
        if current['state'] not in {'QUEUED','RUNNING'}: return current
        time.sleep(.2)
    return result

def watches(core):
    return [json.loads(p.read_text(encoding='utf-8')) for p in (core.root/'watches').glob('hy_*.json')]

def doctor(core):
    p=core.root/'browser-status.json'
    worker=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'state':'NOT_STARTED'}
    return {'version':VERSION,'python':sys.executable,'state_root':str(core.root),'worker':worker,
            'responsive':time.time()-worker.get('heartbeat',0)<15 and worker.get('state')!='STOPPED',
            'transport':'local file queue; persistent Chrome; stdio MCP','cloud_api':False,
            'job_count':len(core.list()),'watches':watches(core)}

def serve():
    from mcp.server.fastmcp import FastMCP
    mcp=FastMCP('hunyuan-workbench',instructions='Control the official Hunyuan web workbench through a persistent local Chrome worker. Existing web account/quota; no Cloud API. Prepare local specs, run once, monitor locally and archive matching downloads. submit=True consumes web quota; only run jobs authorized by the user. Never resubmit SUBMITTING/UNCERTAIN/RUNNING jobs. Check capabilities for tested vs assisted functions.')
    core=Workbench()

    @mcp.tool()
    def workbench_capabilities() -> dict:
        """Observed feature catalog, inputs, tested status and current limitations. Excludes world generation."""
        return capabilities()

    @mcp.tool()
    def workbench_prepare(name:str,views:dict[str,str],face_count:int=50000,height_m:float|None=None,revision:str='v001')->dict:
        """Validate/copy/deduplicate 3..8 views including front. Does not submit or consume quota."""
        return core.prepare(name,views,face_count,height_m,revision)

    @mcp.tool()
    def workbench_prepare_feature(spec:dict)->dict:
        """Validate a feature specification and preserve local inputs. See capabilities and README for schemas."""
        return prepare_feature(core,spec)

    @mcp.tool()
    def workbench_list()->list:
        """Read durable local jobs; no browser calls."""
        return core.list()

    @mcp.tool()
    def workbench_get(job_id:str)->dict:
        """Read one job, its input hashes and state history; no browser calls."""
        return core.get(job_id)

    @mcp.tool()
    def workbench_browser_start()->dict:
        """Start/reconnect the persistent local browser. Uses its existing official web login."""
        return start(core.root)

    @mcp.tool()
    def workbench_browser_run(job_id:str,submit:bool=False)->dict:
        """Upload and configure the full job in one local execution. submit=True generates once and starts local monitoring with automatic download; consumes web quota."""
        return request(core,'run',job_id,submit=submit)

    @mcp.tool()
    def workbench_submit(job_id:str)->dict:
        """Submit an already prepared READY form exactly once. Use only with user authorization for this job; may consume web quota."""
        return request(core,'submit_and_watch',job_id)

    @mcp.tool()
    def workbench_status(job_id:str,refresh:bool=False)->dict:
        """Read local state or enqueue a fresh check of the exactly bound web asset."""
        return request(core,'status',job_id) if refresh else core.get(job_id)

    @mcp.tool()
    def workbench_watch(job_id:str,enabled:bool=True,interval:int=20,auto_download:bool=True,format_name:str='auto')->dict:
        """Configure persistent local task monitoring. Checks happen in the worker without repeated model calls. Stopping monitoring does not cancel generation."""
        return request(core,'watch',job_id,enabled=enabled,interval=interval,auto_download=auto_download,format=format_name)

    @mcp.tool()
    def workbench_watches()->list:
        """Read monitor results, errors, next check times and attention flags from disk."""
        return watches(core)

    @mcp.tool()
    def workbench_download(job_id:str,format_name:str='auto')->dict:
        """Select the matching completed asset, download via official UI, validate and archive. Never generates again."""
        return request(core,'download_job',job_id,format=format_name)

    @mcp.tool()
    def workbench_assets(job_id:str)->dict:
        """List currently loaded visible asset cards and thumbnail identities on this job page. Does not enumerate unloaded pages."""
        return request(core,'cards',job_id)

    @mcp.tool()
    def workbench_recover(job_id:str,thumbnail:str,evidence:str)->dict:
        """Explicitly rebind an interrupted task only after reviewing its matching completed asset. Thumbnail must identify the one selected card. Never generates."""
        return request(core,'adopt_completed',job_id,thumbnail=thumbnail,evidence=evidence)

    @mcp.tool()
    def workbench_browser_inspect(job_id:str|None=None)->dict:
        """Read the visible job page or default page for diagnosing a changed UI."""
        return enqueue(core.root,'inspect',job_id)

    @mcp.tool()
    def workbench_browser_result(request_id:str)->dict:
        """Retrieve one local request result. Read watches for generation progress; do not repeatedly inspect the page."""
        return poll(core.root,request_id)

    @mcp.tool()
    def workbench_ingest(job_id:str,downloaded_file:str)->dict:
        """Validate/archive a manually downloaded artifact for a confirmed successful job."""
        return core.ingest(job_id,downloaded_file)

    @mcp.tool()
    def workbench_blender_script(job_id:str)->dict:
        """Create a separate background Blender import script with metres, normalized height and grounded origin."""
        return core.blender_script(job_id)

    @mcp.tool()
    def workbench_doctor()->dict:
        """Inspect local runtime, worker heartbeat and persisted monitoring state."""
        return doctor(core)

    mcp.run(transport='stdio')

def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path)
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('capabilities','list','doctor','mcp','web-start','web-stop','watches'):
        sub.add_parser(name)
    prep=sub.add_parser('prepare')
    prep.add_argument('--name',required=True)
    for view in VIEWS: prep.add_argument('--'+view.replace('_','-'),dest=view)
    prep.add_argument('--faces',type=int,default=50000);prep.add_argument('--height',type=float);prep.add_argument('--revision',default='v001')
    spec=sub.add_parser('prepare-spec');spec.add_argument('file',type=Path)
    batch=sub.add_parser('batch');batch.add_argument('file',type=Path);batch.add_argument('--submit',action='store_true')
    for name in ('get','blender-script','ingest','status','watch','download','web-run','submit','assets','recover'):
        q=sub.add_parser(name);q.add_argument('job_id')
        if name in {'status','watch','download','web-run','submit','assets','recover'}: q.add_argument('--wait',type=float,default=0)
        if name=='recover':q.add_argument('--thumbnail',required=True);q.add_argument('--evidence',required=True)
        if name=='status': q.add_argument('--refresh',action='store_true')
        if name=='ingest': q.add_argument('file')
        if name=='web-run': q.add_argument('--submit',action='store_true')
        if name in {'watch','download'}: q.add_argument('--format',default='auto',choices=('auto','glb','fbx','stl','usdz','mp4','gif'))
        if name=='watch':
            q.add_argument('--interval',type=int,default=20);q.add_argument('--stop',action='store_true');q.add_argument('--no-download',action='store_true')
    inspect=sub.add_parser('web-inspect');inspect.add_argument('--job-id')
    poller=sub.add_parser('web-poll');poller.add_argument('request_id')
    check=sub.add_parser('inspect-asset',aliases=['inspect-glb']);check.add_argument('file',type=Path)
    args=p.parse_args()
    try:
        if args.root: os.environ['HUNYUAN_WORKBENCH_ROOT']=str(args.root.resolve())
        core=Workbench(args.root)
        cmd=args.command
        if cmd=='mcp': serve();return
        if cmd=='capabilities': result=capabilities()
        elif cmd=='prepare': result=core.prepare(args.name,{v:getattr(args,v) for v in VIEWS if getattr(args,v)},args.faces,args.height,args.revision)
        elif cmd=='prepare-spec': result=prepare_feature(core,json.loads(args.file.read_text(encoding='utf-8-sig')))
        elif cmd=='batch':
            specs=json.loads(args.file.read_text(encoding='utf-8-sig'))
            if not isinstance(specs,list) or not 1<=len(specs)<=8: raise ValueError('Batch must contain 1..8 specifications')
            from features import validate
            for s in specs: validate(s)
            jobs=[prepare_feature(core,s) for s in specs]
            result=[]
            for j in jobs:
                result.append({'job_id':j['id'],'state':j['state'],'request':request(core,'run',j['id'],submit=True) if args.submit and j['state'] in {'PREPARED','UPLOADING','READY'} else None})
        elif cmd=='list': result=core.list()
        elif cmd=='get': result=core.get(args.job_id)
        elif cmd=='doctor': result=doctor(core)
        elif cmd=='web-start': result=start(core.root)
        elif cmd=='web-stop': result=enqueue(core.root,'stop')
        elif cmd=='web-inspect': result=enqueue(core.root,'inspect',args.job_id)
        elif cmd=='web-poll': result=poll(core.root,args.request_id)
        elif cmd=='web-run': result=request(core,'run',args.job_id,args.wait,submit=args.submit)
        elif cmd=='submit': result=request(core,'submit_and_watch',args.job_id,args.wait)
        elif cmd=='status': result=request(core,'status',args.job_id,args.wait) if args.refresh else core.get(args.job_id)
        elif cmd=='watch': result=request(core,'watch',args.job_id,args.wait,enabled=not args.stop,interval=args.interval,auto_download=not args.no_download,format=args.format)
        elif cmd=='watches': result=watches(core)
        elif cmd=='download': result=request(core,'download_job',args.job_id,args.wait,format=args.format)
        elif cmd=='assets': result=request(core,'cards',args.job_id,args.wait)
        elif cmd=='recover': result=request(core,'adopt_completed',args.job_id,args.wait,thumbnail=args.thumbnail,evidence=args.evidence)
        elif cmd=='ingest': result=core.ingest(args.job_id,args.file)
        elif cmd=='blender-script': result=core.blender_script(args.job_id)
        elif cmd in {'inspect-asset','inspect-glb'}: result=inspect_asset(args.file)
        else: raise ValueError('Unknown command')
        print(dump(result))
        if isinstance(result,dict) and result.get('state') in {'ERROR','WORKER_UNRESPONSIVE'}: raise SystemExit(2)
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(dump({'error':str(error)}),file=sys.stderr);raise SystemExit(2)
