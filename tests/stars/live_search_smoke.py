"""Opt-in public search checks using a caller-selected query and term."""

import argparse
import asyncio
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]


async def main(args):
    params = StdioServerParameters(command='uvx', args=['--no-cache', '--from', str(ROOT), 'all-abt-ntu-mcp'], cwd=str(ROOT))
    async with Client(params) as client:
        query = dict(query=args.query, academic_year=args.academic_year, semester=args.semester, study_mode=args.study_mode, limit=2)
        reply = await client.call_tool('stars_search_courses', query)
        if reply.is_error:
            raise RuntimeError('Live course search failed; inspect the tool error locally.')
        first = reply.structured_content
        codes = [course['course_code'] for course in first['courses']]
        page = first
        for _ in range(2):
            if not page['has_more']:
                break
            reply = await client.call_tool('stars_search_courses', {**query, 'offset': len(codes)})
            if reply.is_error:
                raise RuntimeError('Live course search pagination failed; inspect the tool error locally.')
            page = reply.structured_content
            assert page['retrieved_at'] == first['retrieved_at']
            assert page['courses']
            codes.extend(course['course_code'] for course in page['courses'])
        assert len(set(codes)) == len(codes) <= first['total_count']
        if codes:
            details = await client.call_tool('stars_get_course_metadata', dict(course_code=codes[0], academic_year=args.academic_year, semester=args.semester))
            assert not details.is_error
            assert details.structured_content['course_code'] == codes[0]
        print('Live public course search checks passed; sampled results:', len(codes))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', required=True)
    parser.add_argument('--academic-year', type=int, required=True)
    parser.add_argument('--semester', choices=['1', '2', 'S'], required=True)
    parser.add_argument('--study-mode', choices=['full_time', 'part_time'], default='full_time')
    args = parser.parse_args()
    if args.semester != 'S':
        args.semester = int(args.semester)
    asyncio.run(main(args))
