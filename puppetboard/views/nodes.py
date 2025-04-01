from datetime import datetime, timedelta, timezone
from itertools import batched

from flask import (
    Response, stream_with_context, request, render_template
)
# import pypuppetdb.QueryBuilder
from pypuppetdb.types import Node
# from pypuppetdb.api.query import QueryAPI
from pypuppetdb.QueryBuilder import (AndOperator,
                                     EqualsOperator,
                                     NullOperator, OrOperator, LessEqualOperator)

from puppetboard.core import get_app, get_puppetdb, environments, stream_template, REPORTS_COLUMNS
from puppetboard.utils import (yield_or_stop, check_env, get_or_abort)

app = get_app()
puppetdb = get_puppetdb()

def get_puppetdb_url():
    host = app.config["PUPPETDB_HOST"]
    port = app.config["PUPPETDB_PORT"]
    return f'http://{host}:{port}/pdb/query/v4'

def query_node_count(env):
    nodes_n_qry = {
        'query': f'nodes[count()] {{ report_environment = "{env}" }}'
    }
    nodes_n_json = puppetdb._make_request(
        url=get_puppetdb_url(),
        payload=nodes_n_qry,
        request_method='GET',
    )
    [nodes_n] = nodes_n_json if nodes_n_json is not None else [{'count': 0}]
    return nodes_n['count']

def get_total_pages(node_count):
    offset = int(app.config['NODE_QRY_OFFSET'])
    # itertools.batched divvies up total node count into even batches
    return len(list(batched(range(node_count), offset)))

def compose_pql_env(env):
    if env != '*':
        return f'catalog_environment = "{env}"'
    return ''

def compose_pql_status(status):
    if status == 'unreported':
        unreported = datetime.now(timezone.utc)
        unreported = unreported - timedelta(hours=app.config['UNRESPONSIVE_HOURS'])
        unreported = unreported.replace(microsecond=0).isoformat()
        return f'report_timestamp is null or report_timestamp <= "{unreported}"'
    if status in ['failed', 'changed', 'noop', 'unchanged']:
        return f'latest_report_status = "{status}"'
    return ''

def compose_pql_pagination(page, status, orderby='certname asc'):
    # only paginate if we are not filtering by status, puppetdb applies
    # pagination before filter conditions
    if status == '':
        offset = int(app.config['NODE_QRY_OFFSET']) * int(page)
        lim = app.config['NODE_QRY_OFFSET']
        return f'order by {orderby} limit {lim} offset {offset}'
    return ''

@app.route('/nodes/<int(min=1):page>', defaults={'env': app.config['DEFAULT_ENVIRONMENT'], 'page': 1})
@app.route('/<env>/nodes/<int(min=1):page>')
def nodes_paged(env, page):
    envs = environments()
    status_arg = request.args.get('status', '')
    check_env(env, envs)

    pdb_url = get_puppetdb_url()
    nodes_n = query_node_count(env=env)
    pages_total = get_total_pages(nodes_n)

    nodes_qry_acc = []

    qry_env = compose_pql_env(env)
    if qry_env:
        nodes_qry_acc.append(qry_env)
    qry_status = compose_pql_status(status_arg)
    if qry_status:
        nodes_qry_acc.append(qry_status)

    pg_fragment = compose_pql_pagination(page=page, status=status_arg, orderby='certname asc')
    nodes_qry_fragment = ''
    if len(nodes_qry_acc) > 1:
        nodes_qry_fragment += " and ".join(nodes_qry_acc)
    else:
        nodes_qry_fragment += nodes_qry_acc[0]

    qry = f'nodes {{{nodes_qry_fragment} {pg_fragment}}}'

    nodes = []
    nodelist = puppetdb._make_request(
        url=pdb_url,
        payload={'query': qry},
        request_method='GET',
    )
    for raw_node in nodelist:
        nd = Node.create_from_dict(
            query_api=puppetdb,
            node=raw_node,
            with_status=True,
            with_event_numbers=False,
            latest_events=False,
            now=datetime.now(),
            unreported=app.config['UNRESPONSIVE_HOURS'],
        )
        # parse everything if there a status filter hasn't been selected,
        # parse status matches if a status filter has been selected
        if not status_arg or (status_arg and nd.status == status_arg):
            nodes.append(nd)

    return render_template(
        'nodes_paged.html',
        nodes=nodes,
        envs=envs,
        current_env=env,
        pages=pages_total,
        current_page=page,
        next_page=app.url_for('.nodes_paged', env=env, page=page+1),
        prev_page=app.url_for('.nodes_paged', env=env, page=page-1),
        query=str(qry),
    )

def get_page_next(page, total):
    if page + 1 > total:
        return total
    return page + 1

def get_page_prev(page):
    if page <= 1:
        return 1
    return page - 1

@app.route('/nodes', defaults={'env': app.config['DEFAULT_ENVIRONMENT']})
@app.route('/<env>/nodes')
def nodes(env):
    """Fetch all (active) nodes from PuppetDB and stream a table displaying
    those nodes.

    Downside of the streaming aproach is that since we've already sent our
    headers we can't abort the request if we detect an error. Because of this
    we'll end up with an empty table instead because of how yield_or_stop
    works. Once pagination is in place we can change this but we'll need to
    provide a search feature instead.

    :param env: Search for nodes in this (Catalog and Fact) environment
    :type env: :obj:`string`
    """
    envs = environments()
    status_arg = request.args.get('status', '')
    check_env(env, envs)

    nodes_n_qry = {
        'query': f'nodes[count()] {{ catalog_environment = "{env}" }}'
    }

    nodes_n_json = puppetdb._make_request(
        url='http://puppetdb-read.service.athenaprod-nva1-dc.consul:8080/pdb/query/v4',
        payload=nodes_n_qry,
        request_method='GET',
    )

    [nodes_n] = nodes_n_json if nodes_n_json is not None else [{'count': 0}]
    nodes_n = nodes_n['count']

    nodes = []
    lim = app.config['NODE_QRY_LIMIT']
    offset = app.config['NODE_QRY_OFFSET']

    # nodes_qry = {
    #     'query': f'nodes {{ catalog_environment = "{env}" order by certname asc limit {lim} offset {offset_idx} }}'
    # }

    # nodes_json = puppetdb._make_request(
    #     url='http://puppetdb-read.service.athenaprod-nva1-dc.consul:8080/pdb/query/v4',
    #     payload=nodes_qry,
    #     request_method='GET',
    # )

    for page in batched(range(nodes_n), offset):
        offset_idx = page[-1]
        nodes_qry = {'query': 'nodes'}
        nodes_qry_acc = []
        # query = AndOperator()

        if env != '*':
            nodes_qry_acc.append(f'catalog_environment = "{env}"')
            # query.add(EqualsOperator("catalog_environment", env))

        if status_arg in ['failed', 'changed', 'unchanged']:
            # nodes_qry['query'] = nodes_qry['query'].replace('nodes', 'nodes[latest_report_status]')
            nodes_qry_acc.append(f'latest_report_status = "{status_arg}"')
            # query.add(EqualsOperator('latest_report_status', status_arg))
        elif status_arg == 'unreported':
            unreported = datetime.now(timezone.utc)
            unreported = (unreported -
                        timedelta(hours=app.config['UNRESPONSIVE_HOURS']))
            unreported = unreported.replace(microsecond=0).isoformat()

            nodes_qry_acc.append(f'report_timestamp is null or report_timestamp <= "{unreported}"')
            # unrep_query = OrOperator()
            # unrep_query.add(NullOperator('report_timestamp', True))
            # unrep_query.add(LessEqualOperator('report_timestamp', unreported))

            # query.add(unrep_query)


        # if len(query.operations) == 0:
        #     query = None
        nodes_qry_fragment = ''
        if len(nodes_qry_acc) > 1:
            nodes_qry_fragment += " and ".join(nodes_qry_acc)

        nodes_qry['query'] = f'{nodes_qry['query']} {{ {nodes_qry_fragment} order by certname asc limit {lim} offset {offset_idx} }}'
        # nodelist = puppetdb.nodes(
        #     query=query,
        #     unreported=app.config['UNRESPONSIVE_HOURS'],
        #     with_status=True,
        #     with_event_numbers=app.config['WITH_EVENT_NUMBERS'],
        # )
        nodelist = puppetdb._make_request(
            url='http://puppetdb-read.service.athenaprod-nva1-dc.consul:8080/pdb/query/v4',
            payload=nodes_qry,
            request_method='GET',
        )
        for node_raw in nodelist:
            node = Node.create_from_dict(
                query_api=puppetdb,
                node=node_raw,
                with_status=True,
                with_event_numbers=False,
                latest_events=False,
                now=datetime.now(),
                unreported=app.config['UNRESPONSIVE_HOURS'],
            )
            if status_arg and node.status == status_arg:
                    nodes.append(node)
            if not status_arg:
                nodes.append(node)

    return Response(stream_with_context(
        stream_template('nodes.html',
                        nodes=nodes,
                        envs=envs,
                        current_env=env)))


@app.route('/node/<node_name>', defaults={'env': app.config['DEFAULT_ENVIRONMENT']})
@app.route('/<env>/node/<node_name>')
def node(env, node_name):
    """Display a dashboard for a node showing as much data as we have on that
    node. This includes facts and reports but not Resources as that is too
    heavy to do within a single request.

    :param env: Ensure that the node, facts and reports are in this environment
    :type env: :obj:`string`
    """
    envs = environments()
    check_env(env, envs)
    query = AndOperator()

    if env != '*':
        query.add(EqualsOperator("environment", env))

    query.add(EqualsOperator("certname", node_name))

    node = get_or_abort(puppetdb.node, node_name)

    return render_template(
        'node.html',
        node=node,
        envs=envs,
        current_env=env,
        columns=REPORTS_COLUMNS[:2],
    )
