"""Guarded OpenAI Responses proxy; stateless text/function profile, buffered SSE.

Credentials and upstream destination are server-owned. No retry or redirect can dispatch twice.
Panel controls are pinned per invocation; the existing release owns durable budget limits and
additional content controls. Both policy identities are audited. No provider input/output is stored
in audit: only keyed hashes, measured usage, decisions and correlation IDs.
"""
from copy import deepcopy
import json
import socket
import re
import time
import sys
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass

from .audit import AuditTrail, keyed_hash
from .budget import BudgetPlan, utc_day_key
from .content import ContentGate
from .panel_engine import evaluate, PanelValidationError
from .panel_service import PanelService
from .policy_reader import policy_hash
from .snapshot import to_jsonable
from .storage.base import RepositoryError

MAX_RESPONSE_BYTES = 2_000_000
MAX_OUTPUT_TOKENS = 4096
FIELDS = {'model', 'input', 'instructions', 'tools', 'tool_choice', 'parallel_tool_calls',
          'max_output_tokens', 'store', 'stream', 'reasoning', 'include', 'text', 'temperature', 'top_p'}


class ProxyError(Exception):
    def __init__(self, code, status=403):
        self.code, self.status = code, status
        super().__init__(code)


def error_body(code):
    # Never echo upstream error text, request fragments, credentials or URLs.
    return {'error': {'type': 'action_gate_error', 'code': code,
                      'message': 'Action Gate: ' + code.replace('_', ' ')}}


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def validate_request(body):
    if not isinstance(body, dict) or set(body) - FIELDS:
        raise ProxyError('schema_invalid', 422)
    if not isinstance(body.get('model'), str) or not 1 <= len(body['model']) <= 160:
        raise ProxyError('model_required', 422)
    if body.get('store', False) is not False:
        raise ProxyError('stored_context_not_supported', 422)
    for k in ('stream', 'parallel_tool_calls'):
        if k in body and type(body[k]) is not bool:
            raise ProxyError('schema_invalid', 422)
    cap = body.get('max_output_tokens', 1024)
    if type(cap) is not int or cap < 16:
        raise ProxyError('invalid_output_limit', 422)
    if cap > MAX_OUTPUT_TOKENS:
        raise ProxyError('output_token_limit', 429)
    if 'instructions' in body and not isinstance(body['instructions'], str):
        raise ProxyError('schema_invalid', 422)
    items = body.get('input')
    if not isinstance(items, (str, list)) or not items:
        raise ProxyError('schema_invalid', 422)
    if isinstance(items, list):
        for item in items:
            if isinstance(item,dict):
                for key in ('id','call_id'):
                    if key in item and (not isinstance(item[key],str) or not re.fullmatch(r'(?:msg|rs|fc|call|fco)_[A-Za-z0-9_-]{1,160}',item[key])):
                        raise ProxyError('invalid_item_identifier',422)
        if len(items) > 100:
            raise ProxyError('too_many_items', 422)
        for item in items:
            if not isinstance(item, dict):
                raise ProxyError('schema_invalid', 422)
            kind = item.get('type', 'message')
            if kind == 'message':
                if set(item) - {'type','role','content','id','status','phase'} or item.get('role') not in ('user','assistant','system','developer'):
                    raise ProxyError('unsupported_input_item', 422)
                content = item.get('content')
                if not isinstance(content, (str,list)):
                    raise ProxyError('schema_invalid', 422)
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict) or part.get('type') not in ('input_text','output_text') or not isinstance(part.get('text'), str):
                            raise ProxyError('only_text_input_supported', 422)
                        if set(part) - {'type','text','annotations','logprobs'}:
                            raise ProxyError('schema_invalid', 422)
                        if part.get('annotations') or part.get('logprobs'):
                            raise ProxyError('input_annotations_not_supported', 422)
            elif kind == 'function_call':
                if set(item) - {'type','id','call_id','name','arguments','status'} or not all(isinstance(item.get(k),str) for k in ('call_id','name','arguments')):
                    raise ProxyError('schema_invalid', 422)
                try:
                    if not isinstance(json.loads(item['arguments']), dict): raise ValueError()
                except ValueError: raise ProxyError('invalid_function_arguments', 422)
            elif kind == 'function_call_output':
                if set(item) - {'type','id','call_id','output','status'} or not isinstance(item.get('call_id'),str) or not isinstance(item.get('output'),str):
                    raise ProxyError('only_text_tool_output_supported', 422)
            elif kind == 'reasoning':
                if set(item) - {'type','id','summary','content','encrypted_content','status'} or not isinstance(item.get('summary',[]),list):
                    raise ProxyError('schema_invalid', 422)
                if item.get('content') not in (None,[]):
                    raise ProxyError('reasoning_plaintext_not_supported',422)
                for part in item.get('summary',[]):
                    if not isinstance(part,dict) or set(part) != {'type','text'} or part['type'] != 'summary_text' or not isinstance(part['text'],str):
                        raise ProxyError('schema_invalid', 422)
                if 'encrypted_content' in item and not isinstance(item['encrypted_content'],str):
                    raise ProxyError('schema_invalid', 422)
            else:
                raise ProxyError('unsupported_input_item', 422)
    tools = body.get('tools', [])
    if not isinstance(tools, list) or len(tools) > 32:
        raise ProxyError('schema_invalid', 422)
    for tool in tools:
        if not isinstance(tool,dict) or tool.get('type') != 'function' or set(tool) - {'type','name','description','parameters','strict'}:
            raise ProxyError('only_client_functions_supported', 422)
        if not isinstance(tool.get('name'),str) or not isinstance(tool.get('parameters'),dict):
            raise ProxyError('schema_invalid', 422)
    choice = body.get('tool_choice', 'auto')
    if isinstance(choice,dict):
        if set(choice) != {'type','name'} or choice['type'] != 'function' or choice['name'] not in [t['name'] for t in tools]:
            raise ProxyError('schema_invalid', 422)
    elif choice not in ('auto','none','required'):
        raise ProxyError('schema_invalid', 422)
    if body.get('include',[]) not in ([], ['reasoning.encrypted_content']):
        raise ProxyError('unsupported_include', 422)
    for k in ('reasoning','text'):
        if k in body and not isinstance(body[k],dict): raise ProxyError('schema_invalid',422)
    for k,upper in (('temperature',2),('top_p',1)):
        if k in body and (type(body[k]) not in (int,float) or not 0 <= body[k] <= upper):
            raise ProxyError('schema_invalid',422)
    if 'reasoning' in body:
        r=body['reasoning']
        if set(r)-{'effort','summary'} or ('effort' in r and r['effort'] not in ('none','minimal','low','medium','high','xhigh')) or ('summary' in r and r['summary'] not in ('auto','concise','detailed')):
            raise ProxyError('schema_invalid',422)
    # Bounded JSON also rejects NaN/Infinity before any upstream request.
    try:
        if len(encode(body).encode()) > 128_000: raise ProxyError('body_too_large',413)
    except (ValueError,TypeError,RecursionError,UnicodeError):
        raise ProxyError('schema_invalid',422)
    result=deepcopy(body)
    result.update(store=False, stream=False, max_output_tokens=cap)
    return result


def strings(value, path=()):
    """Content projections; opaque IDs/ciphertext are preserved, never PII-redacted as text."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for i,item in enumerate(value): yield from strings(item, path+(i,))
    elif isinstance(value, dict):
        for key,item in value.items():
            if key in ('id','call_id','type','role','status','phase','encrypted_content','model'):
                continue
            yield from strings(item, path+(key,))


def replace_at(value, path, text):
    if not path: return text
    target=value
    for key in path[:-1]: target=target[key]
    target[path[-1]]=text
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


class OpenAITransport:
    def __init__(self, environ):
        # The default key is the key the owner already provided, not a client parameter.
        self.key=(environ.get('OPENAI_API_KEY') or environ.get('DETECTOR_PROVIDER_API_KEY') or '').strip()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(self, payload, deadline, invocation_id):
        if not self.key: raise ProxyError('provider_not_configured',503)
        req=urllib.request.Request('https://api.openai.com/v1/responses', data=encode(payload).encode(),
            headers={'Authorization':'Bearer '+self.key, 'Content-Type':'application/json',
                     'Accept':'application/json','X-Client-Request-Id':invocation_id}, method='POST')
        remaining=deadline-time.monotonic()
        if remaining <= 0: raise ProxyError('provider_deadline_exceeded',504)
        try:
            with self.opener.open(req, timeout=remaining) as response:
                chunks=[]; size=0
                while True:
                    if time.monotonic() >= deadline: raise ProxyError('provider_deadline_exceeded',504)
                    if response.isclosed(): break
                    # A slow chunk must not restart the original full socket timeout.
                    response.fp.raw._sock.settimeout(max(0.001,deadline-time.monotonic()))
                    chunk=response.read1(min(65536,MAX_RESPONSE_BYTES+1-size))
                    if not chunk: break
                    size+=len(chunk); chunks.append(chunk)
                    if size>MAX_RESPONSE_BYTES: raise ProxyError('provider_response_too_large',502)
                data=json.loads(b''.join(chunks))
                request_id=response.headers.get('x-request-id','')
                return data, request_id
        except urllib.error.HTTPError as exc:
            code='provider_rate_limited' if exc.code==429 else ('provider_authentication_failed' if exc.code in (401,403) else 'provider_request_failed')
            exc.close()
            raise ProxyError(code,502) from None
        except (TimeoutError,socket.timeout): raise ProxyError('provider_deadline_exceeded',504) from None
        except (urllib.error.URLError,OSError): raise ProxyError('provider_unavailable',502) from None
        except (ValueError,UnicodeError): raise ProxyError('provider_response_invalid',502) from None


def usage_of(response):
    u=response.get('usage')
    if not isinstance(u,dict) or any(type(u.get(k)) is not int or u[k]<0 for k in ('input_tokens','output_tokens','total_tokens')):
        raise ProxyError('provider_usage_missing',502)
    if u['total_tokens'] != u['input_tokens']+u['output_tokens']:
        raise ProxyError('provider_usage_invalid',502)
    return u


@dataclass
class Reply:
    status: int
    body: dict
    headers: tuple=()
    stream: bool=False


class ModelProxy:
    def __init__(self, gateway, panel, environ, transport=None):
        self.gateway=gateway; self.repo=gateway.repository; self.panel=panel
        self.transport=transport or OpenAITransport(environ)
        self.environ=environ

    def _panel_admit(self, payload, principal, reserve, now, fingerprint):
        with self.panel._transaction() as state:
            policy=deepcopy(state['policy'])
            # Model allowlist is compulsory at this public ingress even if the UI node is disabled.
            allowlists=[n['models'] for n in policy['checks'] if n['type']=='allowed_models' and n['mode']=='block']
            if not allowlists or not all(payload['model'] in models for models in allowlists):
                raise ProxyError('model_not_allowed',403)
            recent=[x for x in state.get('modelProxyAttempts',[]) if x['at']>now-60]
            day=utc_day_key(); key=principal.id+':'+day
            usage=state.setdefault('modelProxyAdmissionUsage',{})
            context={'rpm':1+sum(x['principal']==principal.id for x in recent),
                     'similar':1+sum(x['principal']==principal.id and x['hash']==fingerprint for x in recent),
                     'tokens_used':usage.get(key,0),'tokens_requested':reserve}
            # Whole-input check detects patterns crossing fields. Leaf checks below preserve JSON.
            projection='\n'.join(text for _,text in strings(payload))
            evaluated=evaluate(policy,{'agent':principal.id,'dir':'input','target':payload['model'],'text':projection},context=context)
            if evaluated['decision'] in ('block','throttle'):
                raise ProxyError('panel_'+str(evaluated.get('triggerType') or 'policy_denied'),429 if evaluated['decision']=='throttle' else 403)
            recent.append({'at':now,'principal':principal.id,'hash':fingerprint})
            state['modelProxyAttempts']=recent
            # Conservative admission units, separate from actual token ledger; no refund on failure.
            usage[key]=usage.get(key,0)+reserve
            state['modelProxyAdmissionUsage']={k:v for k,v in usage.items() if k.endswith(':'+day)}
            return policy,policy_hash(policy)

    def invoke(self, body, principal):
        iid=str(uuid.uuid4()); started=time.monotonic(); trail=AuditTrail(iid)
        headers=(('X-Action-Gate-Invocation-Id',iid),)
        reserved=False; snapshot=None; plan=None; resolved=None; panel_hash=None; decision='allow'; disclosure='none'
        dispatch_intent=False; dispatched=False; usage=None; response=None; reason=None; semantic_calls=[]; semantic_attempt=False
        out_redacted=False; input_redacted=False; panel_policy=None
        fingerprint=keyed_hash(encode(body),self.gateway.salt)
        trail.record('invocation_received',service='openai',action='responses',requestHash=fingerprint)
        def persist(status, public, final=False):
            outcome='succeeded' if response is not None else ('unknown' if dispatched or (dispatch_intent and not final) else 'not_started')
            record={'invocation_id':iid,'idempotency_key':'model:'+iid,'principal_id':principal.id,'principal_role':principal.role,
                'service_id':'openai','action_id':'responses','request_hash':fingerprint,
                'release_hash':snapshot.release_hash if snapshot else 'unknown','decision':decision,
                'action_outcome':outcome,'disclosure':disclosure,'reasons':[reason] if reason else [],'findings':[],
                'semantic_status':('available' if semantic_calls and all(x['status']=='available' for x in semantic_calls) else 'not_run'),
                'semantic_risk':None,'detector_profile':resolved['profile']['id'] if resolved else 'unset',
                'latency_ms':int((time.monotonic()-started)*1000),'dry_run':False,
                'budget_scope':plan.scope_id if plan else '',
                'response':{'invocationId':iid,'status':status,'provider':'openai','model':body.get('model') if isinstance(body,dict) else None,
                    'providerResponseId':response.get('id') if response else None,'usage':usage,
                    'panelPolicyHash':panel_hash,'policyRelease':snapshot.release_hash if snapshot else None,
                    'inputRedacted':input_redacted,'outputRedacted':out_redacted,'reason':reason}}
            self.repo.save_model_checkpoint(record,trail.rows())
        def check(value,direction):
            nonlocal input_redacted,out_redacted
            value=deepcopy(value)
            policy=to_jsonable(snapshot.content_policy); policy['allowed_models']=[body['model']]
            policy['controls']['semantic']=False
            guard=ContentGate(policy,snapshot.signatures,snapshot.component_hashes['contentPolicy'],snapshot.component_hashes['signatureFeed'])
            # User-defined schema/property keys are content too, but cannot be safely rewritten.
            def keys(obj):
                if isinstance(obj,dict):
                    for k,v in obj.items():
                        yield k
                        yield from keys(v)
                elif isinstance(obj,list):
                    for v in obj: yield from keys(v)
            for key in keys(value):
                checked=guard.inspect(key,body['model'],direction)
                panel_key=evaluate(panel_policy,{'agent':principal.id,'dir':direction,'target':body['model'],'text':key})
                if checked.decision in ('block','redact') or panel_key['decision'] in ('block','redact','throttle'):
                    raise ProxyError('unsafe_structural_key')
            # Always evaluate the complete projection, then each leaf to retain the wire structure.
            projection='\n'.join(text for _,text in strings(value))
            combined=guard.inspect(projection,body['model'],direction)
            if combined.decision=='block': raise ProxyError(combined.reasons[0])
            aggregate=evaluate(panel_policy,{'agent':principal.id,'dir':direction,'target':body['model'],'text':projection})
            if aggregate['decision'] in ('block','throttle'): raise ProxyError('panel_'+str(aggregate.get('triggerType') or 'policy_denied'))
            redacted=False
            for path,text in list(strings(value)):
                a=guard.inspect(text,body['model'],direction)
                if a.decision=='block': raise ProxyError(a.reasons[0])
                b=evaluate(panel_policy,{'agent':principal.id,'dir':direction,'target':body['model'],'text':a.text})
                if b['decision'] in ('block','throttle'): raise ProxyError('panel_'+str(b.get('triggerType') or 'policy_denied'))
                cleaned=b['processed']
                if cleaned!=text:
                    # Names and schema definitions cannot safely be rewritten; fail closed.
                    if 'parameters' in path or 'name' in path or 'format' in path:
                        raise ProxyError('structural_content_redaction_required')
                    value=replace_at(value,path,cleaned); redacted=True
            if (combined.decision=='redact' or aggregate['decision']=='redact') and not redacted:
                raise ProxyError('cross_field_redaction_required')
            if direction=='input': input_redacted|=redacted
            else: out_redacted|=redacted
            return value
        try:
            payload=validate_request(body)
            snapshot=self.gateway.snapshot()
            headers+=(('X-Action-Gate-Policy-Release',snapshot.release_hash),)
            profile=self.environ.get('MODEL_PROXY_DETECTOR_PROFILE') or snapshot.detectors['default']
            resolved=self.gateway._resolve_detector(snapshot,profile)
            scope=snapshot.budget_scope()
            reserve=snapshot.budgets['reserve']
            deadline=started+reserve['globalDeadlineMs']/1000
            # Byte-based upper allowance, not a measured tokenizer count. Structured overhead included.
            target_tokens=len(encode(payload).encode())+1024+payload['max_output_tokens']
            semantic_enabled=snapshot.content_policy['controls']['semantic']
            semantic_cap=0
            if semantic_enabled:
                from .detectors import render_instruction
                semantic_cap=(len(encode(payload).encode())+4*payload['max_output_tokens']+
                              2*len(render_instruction().encode())+2*(resolved.get('completion_token_cap') or 256)+2048)
            rate=int(snapshot.budgets['estimation']['costMicroPerToken'].get('provider-chat-v1',50))
            if rate<=0: raise ProxyError('provider_budget_rate_unconfigured',503)
            tokens=target_tokens+semantic_cap
            plan=BudgetPlan(str(uuid.uuid4()),scope['id'],utc_day_key(),tokens,tokens*rate,reserve['globalDeadlineMs'])
            panel_policy,panel_hash=self._panel_admit(payload,principal,tokens,time.time(),fingerprint)
            headers+=(('X-Action-Gate-Panel-Policy',panel_hash),)
            payload=check(payload,'input')
            payload=validate_request(payload)
            if not getattr(self.transport,'key',True): raise ProxyError('provider_not_configured',503)
            self.repo.ensure_ledger(scope['id'],plan.period_key,scope['limits'],snapshot.activation_generation)
            if self.repo.reserve_budget(plan,scope['limits']) is None:
                plan=None; raise ProxyError('budget_exceeded',429)
            reserved=True
            self.repo.record_reservation_context(plan.reservation_id,{'invocation_id':iid,'release_hash':snapshot.release_hash,'activation_generation':snapshot.activation_generation})
            trail.record('release_pinned',release=snapshot.release_hash,panelPolicyHash=panel_hash,generation=snapshot.activation_generation)
            trail.record('budget_reserved',tokens=tokens,costMicro=tokens*rate,pricingKind='conservative_configured_allowance')
            persist(102,{},False)  # Prove audit storage before any external work.
            def semantic(value,direction,until):
                nonlocal semantic_attempt
                if not semantic_enabled: return
                if time.monotonic()>=until: raise ProxyError('semantic_deadline_exceeded',504)
                semantic_attempt=True
                projection='\n'.join(text for _,text in strings(value))
                policy=to_jsonable(snapshot.content_policy);policy['allowed_models']=[body['model']]
                result=self.gateway._inspect(snapshot,resolved,projection,body['model'],direction,until,policy_override=policy)
                if result.semantic: semantic_calls.append(result.semantic)
                trail.record('semantic_evaluation',result.decision,direction=direction,status=result.semantic_status,profile=profile,
                             usageTokens=(result.semantic or {}).get('usageTokens'),mode=(result.semantic or {}).get('mode'))
                if result.decision=='block':
                    raise ProxyError(result.reasons[0],503 if result.semantic_status=='unavailable' else 403)
            target_deadline=min(started+reserve['targetTimeMs']/1000,deadline-reserve['outputTimeMs']/1000)
            semantic(payload,'input',target_deadline)
            if target_deadline-time.monotonic()<reserve['minTargetWindowMs']/1000: raise ProxyError('provider_deadline_exceeded',504)
            trail.record('input_controls','redact' if input_redacted else 'allow',outboundHash=keyed_hash(encode(payload),self.gateway.salt))
            trail.record('dispatch_started',provider='openai',model=body['model'])
            dispatch_intent=True
            persist(102,{},False)
            dispatched=True
            raw,provider_request_id=self.transport.call(payload,target_deadline,iid)
            if not isinstance(raw,dict) or raw.get('object')!='response' or not isinstance(raw.get('output'),list) or not raw.get('id'):
                raise ProxyError('provider_response_invalid',502)
            response=raw;usage=usage_of(response)
            if raw.get('model')!=body['model'] and not str(raw.get('model','')).startswith(body['model']+'-'):
                raise ProxyError('provider_model_mismatch',502)
            trail.record('dispatch_finished','succeeded',providerRequestId=provider_request_id,providerResponseId=raw['id'],usageTokens=usage['total_tokens'])
            # Do not expose the echoed request or opaque reasoning ciphertext after redaction.
            cleaned=check(raw['output'],'output')
            semantic(cleaned,'output',deadline)
            if time.monotonic()>deadline: raise ProxyError('output_deadline_exceeded',504)
            for item in cleaned:
                if item.get('type')=='function_call':
                    try: json.loads(item['arguments'])
                    except (ValueError,KeyError): raise ProxyError('redacted_function_arguments_invalid',502)
            # Forward the supported wire envelope only. Do not relay arbitrary provider metadata.
            safe_fields={'id','object','created_at','status','model','usage','parallel_tool_calls',
                         'max_output_tokens','store','service_tier','temperature','top_p'}
            result={key:deepcopy(value) for key,value in raw.items() if key in safe_fields}
            result['output']=cleaned
            result['error']=error_body('provider_response_failed')['error'] if raw.get('error') else None
            result['incomplete_details']=None
            if raw.get('status')=='incomplete':
                incomplete_reason=(raw.get('incomplete_details') or {}).get('reason')
                if incomplete_reason not in ('max_output_tokens','content_filter'):
                    raise ProxyError('provider_incomplete_reason_invalid',502)
                result['incomplete_details']={'reason':incomplete_reason}
            # These echoed fields can otherwise disclose the original input or bypass output checks.
            for key in ('instructions','tools','text','metadata','prompt','input','reasoning'):
                if key in result: result[key]=None if key not in ('tools','metadata') else ([] if key=='tools' else {})
            if input_redacted or out_redacted:
                for item in result['output']: item.pop('encrypted_content',None)
            disclosure='redacted' if out_redacted else 'full'
            decision='redact' if input_redacted else 'allow'
            trail.record('output_controls','redact' if out_redacted else 'allow')
            status=200
        except ProxyError as exc:
            reason=exc.code;status=exc.status;decision=('redact' if input_redacted else 'allow') if dispatched else 'block';disclosure='withheld' if dispatched else 'none';result=error_body(reason)
        except Exception as exc:
            print(encode({'modelProxyFailure':type(exc).__name__,'invocationId':iid}),file=sys.stderr)
            # No arbitrary exception details reach the client or audit.
            reason='dependency_unavailable';status=503;decision=('redact' if input_redacted else 'allow') if dispatched else 'block';result=error_body(reason)
            disclosure='withheld' if dispatched else 'none'
        try:
            if reserved:
                actual_semantic=sum(x.get('usageTokens') or 0 for x in semantic_calls)
                known=not dispatched or usage is not None
                known=known and all(x.get('usageStatus') in ('reported','estimated','replayed','known') for x in semantic_calls)
                if semantic_attempt and not semantic_calls: known=False
                charged=(usage['total_tokens'] if usage else 0)+actual_semantic if known else plan.tokens
                self.repo.commit_budget(plan.reservation_id,charged,charged*rate,int((time.monotonic()-started)*1000),known)
                trail.record('budget_committed',usageTokens=charged,usageKnown=known,costMicro=charged*rate,pricingKind='conservative_configured_allowance')
            if dispatched:
                self.repo.record_effect({'invocation_id':iid,'service_id':'openai','action_id':'responses',
                    'outcome':'succeeded' if response is not None else 'unknown',
                    'result_bytes':len(encode(response).encode()) if response is not None else 0,
                    'detail':{'provider':'openai','responseId':response.get('id') if response else None}})
            trail.record('invocation_completed' if status==200 else 'invocation_blocked',decision,reasons=[reason] if reason else [],dispatchCount=int(dispatched))
            persist(status,result,True)
        except Exception:
            return Reply(503,error_body('audit_or_budget_not_persisted'),headers)
        return Reply(status,result,headers,stream=bool(body.get('stream')) and status==200)


def sse(response):
    """Emit a buffered, checked Responses event sequence; no upstream byte is forwarded raw."""
    events=[]
    def emit(kind,**values): events.append({'type':kind,'sequence_number':len(events),**values})
    initial={**response,'status':'in_progress','output':[],'usage':None}
    emit('response.created',response=initial);emit('response.in_progress',response=initial)
    for i,item in enumerate(response['output']):
        empty={**item,'status':'in_progress'}
        if item['type']=='message': empty['content']=[]
        elif item['type']=='function_call': empty['arguments']=''
        emit('response.output_item.added',output_index=i,item=empty)
        if item['type']=='message':
            for j,part in enumerate(item.get('content',[])):
                emit('response.content_part.added',item_id=item['id'],output_index=i,content_index=j,part={**part,'text':''} if 'text' in part else part)
                if part.get('type')=='output_text':
                    emit('response.output_text.delta',item_id=item['id'],output_index=i,content_index=j,delta=part['text'],logprobs=[])
                    emit('response.output_text.done',item_id=item['id'],output_index=i,content_index=j,text=part['text'],logprobs=[])
                emit('response.content_part.done',item_id=item['id'],output_index=i,content_index=j,part=part)
        elif item['type']=='function_call':
            emit('response.function_call_arguments.delta',item_id=item['id'],output_index=i,delta=item['arguments'])
            emit('response.function_call_arguments.done',item_id=item['id'],output_index=i,arguments=item['arguments'])
        emit('response.output_item.done',output_index=i,item=item)
    terminal={'completed':'response.completed','incomplete':'response.incomplete','failed':'response.failed'}.get(response.get('status'),'response.failed')
    emit(terminal,response=response)
    return ''.join('event: '+e['type']+'\ndata: '+encode(e)+'\n\n' for e in events)
