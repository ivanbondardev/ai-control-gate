"""Operator-only: allow the configured OpenAI model through the panel's compare/activate API."""
from copy import deepcopy
import json
import os
from .mcp_bootstrap import Bootstrap


def configure_deadlines(bootstrap):
    """Compare/activate a realistic bounded model window, preserving all daily caps."""
    from .snapshot import to_jsonable
    from .contracts import parse_evaluation
    from .evaluation import EvaluationRequest
    service=bootstrap.core.config_service
    active=service.snapshot()
    budgets=to_jsonable(active.budgets)
    reserve=budgets['reserve']
    wanted={'targetTimeMs':15000,'outputTimeMs':4000,'globalDeadlineMs':20000}
    if all(reserve[key]>=value for key,value in wanted.items()):
        return {'changed':False}
    for key,value in wanted.items(): reserve[key]=max(reserve[key],value)
    reserve['globalDeadlineMs']=max(reserve['globalDeadlineMs'],reserve['targetTimeMs']+reserve['outputTimeMs'])
    draft=service.create_draft(documents={'budgets':budgets},created_by='operator-local',source='model-proxy-setup')
    candidate,payload=service.candidate_from_draft(draft.draft_id,draft.revision)
    model=active.content_policy['allowed_models'][0]
    samples=[('neutral','Explain access controls.'),('secret','sk-SYNTHETICONLY000000000000000000000000000000'),('signature','pickle.loads(untrusted_blob)')]
    resolved=bootstrap.core.gateway._resolve_detector(active,active.detectors['default'])
    cases=[]
    for id,text in samples:
        outcome=bootstrap.core.gateway._inspect(active,resolved,text,model,'input',None)
        cases.append({'id':id,'text':text,'model':model,'expected':{'decision':outcome.decision}})
    request=parse_evaluation({'cases':cases})
    request=EvaluationRequest(cases=request.cases,detector_profile=active.detectors['default'],
        candidate={'documents':payload,'revision':draft.revision,'hash':candidate.release_hash})
    status,result=bootstrap.core.gateway.evaluate(request)
    if status!=200 or result.get('status')!='complete' or not result.get('passed'):
        raise SystemExit('Deadline comparison did not pass; active limits were not changed')
    eid=service.record_evaluation(result,active=active,candidate_hash=candidate.release_hash,
        candidate_revision=draft.revision,dataset_hash=None,detector_profile=active.detectors['default'],actor='operator-local')
    activated=service.activate(draft_id=draft.draft_id,expected_revision=draft.revision,
        expected_generation=active.activation_generation,evaluation_id=eid,operation_key=None,
        actor='operator-local',reason='Bounded real OpenAI window with reserved output-control time')
    return {'changed':True,'comparison':eid,'generation':activated['active']['activationGeneration'],'reserve':reserve}


def main():
    model=os.environ.get('MODEL_PROXY_MODEL') or os.environ.get('DETECTOR_PROVIDER_MODEL')
    if not model:
        raise SystemExit('Set MODEL_PROXY_MODEL to the model to allow')
    bootstrap=Bootstrap()
    state=bootstrap.state()
    policy=deepcopy(state['policy'])
    nodes=[n for n in policy['checks'] if n['type']=='allowed_models']
    if not nodes: raise SystemExit('The panel needs an allowed_models control')
    for node in nodes:
        if node['mode']!='block': raise SystemExit('Enable the panel model allowlist in block mode first')
        if model not in node['models']: node['models'].append(model)
    tests=deepcopy(state['tests'])
    ids={t['id'] for t in tests}
    for entry in [
        {'id':'openai-model-allowed','name':'Real configured OpenAI model is allowed','agent':'support-agent','dir':'input','target':model,'text':'Say hello.','expected':'allow'},
        {'id':'openai-model-denied','name':'Unknown model remains denied','agent':'support-agent','dir':'input','target':'gate-test-denied-model','text':'Say hello.','expected':'block'}]:
        if entry['id'] not in ids: tests.append(entry)
    result=bootstrap.compare_and_activate(policy,tests,'Enable the owner-authorized OpenAI Responses proxy model')
    deadlines=configure_deadlines(bootstrap)
    print(json.dumps({'model':model,'activation':result,'deadlines':deadlines},default=str))


if __name__=='__main__':main()
