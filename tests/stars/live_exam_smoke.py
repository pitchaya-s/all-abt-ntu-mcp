"""Opt-in public exam lookup for a caller-selected course."""

import argparse
import asyncio
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]


async def main(args):
    params = StdioServerParameters(command='uvx', args=['--no-cache', '--from', str(ROOT), 'all-abt-ntu-mcp'], cwd=str(ROOT))
    async with Client(params) as client:
        result = await client.call_tool('stars_get_undergraduate_exam_schedule', {'course_code': args.course_code})
        if result.is_error:
            raise RuntimeError('Live exam lookup failed; inspect the tool error locally.')
        data = result.structured_content
        assert data['course_code'] == args.course_code.upper()
        assert data['exam_count'] == len(data['exams'])
        print('Live public exam checks passed; status:', data['exam_status'], '; exams:', data['exam_count'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course-code', required=True)
    asyncio.run(main(parser.parse_args()))
