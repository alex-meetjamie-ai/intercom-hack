"""Serve a synthetic SIP.js integration test on localhost:8741, with no cloud calls."""
from aiohttp import web
from app import Jamie, create_app, WEBSITE
from test_jamie import FakeAgent

if __name__ == '__main__':
    app = create_app(Jamie(8741, agent_factory=FakeAgent))
    app.router.add_get('/browser-test', lambda r: web.FileResponse(WEBSITE / 'tests/browser.html'))
    app.router.add_get('/browser-test.js', lambda r: web.FileResponse(WEBSITE / 'dist/browser-test.js'))
    web.run_app(app, host='127.0.0.1', port=8741, access_log=None)
