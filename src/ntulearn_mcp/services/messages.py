"""Read Blackboard mailbox conversations without marking messages as read."""

from ..ntu_client.client import PREFIX, identifier, mapping, model, page_parameters
from ..models import MessageDetail, Messages, MessageSummary, Person
from ..models import LearnError
from ..parser.response import records, required, text
from .people import person
from .scan import LimitReached, Scan, aware


def _rows(client, scan, path, refresh):
    offset = 0
    while True:
        data = scan.get(client, path, {'limit': 100, 'offset': offset}, refresh)
        rows, next_offset = records(data, path)
        yield from rows
        if next_offset is None:
            return
        if next_offset <= offset:
            raise LearnError('NTULearn returned a mailbox pagination loop.')
        offset = next_offset


def _summary(row, conversation, course_id, own_id):
    sender = person(mapping(row, 'sender'), required(row, 'senderId'))
    return model(MessageSummary, id=required(row, 'id'), course_id=course_id,
                 conversation_id=required(conversation, 'id'), sender=sender,
                 subject=row.get('subject') or conversation.get('subject'), created=row.get('postDate'),
                 read=row.get('isRead'), folder='sent' if sender.id == own_id else 'inbox')


def _messages(conversation):
    rows = conversation.get('messages')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise LearnError('NTULearn returned an unfamiliar conversation format.')
    total = conversation.get('totalCount')
    if total is not None and (type(total) is not int or total < 0):
        raise LearnError('NTULearn returned an unfamiliar conversation message count.')
    return rows


def _mailbox(client, scan, course_id, refresh):
    own = scan.get(client, PREFIX + '/users/me', refresh=refresh)
    own_id = identifier(required(own, 'id'))
    if course_id:
        courses = [identifier(course_id)]
    else:
        courses = [identifier(required(row, 'courseId')) for row in _rows(client, scan, '/learn/api/v1/messages/summary', refresh)
                   if row.get('isCourseMessagesEnabled') is not False]
    for course in dict.fromkeys(courses):
        try:
            for conversation in _rows(client, scan, f'/learn/api/v1/courses/{course}/conversations', refresh):
                rows = _messages(conversation)
                if conversation.get('totalCount', len(rows)) > len(rows):
                    conversation = scan.get(client, f'/learn/api/v1/courses/{course}/conversations/{identifier(required(conversation, "id"))}', refresh=refresh)
                    rows = _messages(conversation)
                    if conversation.get('totalCount', len(rows)) > len(rows):
                        scan.issue('messages', 'Only part of this conversation was published; available messages are retained.', course)
                for row in rows:
                    yield _summary(row, conversation, course, own_id), row, conversation
        except LearnError as error:
            scan.issue('messages', error, course)
            if isinstance(error, LimitReached):
                return


def list_messages(client, folder='inbox', course_id=None, since=None, unread_only=False, limit=50, offset=0, max_requests=100, refresh=False):
    page_parameters(limit, offset)
    if folder not in {'inbox', 'sent'}:
        raise LearnError('folder must be inbox or sent.')
    aware(since, 'since')
    scan = Scan(max_requests)
    messages = []
    try:
        for summary, _, _ in _mailbox(client, scan, course_id, refresh):
            if summary.folder != folder or (unread_only and summary.read is not False):
                continue
            if since is not None and (summary.created is None or summary.created < since):
                if summary.created is None:
                    scan.issue('messages', 'A message has no published timestamp and could not be filtered by since.', summary.course_id)
                continue
            messages.append(summary)
    except LearnError as error:
        scan.issue('messages', error)
    messages.sort(key=lambda row: row.created.timestamp() if row.created else float('-inf'), reverse=True)
    return model(Messages, folder=folder, messages=messages[offset:offset + limit], offset=offset,
                 next_offset=offset + limit if offset + limit < len(messages) else None, **scan.metadata())


def read_message(client, message_id, course_id=None, conversation_id=None, max_requests=100, refresh=False):
    message_id = identifier(message_id)
    if (course_id is None) != (conversation_id is None):
        raise LearnError('Supply course_id and conversation_id together, or omit both to search the mailbox.')
    scan = Scan(max_requests)
    if course_id is not None:
        course_id, conversation_id = identifier(course_id), identifier(conversation_id)
        own = scan.get(client, PREFIX + '/users/me', refresh=refresh)
        conversation = scan.get(client, f'/learn/api/v1/courses/{course_id}/conversations/{conversation_id}', refresh=refresh)
        candidates = [(_summary(row, conversation, course_id, required(own, 'id')), row, conversation) for row in _messages(conversation)]
    else:
        candidates = _mailbox(client, scan, None, refresh)
    for summary, row, conversation in candidates:
        if summary.id != message_id:
            continue
        if course_id is None:
            conversation = scan.get(client, f'/learn/api/v1/courses/{summary.course_id}/conversations/{summary.conversation_id}', refresh=refresh)
            row = next((item for item in _messages(conversation) if item.get('id') == message_id), None)
            if row is None:
                raise LearnError('The selected message is no longer present in its conversation.')
        body = row.get('body')
        if isinstance(body, dict):
            if not any(key in body for key in ('rawText', 'displayText')):
                raise LearnError('NTULearn returned an unfamiliar message body format.')
            body = body['rawText'] if 'rawText' in body else body['displayText']
        known = conversation.get('participantsNotInACategory', [])
        ids = conversation.get('participantIds', [])
        excluded = conversation.get('excludedParticipantIds', [])
        categories = conversation.get('recipientCategory', [])
        if not all(isinstance(value, list) for value in (known, ids, excluded, categories)) or any(not isinstance(user, dict) for user in known):
            raise LearnError('NTULearn returned unfamiliar conversation recipients.')
        people = {required(user, 'id'): person(user) for user in known}
        for user_id in ids:
            people.setdefault(identifier(user_id), Person(id=user_id))
        recipients = [user for user in people.values() if user.id != summary.sender.id and user.id not in excluded]
        return model(MessageDetail, message=summary, body=text(body), recipients=recipients,
                     recipient_categories=categories, excluded_participant_ids=excluded,
                     includes_all_course_members=conversation.get('includesAllMembers'), **scan.metadata())
    raise LearnError('Message not found within the readable mailbox and request budget; use course_id and conversation_id from ntulearn_list_messages.')
