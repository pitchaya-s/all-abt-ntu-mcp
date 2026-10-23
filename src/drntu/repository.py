from . import parser
from .models import Bundle, Bundles, Containers, FacetDefinition, Facets, FacetValue, Files, Item, RepositoryError, SearchResults


def search_parameters(query, scope_id, entity_type, filters):
    params = {"query": query.strip()}
    if scope_id:
        params["scope"] = parser.identifier(scope_id)
    if entity_type != "all":
        params["f.entityType"] = [entity_type + ",equals"]
    for filter in filters or []:
        if not filter.value.strip():
            raise RepositoryError("Filter values must contain text.")
        params.setdefault("f." + filter.field, []).append(filter.value + "," + filter.operator)
    return params


def search(client, query, scope_id=None, entity_type="Publication", filters=None, page=0, page_size=10, refresh=False):
    if not query.strip():
        raise RepositoryError("query must contain search terms; use drntu_browse to explore repository containers.")
    params = search_parameters(query, scope_id, entity_type, filters)
    params.update(dsoType="item", page=page, size=page_size)
    data, snapshot = client.get("/discover/search/objects", params, refresh=refresh)
    result = data["_embedded"]["searchResult"]
    items = [parser.summary(v["_embedded"]["indexableObject"]) for v in parser.embedded(result, "objects")]
    return SearchResults(query=query.strip(), items=items, pagination=parser.pagination(result, len(items), page, page_size), **snapshot)


def get_item(client, item_id, refresh=False):
    item_id = parser.identifier(item_id)
    data, snapshot = client.get(f"/core/items/{item_id}", refresh=refresh)
    summary = parser.summary(data)
    if summary.item_id != item_id:
        raise RepositoryError("DR-NTU returned a different item ID.")
    meta = parser.metadata(data)
    # Keep alternate/multilingual titles; omit the one title already returned above.
    if len(meta.get("dc.title", [])) == 1 and meta["dc.title"][0].value == summary.title and meta["dc.title"][0].language is None:
        del meta["dc.title"]
    return Item(item_id=item_id, title=summary.title, entity_type=summary.entity_type, url=summary.url,
                last_modified=data.get("lastModified"), withdrawn=data.get("withdrawn"), metadata=meta, **snapshot)


def browse(client, kind="communities", community_id=None, page=0, page_size=20, refresh=False):
    if community_id:
        relation = "subcommunities" if kind == "communities" else "collections"
        path = f"/core/communities/{parser.identifier(community_id)}/{relation}"
    else:
        path = "/core/" + kind
    data, snapshot = client.get(path, {"page": page, "size": page_size}, refresh=refresh)
    key = "subcommunities" if community_id and kind == "communities" else kind
    containers = [parser.container(v) for v in parser.embedded(data, key)]
    return Containers(kind=kind, containers=containers, pagination=parser.pagination(data, len(containers), page, page_size), **snapshot)


def get_facets(client, facet=None, query="", scope_id=None, entity_type="Publication", filters=None, page=0, page_size=10, refresh=False):
    params = search_parameters(query, scope_id, entity_type, filters)
    if facet is None:
        data, snapshot = client.get("/discover/facets", params, refresh=refresh)
        definitions = [FacetDefinition(name=v["name"], facet_type=v["facetType"]) for v in parser.embedded(data, "facets")]
        return Facets(facet=None, definitions=definitions, values=[], pagination=None, **snapshot)
    params.update(page=page, size=page_size)
    data, snapshot = client.get("/discover/facets/" + facet, params, refresh=refresh)
    if data.get("name") != facet:
        raise RepositoryError("DR-NTU returned a different facet.")
    values = [FacetValue(label=v["label"], count=v["count"], authority_key=v.get("authorityKey"), filter=parser.facet_filter(v, facet))
              for v in parser.embedded(data, "values")]
    return Facets(facet=facet, definitions=[], values=values, pagination=parser.pagination(data, len(values), page, page_size), **snapshot)


def list_bundles(client, item_id, page=0, page_size=20, refresh=False):
    item_id = parser.identifier(item_id)
    data, snapshot = client.get(f"/core/items/{item_id}/bundles", {"page": page, "size": page_size}, refresh=refresh)
    bundles = [Bundle(bundle_id=parser.identifier(v["uuid"]), name=v["name"]) for v in parser.embedded(data, "bundles")]
    return Bundles(item_id=item_id, bundles=bundles, pagination=parser.pagination(data, len(bundles), page, page_size), **snapshot)


def list_files(client, bundle_id, page=0, page_size=20, refresh=False):
    bundle_id = parser.identifier(bundle_id)
    data, snapshot = client.get(f"/core/bundles/{bundle_id}/bitstreams", {"page": page, "size": page_size}, refresh=refresh)
    files = [parser.file(v) for v in parser.embedded(data, "bitstreams")]
    return Files(bundle_id=bundle_id, files=files, pagination=parser.pagination(data, len(files), page, page_size), **snapshot)
