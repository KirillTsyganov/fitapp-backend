from urllib.parse import parse_qsl, urlencode

FUNCTION_PATH = '/api/index'
PATH_PARAM = 'vercel_path'


class RestoreVercelPath:
    """The Vercel Python runtime hands Flask the rewrite destination, so vercel.json passes the original path as a query param."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        if environ.get('PATH_INFO') == FUNCTION_PATH:
            params = parse_qsl(environ.get('QUERY_STRING', ''), keep_blank_values=True)
            original = next((v for k, v in params if k == PATH_PARAM), None)
            if original is not None:
                environ['PATH_INFO'] = '/' + original.lstrip('/')
                environ['QUERY_STRING'] = urlencode([(k, v) for k, v in params if k != PATH_PARAM])
        return self.wsgi_app(environ, start_response)
