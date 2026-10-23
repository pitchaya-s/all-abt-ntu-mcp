"""Bounded content traversal and substring search; attachment bytes are not searched."""

from ..client.client import identifier, model
from ..models import ContentMatch, ContentNode, ContentSearch, ContentTree
from ..models import LearnError
from .scan import LimitReached, Scan, course_ids, pages


def bounds(max_depth, max_nodes):
    if type(max_depth) is not int or not 1 <= max_depth <= 10:
        raise LearnError('max_depth must be between 1 and 10; root items are depth 1.')
    if type(max_nodes) is not int or not 1 <= max_nodes <= 5000:
        raise LearnError('max_nodes must be between 1 and 5000.')


def walk(client, scan, course_id, max_depth, max_nodes, refresh, roots=None):
    course_id = identifier(course_id)
    bounds(max_depth, max_nodes)
    seen = set()

    def visit(parent_id, depth, breadcrumb, nodes):
        complete = True
        try:
            for item in pages(scan, client.get_course_contents, 'contents', course_id, parent_id, refresh=refresh):
                if len(seen) >= max_nodes:
                    raise LimitReached('Content node limit reached; increase max_nodes or browse individual folders.')
                if item.id in seen:
                    scan.issue('content', 'Repeated or cyclic content ID was not followed again.', course_id, item.id)
                    complete = False
                    continue
                seen.add(item.id)
                node = model(ContentNode, **item.model_dump())
                nodes.append(node)
                path = [*breadcrumb, node.title]
                yield node, path
                if item.has_children:
                    if depth >= max_depth:
                        node.children_complete = False
                        scan.issue('content', 'Folder not opened because max_depth was reached.', course_id, item.id)
                    else:
                        node.children_complete = yield from visit(item.id, depth + 1, path, node.children)
        except LearnError as error:
            scan.issue('content', error, course_id, parent_id)
            complete = False
        return complete

    yield from visit(None, 1, [], roots if roots is not None else [])


def tree(client, scan, course_id, max_depth, max_nodes, refresh):
    roots = []
    for _ in walk(client, scan, course_id, max_depth, max_nodes, refresh, roots):
        pass
    return roots


def get_content_tree(client, course_id, max_depth=5, max_nodes=1000, max_requests=100, refresh=False):
    scan = Scan(max_requests)
    contents = tree(client, scan, course_id, max_depth, max_nodes, refresh)
    return model(ContentTree, course_id=identifier(course_id), contents=contents, max_depth=max_depth, **scan.metadata())


def search(client, query, selected, max_depth=5, max_nodes=1000, max_results=50, max_requests=100, refresh=False):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise LearnError('query must contain 1–200 non-whitespace characters.')
    if type(max_results) is not int or not 1 <= max_results <= 200:
        raise LearnError('max_results must be between 1 and 200.')
    bounds(max_depth, max_nodes)
    query = query.strip()
    scan = Scan(max_requests)
    matches, searched = [], []
    try:
        courses = course_ids(client, scan, selected, refresh)
    except LearnError as error:
        scan.issue('courses', error)
        courses = []
    remaining_nodes = max_nodes
    for course in courses:
        if scan.requests >= scan.limit or remaining_nodes <= 0:
            scan.issue('search', 'Search limit reached before all selected courses were visited.')
            break
        searched.append(course)
        for node, breadcrumb in walk(client, scan, course, max_depth, remaining_nodes, refresh):
            remaining_nodes -= 1
            source = '\n'.join(value for value in (node.title, node.body, node.description) if value)
            position = source.casefold().find(query.casefold())
            if position < 0:
                continue
            matches.append(ContentMatch(course_id=course, content_id=node.id, title=node.title, breadcrumb=breadcrumb,
                                        excerpt=source[max(0, position - 80):position + len(query) + 200]))
            if len(matches) >= max_results:
                scan.issue('search', 'max_results reached; narrow the query to inspect additional matches.')
                return model(ContentSearch, query=query, courses_searched=searched, matches=matches, **scan.metadata())
    return model(ContentSearch, query=query, courses_searched=searched, matches=matches, **scan.metadata())
