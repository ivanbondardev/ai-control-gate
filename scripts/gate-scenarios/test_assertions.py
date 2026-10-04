"""Offline checks of the harness, not a substitute or emulator for a real provider."""
import json
import unittest
from support import validate, case


def response():
    return {'object':'response','id':'resp_synthetic_validator_test','model':'validator-only',
            'status':'completed','output':[{'type':'message','content':[]}],
            'usage':{'input_tokens':1,'output_tokens':2,'total_tokens':3}}


class Assertions(unittest.TestCase):
    def test_stream_block_needs_failure(self):
        raw='data: '+json.dumps({'type':'response.completed','response':response()})
        with self.assertRaises(AssertionError): validate(case('D07'),200,raw)

    def test_stream_block_rejects_leak_before_failure(self):
        raw='\n'.join('data: '+json.dumps(e) for e in [
            {'type':'response.output_text.delta','delta':'alex.synthetic@'},
            {'type':'response.output_text.delta','delta':'example.test'},
            {'type':'response.failed'}])
        with self.assertRaises(AssertionError): validate(case('D07'),200,raw)

    def test_missing_route_not_success(self):
        self.assertEqual(validate(case('L01'),404,'not json')[0],'BLOCKED')

    def test_plain_http_ok_not_success(self):
        with self.assertRaises(AssertionError): validate(case('L01'),200,'{}')

    def test_missing_usage_rejected(self):
        r=response(); del r['usage']
        with self.assertRaises(AssertionError): validate(case('L01'),200,json.dumps(r))

    def test_provider_refusal_not_gate_denial(self):
        with self.assertRaises(AssertionError): validate(case('S01'),200,json.dumps(response()))

    def test_rate_error_not_auth_success(self):
        with self.assertRaises(AssertionError): validate(case('A01'),429,json.dumps({'error':{'message':'rate'}}))

    def test_good_response_only_observation(self):
        self.assertEqual(validate(case('L01'),200,json.dumps(response()))[0],'OBSERVED')

    def test_sensitive_output_fails(self):
        r=response(); r['output'][0]['content']=[{'type':'output_text','text':'alex.synthetic@example.test'}]
        with self.assertRaises(AssertionError): validate(case('D04'),200,json.dumps(r))

    def test_split_sse_canary_fails(self):
        events=[{'type':'response.created'}, {'type':'response.output_text.delta','delta':'alex.synthetic@'},
                {'type':'response.output_text.delta','delta':'example.test'},
                {'type':'response.completed','response':response()}]
        raw='\n\n'.join('data: '+json.dumps(e) for e in events)
        with self.assertRaises(AssertionError): validate(case('D05'),200,raw)

    def test_sse_needs_terminal(self):
        with self.assertRaises(AssertionError): validate(case('L04'),200,'data: {"type":"response.created"}\n')

    def test_mcp_transport_error_not_policy_denial(self):
        raw=json.dumps({'jsonrpc':'2.0','id':'M04','error':{'code':-32602}})
        with self.assertRaises(AssertionError): validate(case('M04'),200,raw)

    def test_mcp_wrong_id_fails(self):
        raw=json.dumps({'jsonrpc':'2.0','id':'other','error':{'code':-32602}})
        with self.assertRaises(AssertionError): validate(case('M10'),200,raw)

    def test_unknown_not_allow(self):
        raw=json.dumps({'jsonrpc':'2.0','id':'M02','result':{'structuredContent':{'status':'outcome_unknown'}}})
        with self.assertRaises(AssertionError): validate(case('M02'),200,raw)

if __name__=='__main__': unittest.main()
