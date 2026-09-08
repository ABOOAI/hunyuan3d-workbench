import asyncio
import argparse
import json
from pathlib import Path
import sys
import os
import tempfile
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    parser = argparse.ArgumentParser(description='Offline MCP initialization and capabilities smoke test')
    parser.add_argument('--installed', action='store_true', help='Load only the installed package, ignoring the source directory')
    parser.add_argument('--output', type=Path, help='Optional JSON report path')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hunyuan-mcp-smoke-') as state_root:
        child_args = ['-I', '-m', 'hunyuan_workbench', 'mcp'] if args.installed else [str(Path(__file__).with_name('hunyuan_workbench.py')), 'mcp']
        params=StdioServerParameters(command=sys.executable,args=child_args,
                                    env={**os.environ,'HUNYUAN_WORKBENCH_ROOT':state_root})
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools=await session.list_tools()
                names = {tool.name for tool in tools.tools}
                required = {'workbench_capabilities', 'workbench_prepare', 'workbench_prepare_feature',
                            'workbench_browser_start', 'workbench_browser_run', 'workbench_submit',
                            'workbench_status', 'workbench_watch', 'workbench_download', 'workbench_recover'}
                if len(tools.tools) != 19 or not required.issubset(names):
                    raise RuntimeError('MCP tool catalog does not match the expected 19-tool release')
                result=await session.call_tool('workbench_capabilities',{})
                if result.isError:raise RuntimeError('Capabilities call failed')
                report={'initialized':True,'tool_count':len(tools.tools),'tools':[t.name for t in tools.tools],'capabilities_call_ok':True}
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(main())
