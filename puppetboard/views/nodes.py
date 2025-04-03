from datetime import datetime, timedelta, timezone
from itertools import batched

from flask import Response, render_template, request, stream_with_context
from pypuppetdb.QueryBuilder import AndOperator, EqualsOperator
from pypuppetdb.types import Node

from puppetboard.core import (REPORTS_COLUMNS, environments, get_app,
                              get_puppetdb, stream_template)
from puppetboard.utils import (check_env, get_or_abort)


app = get_app()
puppetdb = get_puppetdb()


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

    for page in batched(range(nodes_n), offset):
        offset_idx = page[-1]
        nodes_qry = {'query': 'nodes'}
        nodes_qry_acc = []

        if env != '*':
            nodes_qry_acc.append(f'catalog_environment = "{env}"')

        if status_arg in ['failed', 'changed', 'unchanged']:
            nodes_qry_acc.append(f'latest_report_status = "{status_arg}"')
        elif status_arg == 'unreported':
            unreported = datetime.now(timezone.utc)
            unreported = (unreported -
                        timedelta(hours=app.config['UNRESPONSIVE_HOURS']))
            unreported = unreported.replace(microsecond=0).isoformat()

            nodes_qry_acc.append(f'report_timestamp is null or report_timestamp <= "{unreported}"')

        nodes_qry_fragment = ''
        if len(nodes_qry_acc) > 1:
            nodes_qry_fragment += " and ".join(nodes_qry_acc)

        nodes_qry['query'] = f'{nodes_qry['query']} {{ {nodes_qry_fragment} order by certname asc limit {lim} offset {offset_idx} }}'

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
