#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
This module converts an AWS API Gateway proxied request to a WSGI request,
then loads the WSGI application specified by FQN in `.wsgi_app` and invokes
the request when the handler is called by AWS Lambda.

Inspired by: https://github.com/miserlou/zappa

Author: Logan Raarup <logan@logan.dk>
"""
import os
import sys

PY2 = sys.version_info[0] == 2

root = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(root, '.wsgi_app'), 'r') as f:
    app_path = f.read()
app_dir = os.path.dirname(app_path)
requirements_path = os.path.join(root, app_dir, '.requirements')
sys.path.insert(0, requirements_path)

import importlib  # noqa: E402
if PY2:
    from StringIO import StringIO  # noqa: E402
else:
    from io import StringIO  # noqa: E402
from werkzeug.datastructures import Headers  # noqa: E402
from werkzeug.wrappers import Response  # noqa: E402
from werkzeug.urls import url_encode  # noqa: E402
from werkzeug._compat import wsgi_encoding_dance  # noqa: E402

wsgi_fqn = app_path.rsplit('.', 1)
wsgi_module = importlib.import_module(wsgi_fqn[0].replace('/', '.'))
wsgi_app = getattr(wsgi_module, wsgi_fqn[1])


def all_casings(input_string):
    """
    Permute all casings of a given string.
    A pretty algoritm, via @Amber
    http://stackoverflow.com/questions/6792803/finding-all-possible-case-permutations-in-python
    """
    if not input_string:
        yield ""
    else:
        first = input_string[:1]
        if first.lower() == first.upper():
            for sub_casing in all_casings(input_string[1:]):
                yield first + sub_casing
        else:
            for sub_casing in all_casings(input_string[1:]):
                yield first.lower() + sub_casing
                yield first.upper() + sub_casing


def handler(event, context):
    headers = Headers(event[u'headers'])

    if headers.get(u'Host', u'').endswith(u'.amazonaws.com'):
        script_name = '/{}'.format(event[u'requestContext'].get(u'stage', ''))
    else:
        script_name = ''

    environ = {
        'API_GATEWAY_AUTHORIZER':
            event[u'requestContext'].get(u'authorizer', None),
        'CONTENT_LENGTH':
            headers.get(u'Content-Length', str(len(event[u'body'] or ''))),
        'CONTENT_TYPE':
            headers.get(u'Content-Type', ''),
        'PATH_INFO':
            event[u'path'],
        'QUERY_STRING':
            url_encode(event.get(u'queryStringParameters', None) or {}),
        'REMOTE_ADDR':
            headers.get(u'X-Forwarded-For', '').split(', ')[0],
        'REMOTE_USER':
            event[u'requestContext'].get(u'authorizer', {}).get(
                u'principalId', ''),
        'REQUEST_METHOD':
            event[u'httpMethod'],
        'SCRIPT_NAME':
            script_name,
        'SERVER_NAME':
            headers.get(u'Host', 'lambda'),
        'SERVER_PORT':
            headers.get(u'X-Forwarded-Port', '80'),
        'SERVER_PROTOCOL':
            'HTTP/1.1',
        'context':
            context,
        'wsgi.errors':
            StringIO(),
        'wsgi.input':
            StringIO(wsgi_encoding_dance(event[u'body'] or '')),
        'wsgi.multiprocess':
            False,
        'wsgi.multithread':
            False,
        'wsgi.run_once':
            False,
        'wsgi.url_scheme':
            headers.get(u'X-Forwarded-Proto', 'http'),
        'wsgi.version':
            (1, 0),
    }

    for key, value in environ.items():
        if PY2:
            if isinstance(value, basestring):  # noqa: F821
                environ[key] = wsgi_encoding_dance(value)
        else:
            if isinstance(value, str):
                environ[key] = wsgi_encoding_dance(value)

    for key, value in headers.items():
        key = 'HTTP_' + key.upper().replace('-', '_')
        if key not in ('HTTP_CONTENT_TYPE', 'HTTP_CONTENT_LENGTH'):
            environ[key] = value

    response = Response.from_app(wsgi_app, environ)

    errors = environ['wsgi.errors'].getvalue()
    if errors:
        print(errors)

    # If there are multiple Set-Cookie headers, create case-mutated variations
    # in order to pass them through APIGW. This is a hack that's currently
    # needed. See: https://github.com/logandk/serverless-wsgi/issues/11
    # Source: https://github.com/Miserlou/Zappa/blob/master/zappa/middleware.py
    new_headers = [x for x in response.headers if x[0] != 'Set-Cookie']
    cookie_headers = [x for x in response.headers if x[0] == 'Set-Cookie']
    if len(cookie_headers) > 1:
        for header, new_name in zip(cookie_headers, all_casings('Set-Cookie')):
            new_headers.append((new_name, header[1]))
    elif len(cookie_headers) == 1:
        new_headers.extend(cookie_headers)

    return {
        u'statusCode': response.status_code,
        u'headers': dict(new_headers),
        u'body': str(response.data)
    }
