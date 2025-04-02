from datetime import datetime
from flask import render_template
from pypuppetdb.QueryBuilder import AndOperator, EqualsOperator, FunctionOperator, ExtractOperator
from pypuppetdb.types import Node
from puppetboard.core import get_app, get_puppetdb, environments
from puppetboard.utils import compose_pql_env, compose_pql_pagination, compose_pql_status, get_or_abort, check_env, query_node_env_count, query_node_count, query_node_status_count, query_resource_count, query_resource_env_count, query_status_counts

app = get_app()
puppetdb = get_puppetdb()


@app.route('/', defaults={'env': app.config['DEFAULT_ENVIRONMENT']})
@app.route('/<env>/')
def index(env):
    """This view generates the index page and displays a set of metrics and
    latest reports on nodes fetched from PuppetDB.

    :param env: Search for nodes in this (Catalog and Fact) environment
    :type env: :obj:`string`
    """
    envs = environments()
    metrics = {
        'num_nodes': 0,
        'num_resources': 0,
        'avg_resources_node': 0,
    }

    if env != app.config['DEFAULT_ENVIRONMENT']:
        check_env(env, envs)

    if env == '*':
        # query = app.config['OVERVIEW_FILTER']

        # prefix = 'puppetlabs.puppetdb.population'
        # num_nodes = get_or_abort(puppetdb.metric, f"{prefix}:name=num-nodes")
        # num_resources = get_or_abort(puppetdb.metric, f"{prefix}:name=num-resources")

        # metrics['num_nodes'] = num_nodes['Value']
        # metrics['num_resources'] = num_resources['Value']

        metrics['num_nodes'] = query_node_count(client=puppetdb)
        metrics['num_resources'] = query_resource_count(client=puppetdb)
        try:
            # Compute our own average because avg_resources_node['Value']
            # returns a string of the format "num_resources/num_nodes"
            # example: "1234/9" instead of doing the division itself.
            metrics['avg_resources_node'] = "{0:10.0f}".format(
                (metrics['num_resources'] / metrics['num_nodes']))
        except ZeroDivisionError:
            metrics['avg_resources_node'] = 0
    else:
        # query = AndOperator()
        # query.add(EqualsOperator('catalog_environment', env))

        # num_nodes_query = ExtractOperator()
        # num_nodes_query.add_field(FunctionOperator('count'))
        # num_nodes_query.add_query(query)

        # if app.config['OVERVIEW_FILTER'] is not None:
        #     query.add(app.config['OVERVIEW_FILTER'])

        # num_resources_query = ExtractOperator()
        # num_resources_query.add_field(FunctionOperator('count'))
        # num_resources_query.add_query(EqualsOperator("environment", env))

        # num_nodes = get_or_abort(
        #     puppetdb._query,
        #     'nodes',
        #     query=num_nodes_query)

        metrics['num_nodes'] = query_node_env_count(env=env, client=puppetdb)
        metrics['num_resources'] = query_resource_env_count(env=env, client=puppetdb)
        # num_resources = get_or_abort(
        #     puppetdb._query,
        #     'resources',
        #     query=num_resources_query)
        try:
            metrics['avg_resources_node'] = "{0:10.0f}".format(
                (metrics['num_resources'] / metrics['num_nodes']))
        except ZeroDivisionError:
            metrics['avg_resources_node'] = 0

    status_counts = query_status_counts(env=env, client=puppetdb)

    # nodes = get_or_abort(puppetdb.nodes,
    #                      query=query,
    #                      unreported=app.config['UNRESPONSIVE_HOURS'],
    #                      with_status=True,
    #                      with_event_numbers=app.config['WITH_EVENT_NUMBERS'])

    # nodes_overview = []
    stats = {
        'changed': 0,
        'unchanged': 0,
        'failed': 0,
        'unreported': 0,
        'noop': 0,
    }

    for status,cnt in status_counts.items():
        if status in stats:
            stats[status] = cnt

    # for node in nodes:
    #     if node.status == 'unreported':
    #         stats['unreported'] += 1
    #     elif node.status == 'changed':
    #         stats['changed'] += 1
    #     elif node.status == 'failed':
    #         stats['failed'] += 1
    #     elif node.status == 'noop':
    #         stats['noop'] += 1
    #     else:
    #         stats['unchanged'] += 1

        # if node.status != 'unchanged':
        #     nodes_overview.append(node)

    nodes_qry_acc = []
    nodes_qry_acc.append(compose_pql_env(env))
    nodes_qry_acc.append(compose_pql_status('failed', app=app))
    nodes_qry_clean = [frg for frg in nodes_qry_acc if frg]

    nodes_qry_fragment = ' and '.join(nodes_qry_clean) if len(nodes_qry_clean) > 1 else nodes_qry_clean[0]
    qry = f'nodes {{{nodes_qry_fragment}}}'

    nodes = []
    nodelist = puppetdb._make_request(
        url=f'{puppetdb.base_url}/pdb/query/v4',
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
        if nd.status == 'failed':
            nodes.append(nd)

    return render_template(
        'index.html',
        metrics=metrics,
        nodes=nodes,
        stats=stats,
        envs=envs,
        current_env=env,
    )
