import ast
from datetime import datetime, timedelta, timezone
from itertools import batched
import json
import logging
import sys

from flask import abort, request, url_for
from packaging.version import parse
from pypuppetdb.errors import EmptyResponseError
from requests.exceptions import ConnectionError, HTTPError

log = logging.getLogger(__name__)


def url_for_field(field, value):
    args = request.view_args.copy()
    args.update(request.args.copy())
    args[field] = value
    return url_for(request.endpoint, **args)


def jsonprint(value):
    return json.dumps(value, indent=2, separators=(",", ": "))


def check_db_version(puppetdb):
    """
    Gets the version of puppetdb and exits if it is not an accepted one.
    """
    try:
        current_version = puppetdb.current_version()
        log.info(f"PuppetDB version: {current_version}")

        current_semver = current_version.split("-")[0]
        minimum_semver = "5.2.0"

        if parse(current_semver) < parse(minimum_semver):
            log.error(f"The minimum supported version of PuppetDB is {minimum_semver}")
            sys.exit(1)

    except HTTPError as e:
        log.error(str(e))
        sys.exit(2)
    except ConnectionError as e:
        log.error(str(e))
        sys.exit(2)
    except EmptyResponseError as e:
        log.error(str(e))
        sys.exit(2)


def check_secret_key(secret_key_value):
    if not secret_key_value:
        log.critical('Please set SECRET_KEY to a long, random string,'
                     ' **the same for each application replica**,'
                     ' and do not share it.')
        sys.exit(1)


def parse_python(value: str):
    """
    :param value: any string, number, bool, list or a dict
                  casted to a string (f.e. "{'up': ['eth0'], (...)}")
    :return: the same value but with a proper type
    """
    try:
        return ast.literal_eval(value)
    except ValueError:
        return str(value)
    except SyntaxError:
        return str(value)


def formatvalue(value):
    if isinstance(value, str):
        return value
    elif isinstance(value, list):
        return ", ".join(map(formatvalue, value))
    elif isinstance(value, dict):
        ret = ""
        for k in value:
            ret += k + " => " + formatvalue(value[k]) + ",<br/>"
        return ret
    else:
        return str(value)


def get_or_abort(func, *args, **kwargs):
    """Perform a backend request and handle all the errors,"""
    return _do_get_or_abort(False, func, *args, **kwargs)


def get_or_abort_except_client_errors(func, *args, **kwargs):
    """Perform a backend request and handle the errors,
    but with a chance to react to client errors (HTTP 400-499).
    """
    return _do_get_or_abort(True, func, *args, **kwargs)


def _do_get_or_abort(reraise_client_error: bool, func, *args, **kwargs):
    """Execute the function with its arguments and handle the possible
    errors that might occur.

    If reraise_client_error is True then if the HTTP response status code
    indicates that it was a client side error - then re-raise it.

    In all other cases if we get an exception we simply abort the request.
    """
    try:
        return func(*args, **kwargs)
    except HTTPError as e:
        if reraise_client_error and 400 <= e.response.status_code <= 499:
            # it's a client side error, so reraise it to show the user
            log.warning(str(e))
            raise
        else:
            log.error(str(e))
            abort(e.response.status_code)
    except ConnectionError as e:
        log.error(str(e))
        abort(500)
    except EmptyResponseError as e:
        log.error(str(e))
        abort(204)
    except Exception as e:
        log.error(str(e))
        abort(500)


def yield_or_stop(generator):
    """Similar in intent to get_or_abort this helper will iterate over our
    generators and handle certain errors.

    Since this is also used in streaming responses where we can't just abort
    a request we raise StopIteration.
    """
    while True:
        try:
            yield next(generator)
        except (EmptyResponseError, ConnectionError, HTTPError, StopIteration):
            return


def quote_columns_data(data: str) -> str:
    """When projecting Queries using dot notation (f.e. inventory [ facts.osfamily ])
    we need to quote the dot in such column name for the DataTables library or it will
    interpret the dot a way to get into a nested results object.

    See https://datatables.net/reference/option/columns.data#Types."""
    return data.replace(".", "\\.")


def check_env(env: str, envs: dict):
    if env != "*" and env not in envs:
        abort(404)


def is_a_test():
    running_in_shell = any(
        pytest_binary in sys.argv[0] for pytest_binary in ["pytest", "py.test"]
    )
    running_in_intellij = any("_jb_pytest_runner.py" in arg for arg in sys.argv)
    return running_in_shell or running_in_intellij

def query_node_count(client):
    nodes_n_qry = {
        'query': f'nodes[count()]'
    }
    nodes_n_json = client._make_request(
        url=f'{client.base_url}/pdb/query/v4',
        payload=nodes_n_qry,
        request_method='GET',
    )
    [nodes_n] = nodes_n_json if nodes_n_json is not None else [{'count': 0}]
    return nodes_n['count']

def query_node_env_count(env, client):
    nodes_n_qry = {
        'query': f'nodes[count()] {{report_environment = "{env}"}}'
    }
    nodes_n_json = client._make_request(
        url=f'{client.base_url}/pdb/query/v4',
        payload=nodes_n_qry,
        request_method='GET',
    )
    [nodes_n] = nodes_n_json if nodes_n_json is not None else [{'count': 0}]
    return nodes_n['count']

def query_node_status_count(env, status, client):
    nodes_n_qry = {
        'query': f'nodes[count()] {{report_environment = "{env}" and latest_report_status = "{status}"}}'
    }
    nodes_n_json = client._make_request(
        url=f'{client.base_url}/pdb/query/v4',
        payload=nodes_n_qry,
        request_method='GET',
    )
    [nodes_n] = nodes_n_json if nodes_n_json is not None else [{'count': 0}]
    return nodes_n['count']

def query_resource_count(client):
    resources_n_qry = {
        'query': f'resources[count()]'
    }
    resources_n_json = client._make_request(
        url=f'{client.base_url}/pdb/query/v4',
        payload=resources_n_qry,
        request_method='GET',
    )
    [resources_n] = resources_n_json if resources_n_json is not None else [{'count': 0}]
    return resources_n['count']

def query_resource_env_count(env, client):
    resources_n_qry = {
        'query': f'resources[count()] {{environment = "{env}"}}'
    }
    resources_n_json = client._make_request(
        url=f'{client.base_url}/pdb/query/v4',
        payload=resources_n_qry,
        request_method='GET',
    )
    [resources_n] = resources_n_json if resources_n_json is not None else [{'count': 0}]
    return resources_n['count']

def query_status_counts(env, client):
    status_n_qry = {
        'query': f'nodes[latest_report_status,count()] {{ catalog_environment = "{env}" group by latest_report_status }}'
    }
    status_n_json = client._make_request(
        url=f'{client.base_url}/pdb/query/v4',
        payload=status_n_qry,
        request_method='GET',
    )
    return {stat['latest_report_status']: int(stat['count']) for stat in status_n_json}

def calc_batches(node_count, app):
    offset = int(app.config['NODE_QRY_OFFSET'])
    # itertools.batched divvies up total node count into even batches
    return len(list(batched(range(node_count), offset))) - 1

def compose_pql_env(env):
    if env != '*':
        return f'catalog_environment = "{env}"'
    return ''

def compose_pql_status(status, app):
    if status == 'unreported':
        unreported = datetime.now(timezone.utc)
        unreported = unreported - timedelta(hours=app.config['UNRESPONSIVE_HOURS'])
        unreported = unreported.replace(microsecond=0).isoformat()
        return f'report_timestamp is null or report_timestamp <= "{unreported}"'
    if status in ['failed', 'changed', 'noop', 'unchanged']:
        return f'latest_report_status = "{status}"'
    return ''

def compose_pql_pagination(page, status, app, orderby='certname asc'):
    # only paginate if we are not filtering by status,
    # puppetdb applies pagination before applying filtering conditions
    if status == '':
        offset = int(app.config['NODE_QRY_OFFSET']) * int(page)
        lim = app.config['NODE_QRY_OFFSET']
        return f'order by {orderby} limit {lim} offset {offset}'
    return ''
