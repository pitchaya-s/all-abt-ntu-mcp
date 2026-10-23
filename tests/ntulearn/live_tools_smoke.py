"""Opt-in NTULearn capability checks; output is limited to counts and sanitized statuses."""

import asyncio
from pathlib import Path
import tempfile

from mcp import Client

from ntulearn import mcp_server
from shared.server import mcp


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node['children'])


async def main():
    try:
        async with Client(mcp) as client:
            async def call(name, **arguments):
                result = await client.call_tool(name, arguments)
                if result.is_error:
                    raise RuntimeError(result.content[0].text)
                return result.structured_content

            assert len([t for t in (await client.list_tools()).tools if t.name.startswith('ntulearn_')]) == 20
            courses = (await call('ntulearn_list_courses', limit=100))['courses']
            selected = [course for course in courses if course.get('available') == 'Yes' and course.get('organization') is not True]
            assert selected, 'No available enrolled course to sample.'
            course = selected[-1]
            cid = course['id']
            tree = await call('ntulearn_get_content_tree', course_id=cid, max_depth=5, max_requests=50)
            nodes = list(flatten(tree['contents']))
            assert nodes
            print('Live content tree:', len(nodes), 'nodes; complete:', tree['complete'], flush=True)
            query = nodes[0]['title'][:40]
            for name, args in [('ntulearn_search_course_content', {'course_id': cid}), ('ntulearn_search_all_courses', {'course_ids': [cid]})]:
                result = await call(name, query=query, max_requests=50, **args)
                assert result['matches'] and all(item['course_id'] == cid and item['breadcrumb'] for item in result['matches'])
                print('Live', name, 'matches:', len(result['matches']), flush=True)
            for name, args, field in [
                ('ntulearn_get_upcoming', {'course_ids': [cid]}, 'items'),
                ('ntulearn_list_course_users', {'course_id': cid, 'limit': 2}, 'users'),
                ('ntulearn_whats_new', {'course_ids': [cid], 'max_requests': 30}, 'grades'),
            ]:
                result = await call(name, **args)
                print('Live', name, 'items:', len(result[field]), 'issues:', len(result.get('issues', [])), flush=True)
            group_course = course
            groups = await call('ntulearn_list_course_groups', course_id=group_course['id'], limit=100)
            print('Live groups:', len(groups['groups']), flush=True)
            group = next((group for group in groups['groups'] if group.get('is_group_set') is False), None)
            if group:
                members = await call('ntulearn_get_group_members', course_id=group_course['id'], group_id=group['id'], limit=2)
                print('Live group members:', len(members['users']), flush=True)
            else:
                print('Live group members not verified: no child group in the sampled page.', flush=True)
            mailbox = await call('ntulearn_list_messages', course_id=group_course['id'], max_requests=20)
            print('Live inbox messages:', len(mailbox['messages']), 'issues:', len(mailbox['issues']), flush=True)
            if mailbox['messages']:
                message = mailbox['messages'][0]
                detail = await call('ntulearn_read_message', message_id=message['id'], course_id=message['course_id'], conversation_id=message['conversation_id'])
                assert detail['body'] is not None and detail['recipients_scope'] == 'conversation_participants'
                print('Live message body retrieved; published recipients:', len(detail['recipients']), flush=True)
            sent = await call('ntulearn_list_messages', folder='sent', course_id=group_course['id'], max_requests=20)
            print('Live sent messages:', len(sent['messages']), 'issues:', len(sent['issues']), flush=True)
            for node in nodes:
                if node['has_children'] or 'file' not in (node.get('type') or '').lower():
                    continue
                attachments = await call('ntulearn_get_content_attachments', course_id=cid, content_id=node['id'])
                attachment = next((item for item in attachments['attachments'] if Path(item['file_name']).suffix.lower() in {'.pdf', '.docx', '.pptx', '.xlsx', '.txt'}), None)
                if attachment:
                    result = await call('ntulearn_read_file_content', course_id=cid, content_id=node['id'], attachment_id=attachment['id'], max_pages=2, max_chars=2000)
                    assert result['text']
                    print('Live inline document characters:', len(result['text']), 'truncated:', result['truncated'], flush=True)
                    break
            else:
                print('Live inline reading not verified: no supported attachment in the bounded tree.', flush=True)
            with tempfile.TemporaryDirectory() as directory:
                downloaded = await call('ntulearn_download_course', course_id=cid, destination=directory, max_files=1, max_requests=50, max_total_mb=20)
                assert len(downloaded['files']) <= 1
                for item in downloaded['files']:
                    if item['status'] == 'downloaded':
                        assert Path(item['path']).is_relative_to(directory) and Path(item['path']).stat().st_size == item['bytes_written']
                print('Live bounded course download: files:', len(downloaded['files']), 'bytes:', downloaded['bytes_written'], 'issues:', len(downloaded['issues']), flush=True)
    finally:
        mcp_server.session.close()


if __name__ == '__main__':
    asyncio.run(main())
