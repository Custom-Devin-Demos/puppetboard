from datetime import datetime

from flask import render_template, request
from pypuppetdb.types import Node

from puppetboard.core import (environments, get_app,
                              get_puppetdb)
from puppetboard.utils import (calc_batches, check_env, compose_pql_env,
                               compose_pql_pagination, compose_pql_status,
                               query_node_env_count)


app = get_app()
puppetdb = get_puppetdb()


@app.route('/nodes_paged', defaults={'env': app.config['DEFAULT_ENVIRONMENT']})
@app.route('/<env>/nodes_paged')
def nodes_paged(env):
    envs = environments()
    status_arg = request.args.get('status', '')
    page_arg = request.args.get('page', 0, type=int)
    check_env(env, envs)

    pdb_url = f'{puppetdb.base_url}/pdb/query/v4'
    nodes_n = query_node_env_count(env=env, client=puppetdb)
    pages_total = calc_batches(nodes_n, app=app)

    nodes_qry_acc = []
    nodes_qry_acc.append(compose_pql_env(env))
    nodes_qry_acc.append(compose_pql_status(status_arg, app=app))
    nodes_qry_clean = [frg for frg in nodes_qry_acc if frg]

    nodes_qry_fragment = ' and '.join(nodes_qry_clean) if len(nodes_qry_clean) > 1 else nodes_qry_clean[0]
    pg_fragment = compose_pql_pagination(page=page_arg, status=status_arg, app=app, orderby='certname asc')

    qry = f'nodes {{{nodes_qry_fragment} {pg_fragment}}}'

    nodes = []
    nodelist = puppetdb._make_request(
        url=pdb_url,
        payload={'query': qry},
        request_method='GET',
    )
    for raw_node in nodelist:
        # keep everything if there a status filter hasn't been selected,
        # keep only status matches if a status filter has been selected
        if not status_arg or (
            status_arg and raw_node['latest_report_status'] == status_arg
        ):
            nodes.append(Node.create_from_dict(
                query_api=puppetdb,
                node=raw_node,
                with_status=True,
                with_event_numbers=False,
                latest_events=False,
                now=datetime.now(),
                unreported=app.config['UNRESPONSIVE_HOURS'],
            ))

    # TODO: delete pages_total, current_page, query, only used for debugging
    #       delete matching <ul> items in the template
    return render_template(
        'nodes_paged.html',
        nodes=nodes,
        envs=envs,
        current_env=env,
        pages=pages_total,
        current_page=page_arg,
        first_page_url=app.url_for('nodes_paged', env=env, page=0),
        prev_page_url=app.url_for('nodes_paged', env=env, page=page_arg-1),
        next_page_url=app.url_for('nodes_paged', env=env, page=page_arg+1),
        last_page_url=app.url_for('nodes_paged', env=env, page=int(pages_total)),
        query=str(qry),
    )
