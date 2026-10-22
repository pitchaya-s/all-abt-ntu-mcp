"""Opt-in public timetable checks using caller-selected courses and terms."""

import argparse
import asyncio
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]


async def main(args):
    params = StdioServerParameters(command='uvx', args=['--no-cache', '--from', str(ROOT), 'all-abt-ntu-mcp'], cwd=str(ROOT))
    async with Client(params) as client:
        async def call(name, **arguments):
            result = await client.call_tool(name, arguments)
            if result.is_error:
                raise RuntimeError(f'Live {name} failed; inspect the tool error locally.')
            return result.structured_content

        term = dict(course_code=args.course_code, academic_year=args.academic_year, semester=args.semester)
        course = await call('stars_get_course_indexes', **term)
        assert course['course_code'] == args.course_code.upper()
        assert course['index_count'] == len(course['indexes']) > 0
        known_indexes = {index['index'] for index in course['indexes']}
        metadata = await call('stars_get_course_metadata', **term)
        assert metadata['course_code'] == course['course_code']
        chosen = course['indexes'][0]
        schedule = await call('stars_get_index', **term, index=chosen['index'])
        assert schedule['sessions'] == chosen['sessions']
        for field in ('vacancy_status', 'vacancies_available', 'waitlist_length'):
            assert schedule[field] == chosen[field]
        if len(course['indexes']) >= 2:
            comparison = await call('stars_compare_indexes', **term, indexes=[index['index'] for index in course['indexes'][:2]])
            assert isinstance(comparison['common_sessions'], list)
        matches = await call('stars_find_matching_indexes', **term)
        assert {match['index'] for match in matches['matches']} <= known_indexes
        print('Live public timetable checks passed; indexes:', len(known_indexes), '; vacancy status:', schedule['vacancy_status'])
        if args.graduate_course_code:
            graduate = await call('stars_get_graduate_course_schedule', course_code=args.graduate_course_code)
            assert graduate['course_code'] == args.graduate_course_code.upper()
            assert graduate['class_groups']
            print('Live graduate timetable checks passed; groups:', len(graduate['class_groups']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course-code', required=True)
    parser.add_argument('--academic-year', type=int, required=True)
    parser.add_argument('--semester', choices=['1', '2', 'S'], required=True)
    parser.add_argument('--graduate-course-code')
    args = parser.parse_args()
    if args.semester != 'S':
        args.semester = int(args.semester)
    asyncio.run(main(args))
