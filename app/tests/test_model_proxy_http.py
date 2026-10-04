import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from action_gate.http_server import build_application, GateHandler
from test_model_proxy import MODEL, Transport


class ModelHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=build_application({'APP_STORAGE':'memory','APP_RUNTIME_CACHE':'off','APP_POLICY_DIR':str(Path(__file__).resolve().parents[1]/'policy')})
        with cls.app.panel_service._transaction() as state:
            for node in state['policy']['checks']:
                if node['type']=='allowed_models':node['models'].append(MODEL)
        cls.app.model_proxy.transport=Transport()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),GateHandler);cls.server.app=cls.app
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}/v1/responses'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def call(self,body=None,auth=True,token='local-support-agent-token'):
        body=body if body is not None else {'model':MODEL,'input':'Hello.','max_output_tokens':256}
        headers={'Content-Type':'application/json'}
        if auth:headers.update({'X-Action-Gate-Principal':'support-agent','X-Action-Gate-Token':token})
        req=urllib.request.Request(self.url,data=body if isinstance(body,bytes) else json.dumps(body).encode(),headers=headers)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:r=opener.open(req,timeout=5)
        except urllib.error.HTTPError as exc:r=exc
        with r:return r.code,r.read().decode(),dict(r.headers)

    def test_auth_before_dispatch(self):
        before=len(self.app.model_proxy.transport.calls)
        for kwargs in ({'auth':False},{'token':'wrong'}):
            status,raw,_=self.call(**kwargs);self.assertEqual(status,401);self.assertIsInstance(json.loads(raw)['error'],dict)
        self.assertEqual(len(self.app.model_proxy.transport.calls),before)

    def test_valid_wire_and_correlation(self):
        status,raw,headers=self.call();self.assertEqual(status,200,raw)
        self.assertEqual(json.loads(raw)['object'],'response');self.assertIn('X-Action-Gate-Invocation-Id',headers)

    def test_malformed_and_identity_body(self):
        for body in (b'{',{'model':MODEL,'input':'Hello','role':'operator'}):
            status,raw,_=self.call(body);self.assertIn(status,(400,422));self.assertIsInstance(json.loads(raw)['error'],dict)

    def test_wire_stream(self):
        status,raw,headers=self.call({'model':MODEL,'input':'Hello','stream':True})
        self.assertEqual(status,200,raw);self.assertIn('text/event-stream',headers['Content-Type'])
        self.assertIn('response.completed',raw);self.assertEqual(headers['X-Action-Gate-Streaming'],'buffered')

    def test_hidden_context_refused(self):
        status,_,_=self.call({'model':MODEL,'input':'Hello','previous_response_id':'resp_test'})
        self.assertEqual(status,422)
