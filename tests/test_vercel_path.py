"""Run from backend/: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'api')))

from flask import Flask, jsonify, request  # noqa: E402

from vercel_path import RestoreVercelPath  # noqa: E402


def make_client():
    app = Flask(__name__)

    @app.route('/api/auth/me')
    def me():
        return jsonify(path=request.path, args=request.args.to_dict())

    @app.route('/')
    def root():
        return jsonify(path=request.path)

    app.wsgi_app = RestoreVercelPath(app.wsgi_app)
    return app.test_client()


class RestoreVercelPathTests(unittest.TestCase):
    def test_restores_nested_path_and_keeps_original_query(self):
        res = make_client().get('/api/index?vercel_path=api%2Fauth%2Fme&token=abc')
        self.assertEqual(res.get_json(), {'path': '/api/auth/me', 'args': {'token': 'abc'}})

    def test_restores_root_path(self):
        res = make_client().get('/api/index?vercel_path=')
        self.assertEqual(res.get_json(), {'path': '/'})

    def test_regular_requests_are_untouched(self):
        res = make_client().get('/api/auth/me?x=1')
        self.assertEqual(res.get_json(), {'path': '/api/auth/me', 'args': {'x': '1'}})


if __name__ == '__main__':
    unittest.main()
