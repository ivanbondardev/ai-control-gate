import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from action_gate.http_server import build_application
from action_gate.model_proxy import ModelProxy, ProxyError, validate_request, sse

MODEL='gpt-5-nano-2025-08-07'
POLICY=Path(__file__).resolve().parents[1]/'policy'


def response(text='Hello.'):
    return {'id':'resp_test','object':'response','status':'completed','model':MODEL,
        'output':[{'id':'msg_test','type':'message','status':'completed','role':'assistant',
                   'content':[{'type':'output_text','text':text,'annotations':[],'logprobs':[]}]}],
        'usage':{'input_tokens':10,'output_tokens':5,'total_tokens':15}}


class Transport:
    key=True
    def __init__(self,result=None,error=None):
        self.calls=[];self.result=result if result is not None else response();self.error=error
    def call(self,body,deadline,iid):
        self.calls.append(copy.deepcopy(body))
        if self.error: raise self.error
        return copy.deepcopy(self.result),'req_test'


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.app=build_application({'APP_STORAGE':'memory','APP_RUNTIME_CACHE':'off','APP_POLICY_DIR':str(POLICY)})
        with self.app.panel_service._transaction() as state:
            for node in state['policy']['checks']:
                if node['type']=='allowed_models':node['models'].append(MODEL)
        self.principal=self.app.config_source.load().principals['support-agent']
        self.transport=Transport()
        self.proxy=ModelProxy(self.app.gateway,self.app.panel_service,{},self.transport)
        self.body={'model':MODEL,'input':'Say hello.','max_output_tokens':256,'store':False}

    def invoke(self,**changes):
        return self.proxy.invoke({**self.body,**changes},self.principal)

    def test_real_envelope_and_report(self):
        r=self.invoke();self.assertEqual(r.status,200,r.body)
        self.assertEqual(r.body['id'],'resp_test');self.assertEqual(len(self.transport.calls),1)
        iid=dict(r.headers)['X-Action-Gate-Invocation-Id']
        row=self.app.repository.get_invocation(iid)
        self.assertEqual(row['response']['usage']['total_tokens'],15)
        self.assertNotIn('Hello.',json.dumps(row))
        self.assertEqual(len({e['seq'] for e in self.app.repository.list_events(iid)}),len(self.app.repository.list_events(iid)))

    def test_unknown_model_never_dispatches(self):
        self.assertEqual(self.invoke(model='forbidden').status,403);self.assertFalse(self.transport.calls)

    def test_model_node_disabled_fails_closed(self):
        with self.app.panel_service._transaction() as state:
            for node in state['policy']['checks']:
                if node['type']=='allowed_models':node['mode']='off'
        self.assertEqual(self.invoke().status,403);self.assertFalse(self.transport.calls)

    def test_input_email_redacted_before_dispatch(self):
        r=self.invoke(input='Contact alex.synthetic@example.test for help.')
        self.assertEqual(r.status,200,r.body)
        self.assertNotIn('alex.synthetic@example.test',json.dumps(self.transport.calls))

    def test_secret_blocked_before_dispatch(self):
        r=self.invoke(input='sk-SYNTHETICONLY000000000000000000000000000000')
        self.assertEqual(r.status,403,r.body);self.assertFalse(self.transport.calls)

    def test_output_email_redacted_and_ids_preserved(self):
        self.transport.result=response('Contact alex.synthetic@example.test.')
        r=self.invoke();self.assertEqual(r.status,200,r.body)
        self.assertNotIn('alex.synthetic@example.test',json.dumps(r.body));self.assertEqual(r.body['id'],'resp_test')

    def test_output_secret_blocked(self):
        self.transport.result=response('sk-SYNTHETICONLY000000000000000000000000000000')
        r=self.invoke();self.assertEqual(r.status,403,r.body);self.assertNotIn('SYNTHETICONLY',json.dumps(r.body))

    def test_signature_blocks(self):
        self.assertEqual(self.invoke(input='pickle.loads(untrusted_blob)').status,403)
        self.assertFalse(self.transport.calls)

    def test_budget_refusal_has_no_dispatch(self):
        with patch.object(self.app.repository,'reserve_budget',return_value=None):
            r=self.invoke()
        self.assertEqual(r.status,429,r.body);self.assertFalse(self.transport.calls)

    def test_audit_failure_prevents_external_work(self):
        with patch.object(self.app.repository,'save_model_checkpoint',side_effect=RuntimeError('no database')):
            r=self.invoke()
        self.assertEqual(r.status,503);self.assertFalse(self.transport.calls)

    def test_upstream_timeout_is_unknown_charge(self):
        self.transport.error=ProxyError('provider_deadline_exceeded',504)
        r=self.invoke();self.assertEqual(r.status,504,r.body)
        from action_gate.budget import utc_day_key
        ledger=self.app.repository.read_ledger('global-daily',utc_day_key())
        self.assertEqual(ledger['unknown_usage_count'],1);self.assertEqual(ledger['reserved_tokens'],0)
        self.assertGreater(ledger['used_tokens'],0)

    def test_missing_usage_not_success(self):
        del self.transport.result['usage']
        self.assertEqual(self.invoke().status,502)

    def test_stream_is_checked_before_events(self):
        self.transport.result=response('alex.synthetic@example.test')
        r=self.invoke(stream=True);self.assertTrue(r.stream,r.body)
        wire=sse(r.body)
        self.assertNotIn('alex.synthetic@example.test',wire);self.assertIn('response.completed',wire)
        self.assertFalse(self.transport.calls[0]['stream'])

    def test_function_call_ids_survive(self):
        self.transport.result['output']=[{'id':'fc_123','type':'function_call','call_id':'call_123',
            'name':'documents_read','arguments':'{"doc_id":"KB-1042"}','status':'completed'}]
        r=self.invoke();self.assertEqual(r.status,200,r.body)
        self.assertEqual(r.body['output'][0]['call_id'],'call_123')
        self.assertEqual(json.loads(r.body['output'][0]['arguments']),{'doc_id':'KB-1042'})

    def test_real_reasoning_item_with_empty_content_round_trips(self):
        request={**self.body,'input':[{'type':'reasoning','id':'rs_real_shape',
            'content':[],'summary':[],'encrypted_content':'opaque-provider-ciphertext'},
            {'type':'function_call','id':'fc_real_shape','call_id':'call_real_shape',
             'name':'documents_read','arguments':'{"doc_id":"KB-1042"}','status':'completed'},
            {'type':'function_call_output','call_id':'call_real_shape','output':'Synthetic document'}]}
        self.assertEqual(validate_request(request)['input'][0]['content'],[])

    def test_no_hidden_state_or_hosted_tools(self):
        for extra in ({'previous_response_id':'resp_a'},{'store':True},{'tools':[{'type':'web_search'}]}, {'input':[{'type':'item_reference','id':'x'}]}, {'role':'operator'}, {'max_output_tokens':99999}):
            with self.subTest(extra=extra), self.assertRaises(ProxyError): validate_request({**self.body,**extra})

    def test_panel_change_applies_next_request(self):
        self.assertEqual(self.invoke().status,200)
        with self.app.panel_service._transaction() as state:
            for node in state['policy']['checks']:
                if node['type']=='allowed_models':node['models'].remove(MODEL)
        self.assertEqual(self.invoke().status,403);self.assertEqual(len(self.transport.calls),1)

    def test_pinned_panel_survives_midflight_change(self):
        original=self.transport.call
        def change(*args):
            with self.app.panel_service._transaction() as state:
                for node in state['policy']['checks']:
                    if node['type']=='allowed_models':node['models'].remove(MODEL)
            return original(*args)
        self.transport.call=change
        self.assertEqual(self.invoke().status,200)

    def test_missing_key_is_explicit(self):
        self.transport.key=False
        r=self.invoke();self.assertEqual(r.status,503,r.body);self.assertFalse(self.transport.calls)

    def test_rate_limit_prevents_next_dispatch(self):
        with self.app.panel_service._transaction() as state:
            for node in state['policy']['checks']:
                if node['type']=='rate_limit':node['max_per_minute']=1
        self.assertEqual(self.invoke().status,200)
        self.assertEqual(self.invoke().status,429);self.assertEqual(len(self.transport.calls),1)

if __name__=='__main__':unittest.main()

class TransportReadTests(unittest.TestCase):
    def test_exact_content_length_can_close_fp_after_last_chunk(self):
        from types import SimpleNamespace
        from action_gate.model_proxy import OpenAITransport
        class Wire:
            headers={'x-request-id':'req_unit'}
            def __init__(self):
                self.fp=SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda _:None)))
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def isclosed(self):return self.fp is None
            def read1(self,_):
                self.fp=None
                return json.dumps(response()).encode()
        transport=OpenAITransport({'OPENAI_API_KEY':'unit-only'})
        with patch.object(transport.opener,'open',return_value=Wire()):
            import time
            result,rid=transport.call({'model':MODEL,'input':'Hello'},time.monotonic()+5,'unit-id')
        self.assertEqual(result['id'],'resp_test');self.assertEqual(rid,'req_unit')
