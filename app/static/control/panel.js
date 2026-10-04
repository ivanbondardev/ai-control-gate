/* ===================== constants ===================== */
const AGENTS=['support-bot','research-agent','code-assistant','finance-copilot'];
const MODELS=['llama3.1:8b','qwen2.5:7b'];
const KIND_LABEL={rule:'Rule',ai:'AI check',access:'Access',stage:'Service rules',signature:'Signature feed',budget:'Budget'};
const MODE_LABEL={block:'Block',redact:'Redact',throttle:'Throttle',monitor:'Monitor',off:'Off',enforce:'Enforce',allow:'Allow'};
const DEC_LABEL={pending:'Not run',allow:'Allowed',redact:'Redacted',block:'Blocked',throttle:'Throttled',monitor:'Monitored'};
const DIR_LABEL={input:'Prompt',output:'Answer',tool_call:'Service call'};
const RANK={allow:0,monitor:1,redact:2,throttle:3,block:4};
const OPS={eq:'equals',neq:'does not equal',contains:'contains',not_contains:'does not contain',starts_with:'starts with',lte:'≤',gte:'≥',email_domain_eq:'email domain is'};
const GLYPH={
  rule:'<svg viewBox="0 0 14 14"><path d="M3 12L7 2M7 12l4-10" stroke="currentColor" stroke-width="1.6" fill="none"/></svg>',
  ai:'<svg viewBox="0 0 14 14"><path d="M7 1l1.5 4.5L13 7l-4.5 1.5L7 13l-1.5-4.5L1 7l4.5-1.5z" fill="currentColor"/></svg>',
  access:'<svg viewBox="0 0 14 14"><circle cx="4.5" cy="7" r="2.6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M7 7h6M11 7v2.5" stroke="currentColor" stroke-width="1.5"/></svg>',
  stage:'<svg viewBox="0 0 14 14"><rect x="1.5" y="2" width="11" height="3" fill="none" stroke="currentColor" stroke-width="1.4"/><rect x="1.5" y="9" width="11" height="3" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>',
  signature:'<svg viewBox="0 0 14 14"><path d="M7 1l5 2v4c0 3-2.2 5-5 6-2.8-1-5-3-5-6V3z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
  budget:'<svg viewBox="0 0 14 14"><path d="M2 11a5 5 0 1 1 10 0" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M7 11l2.5-4" stroke="currentColor" stroke-width="1.5"/></svg>',
  service:'<svg viewBox="0 0 14 14"><rect x="2" y="2" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5 7h4M7 5v4" stroke="currentColor" stroke-width="1.5"/></svg>'
};
const NODE_TYPES={
  secrets_detection:{label:'Secrets detection',group:'Deterministic rules',kind:'rule',modes:['block','redact','monitor','off'],desc:'Finds API keys, tokens and private keys with patterns. Patterns cannot catch every secret.',defaults:{mode:'redact'}},
  pii_detection:{label:'Personal data detection',group:'Deterministic rules',kind:'rule',modes:['block','redact','monitor','off'],desc:'Finds emails, phone numbers, PESEL, IBAN and card numbers.',defaults:{mode:'redact',entities:['email','phone','pesel','iban']}},
  regex_pattern:{label:'Custom pattern',group:'Deterministic rules',kind:'rule',modes:['block','redact','monitor','off'],desc:'Your own regular expressions, one per line.',defaults:{mode:'block',patterns:['(?i)internal use only']}},
  allowed_models:{label:'Allowed models',group:'Access',kind:'access',modes:['block','monitor','off'],desc:'Prompts can only go to these models.',defaults:{mode:'block',models:['llama3.1:8b','qwen2.5:7b']}},
  denied_paths:{label:'Denied paths',group:'Access',kind:'access',modes:['block','monitor','off'],desc:'Service calls whose arguments contain these paths are stopped.',defaults:{mode:'block',deny_paths:['.aws/credentials','/etc/shadow','.env']}},
  service_access:{label:'Service access rules',group:'Access',kind:'stage',modes:['enforce','monitor','off'],desc:'Applies the rules from the Service rules tab to every service call.',defaults:{mode:'enforce'}},
  signature_feed:{label:'Known exploit signatures',group:'Signature feed',kind:'signature',modes:['block','monitor','off'],desc:'Local signature patterns detect known risky loaders and payloads. External feed refresh is not connected.',defaults:{mode:'block',feed:'signatures.internal/ai-exploits',refresh_minutes:60}},
  rate_limit:{label:'Rate limit',group:'Budget',kind:'budget',modes:['throttle','block','monitor','off'],desc:'Refuses admission above the limit; the caller receives a retry-after duration. No automatic retry or dispatch occurs.',defaults:{mode:'throttle',max_per_minute:30,delay_ms:2000}},
  token_budget:{label:'Token budget',group:'Budget',kind:'budget',modes:['throttle','block','monitor','off'],desc:'Daily estimated input-token admission limit per synthetic agent, reset at 00:00 UTC. No provider is billed.',defaults:{mode:'throttle',daily_tokens:1000000}},
  loop_detector:{label:'Runaway loop detector',group:'Budget',kind:'budget',modes:['block','throttle','monitor','off'],desc:'Stops sessions that repeat the same call again and again.',defaults:{mode:'block',max_similar_per_minute:30}},
  semantic:{label:'AI classification',group:'AI checks',kind:'ai',modes:['enforce','monitor','off'],desc:'The offline baseline returns a label. Model and instruction settings are retained for future model integration.',
    defaults:{mode:'enforce',classifier:'custom',applies_to:'input',model:'llama3.1:8b',instruction_version:1,instruction:'Classify the message. Answer with exactly one word: safe or unsafe.',labels:[{label:'safe',reaction:'allow'},{label:'unsafe',reaction:'block'}],on_unknown:'block',on_timeout:'block',timeout_ms:800}}
};
const CHECK_KEYS=['classifier','entities','patterns','models','deny_paths','fields','feed','refresh_minutes','max_per_minute','delay_ms','daily_tokens','max_similar_per_minute','applies_to','model','instruction_version','instruction','labels','on_unknown','on_timeout','timeout_ms','exceptions'];

/* ===================== helpers ===================== */
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clone=o=>o===undefined?undefined:JSON.parse(JSON.stringify(o));
const stableJson=value=>JSON.stringify(value,(_,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
const t2=d=>d.toTimeString().slice(0,8);
const ago=d=>{const s=(Date.now()-d)/1000;if(s<60)return 'just now';if(s<3600)return Math.floor(s/60)+' min ago';if(s<86400)return Math.floor(s/3600)+' h ago';return 'yesterday'};
const ms=v=>v<10?v.toFixed(1)+' ms':Math.round(v)+' ms';
const fmt=n=>Number(n).toLocaleString('en-US');
const subj=s=>s==='*'?'Any agent':s;
const act=a=>a==='*'?'any action':a;
const ruleLabel=r=>`${subj(r.subject)} → ${r.service}.${r.action==='*'?'*':r.action}`;
const condText=c=>`${c.param} ${OPS[c.op]||c.op} ${c.value}`;
const renderCall=(svc,action,params)=>`${svc}.${action}(${Object.entries(params||{}).map(([k,v])=>`${k}=${typeof v==='number'?v:JSON.stringify(v)}`).join(', ')})`;

function mk(id,type,extra={}){return Object.assign({id,type,name:NODE_TYPES[type].label},clone(NODE_TYPES[type].defaults),extra)}
function toRegex(p){const ci=p.startsWith('(?i)');return new RegExp(ci?p.slice(4):p,ci?'gi':'g')}
const SIM={};
const HITS={};
const BASE={allow:0,redact:0,block:0,throttle:0,monitor:0};
/* ===================== state ===================== */
const S={
  services:[],
  live:{version:0,checks:[],rules:[],default_reaction:'block'},draft:{version:0,checks:[],rules:[],default_reaction:'block'},history:[],events:[],tests:[],training:[],paused:false,
  filters:{status:'all',agent:'all',q:'',fp:false},trFilters:{check:'all',review:'all'},
  sel:'injection',selRule:'r1',selTest:null,selService:'documents',yaml:false,ext:null,replay:{},histSel:null,histTab:'ops',yamlErr:null,errs:null,tab:'checks',ruleSubject:'all'
};

/* Test and request data come from the authenticated server. */
let tid=Date.now();
function testReq(t){
  const svc=S.services.find(s=>s.id===t.service);const a=svc&&svc.actions.find(a=>a.name===t.action);const params={};
  Object.entries(t.params||{}).forEach(([k,v])=>{const p=a&&a.params.find(p=>p.name===k);params[k]=p&&p.type==='number'&&v!==''&&!isNaN(v)?Number(v):p&&p.type==='boolean'&&['true','false'].includes(v)?v==='true':v});
  return {agent:t.agent,dir:t.dir,target:t.target||null,service:t.service||null,action:t.action||null,params,text:t.dir==='tool_call'?renderCall(t.service,t.action,params):(t.text||''),meta:t.meta||{}};
}
function runTest(policy,t){
  const result=S.testResults&&S.testResults[t.id];
  const r=result&&(policy===S.live?result.live:result.draft);
  if(!r||S.testResultKey!==evaluationKey())return {pending:true,d:'pending',pass:false,r:{decision:'pending',checks:[],processed:null,version:S.live.version,triggerName:'Not evaluated',triggerDetail:'Run tests on the server.'}};
  const d=r.decision==='monitor'?'allow':r.decision;
  return {r,d,pass:d===t.expected&&!(t.expected==='redact'&&t.expected_output&&r.processed!==t.expected_output)};
}
function testSummary(t){return t.dir==='tool_call'?renderCall(t.service,t.action,t.params):`${DIR_LABEL[t.dir]} to ${t.target}: ${t.text}`}

/* ===================== diff / summaries ===================== */
function fmtVal(f,v){
  if(v===undefined||v===null)return 'none';
  if(v==='*')return 'any';
  if(f==='conditions')return v.length?v.map(condText).join(' and '):'none';
  if(f==='labels')return v.map(l=>`${l.label}: ${l.reaction}`).join(', ');
  if(f==='instruction')return '“'+String(v).slice(0,48)+(String(v).length>48?'…':'')+'”';
  if(Array.isArray(v)){if(v.every(x=>typeof x!=='object'))return v.length?v.join(', '):'empty';return v.length+' item'+(v.length===1?'':'s')}
  return String(v);
}
function listDiff(sec,A,B,label){
  const ops=[];const a=Object.fromEntries(A.map(n=>[n.id,n])),b=Object.fromEntries(B.map(n=>[n.id,n]));
  B.forEach((n,i)=>{if(!a[n.id])ops.push({op:'add',sec,id:n.id,label:label(n),item:clone(n),index:i})});
  A.forEach(n=>{if(!b[n.id])ops.push({op:'remove',sec,id:n.id,label:label(n),item:clone(n)})});
  A.forEach(n=>{const m=b[n.id];if(!m)return;const keys=new Set([...Object.keys(n),...Object.keys(m)]);keys.delete('id');
    keys.forEach(k=>{if(stableJson(n[k])!==stableJson(m[k]))ops.push({op:'change',sec,id:n.id,label:label(m),field:k,from:clone(n[k]),to:clone(m[k])})})});
  const ca=A.map(n=>n.id).filter(id=>b[id]),cb=B.map(n=>n.id).filter(id=>a[id]);
  if(ca.join()!==cb.join())ops.push({op:'order',sec,from:ca,to:cb});
  return ops;
}
function diff(a,b){
  const ops=[];
  if(a.default_reaction!==b.default_reaction)ops.push({op:'change',sec:'policy',id:'_default',label:'Calls without a matching rule',field:'default_reaction',from:a.default_reaction,to:b.default_reaction});
  return ops.concat(listDiff('check',a.checks,b.checks,n=>n.name),listDiff('rule',a.rules,b.rules,ruleLabel));
}
function describe(o){
  const pre=o.sec==='rule'?'rule ':'';
  if(o.op==='add')return `Added ${pre}${o.label}`;
  if(o.op==='remove')return `Removed ${pre}${o.label}`;
  if(o.op==='order')return o.sec==='rule'?'Changed the order of rules':'Changed the order of checks';
  if(o.field==='exceptions'){const f=o.from||[],t=o.to||[];if(t.length>f.length){const e=t[t.length-1];return `${o.label}: exception added (${e.agent||'any agent'}, “${e.match}”)`}return `${o.label}: exception removed`}
  const name=o.sec==='rule'?'Rule '+o.label:o.label;
  return `${name}: ${o.field.replace(/_/g,' ')} ${fmtVal(o.field,o.from)} → ${fmtVal(o.field,o.to)}`;
}
function summarize(ops){if(!ops.length)return 'No changes';const d=ops.slice(0,2).map(describe);return d.join('; ')+(ops.length>2?` and ${ops.length-2} more`:'')}
function rebase(oldLive,draft,newLive){
  const ops=diff(oldLive,draft);const r=clone(newLive);
  ops.forEach(o=>{
    if(o.sec==='policy'){r.default_reaction=o.to;return}
    const list=o.sec==='rule'?r.rules:r.checks;
    if(o.op==='add'&&!list.find(n=>n.id===o.id))list.splice(Math.min(o.index,list.length),0,clone(o.item));
    if(o.op==='remove'){const i=list.findIndex(n=>n.id===o.id);if(i>=0)list.splice(i,1)}
    if(o.op==='change'){const n=list.find(n=>n.id===o.id);if(n){if(o.to===undefined)delete n[o.field];else n[o.field]=clone(o.to)}}
  });
  const sortBy=(list,src)=>{const order=src.map(n=>n.id);list.sort((x,y)=>{const a=order.indexOf(x.id),b=order.indexOf(y.id);return (a<0?999:a)-(b<0?999:b)})};
  sortBy(r.checks,draft.checks);sortBy(r.rules,draft.rules);return r;
}
function lineDiff(a,b){
  const A=a.split('\n'),B=b.split('\n'),m=A.length,n=B.length;const L=Array.from({length:m+1},()=>new Int16Array(n+1));
  for(let i=m-1;i>=0;i--)for(let j=n-1;j>=0;j--)L[i][j]=A[i]===B[j]?L[i+1][j+1]+1:Math.max(L[i+1][j],L[i][j+1]);
  const out=[];let i=0,j=0;while(i<m&&j<n){if(A[i]===B[j]){out.push(['c',A[i]]);i++;j++}else if(L[i+1][j]>=L[i][j+1])out.push(['d',A[i++]]);else out.push(['a',B[j++]])}
  while(i<m)out.push(['d',A[i++]]);while(j<n)out.push(['a',B[j++]]);return out;
}

/* ===================== YAML ===================== */
function toYamlObj(p){
  return {version:p.version,default_reaction:p.default_reaction,
    checks:p.checks.map(n=>{const o={id:n.id,type:n.type,name:n.name,mode:n.mode};CHECK_KEYS.forEach(k=>{if(n[k]!==undefined&&!(Array.isArray(n[k])&&!n[k].length))o[k]=n[k]});return o}),
    rules:p.rules.map(r=>{const o={id:r.id,subject:r.subject,service:r.service,action:r.action};if((r.conditions||[]).length)o.conditions=r.conditions;o.reaction=r.reaction;if(r.note)o.note=r.note;return o})};
}
function dump(p){return jsyaml.dump(toYamlObj(p),{lineWidth:-1,noRefs:true})}
function fromYaml(text){
  const o=jsyaml.load(text);
  if(!o||typeof o!=='object')throw new Error('The file is empty or not a mapping.');
  if(!Array.isArray(o.checks))throw new Error('“checks” must be a list.');
  const ids=new Set();
  const checks=o.checks.map((n,i)=>{
    if(!n||typeof n!=='object')throw new Error(`Check ${i+1} is not a mapping.`);
    if(typeof n.id!=='string'||!/^[A-Za-z0-9_.:-]{1,128}$/.test(n.id))throw new Error(`Check ${i+1} needs an id with letters, digits, dots, colons, hyphens or underscores.`);
    if(ids.has(n.id))throw new Error(`Id “${n.id}” is used twice.`);ids.add(n.id);
    const def=NODE_TYPES[n.type];if(!def)throw new Error(`Check “${n.id}” has unknown type “${n.type}”.`);
    if(n.mode&&!def.modes.includes(n.mode))throw new Error(`Check “${n.id}”: mode “${n.mode}” is not allowed. Use ${def.modes.join(', ')}.`);
    return Object.assign({id:String(n.id),type:n.type,name:n.name||def.label},clone(def.defaults),n);
  });
  const rules=(o.rules||[]).map((r,i)=>{
    if(!r||typeof r!=='object'||typeof r.id!=='string'||!/^[A-Za-z0-9_.:-]{1,128}$/.test(r.id))throw new Error(`Rule ${i+1} needs a valid id.`);
    if(ids.has(r.id))throw new Error(`Id “${r.id}” is used twice.`);ids.add(r.id);
    if(!['allow','block'].includes(r.reaction))throw new Error(`Rule “${r.id}”: reaction must be allow or block.`);
    return {id:String(r.id),subject:String(r.subject||'*'),service:String(r.service||''),action:String(r.action||'*'),...(r.conditions?{conditions:r.conditions.map(c=>({param:String(c.param),op:String(c.op),value:String(c.value)}))}:{}),reaction:r.reaction,...(r.note?{note:String(r.note)}:{})};
  });
  const dr=o.default_reaction==='allow'?'allow':'block';
  return {version:S.live.version,default_reaction:dr,checks,rules};
}
function validate(p){
  const errs={},warns={};const add=(m,id,x)=>(m[id]=m[id]||[]).push(x);
  p.checks.forEach((n,i)=>{
    if(!String(n.name||'').trim())add(errs,n.id,'Name is empty.');
    if(n.type==='regex_pattern'){if(!(n.patterns||[]).length)add(errs,n.id,'Add at least one pattern.');(n.patterns||[]).forEach(x=>{try{toRegex(x)}catch(e){add(errs,n.id,`Pattern “${x}” is not a valid regular expression.`)}})}
    if(n.type==='allowed_models'&&!(n.models||[]).length)add(errs,n.id,'List at least one model, or every prompt will be blocked.');
    ['max_per_minute','delay_ms','daily_tokens','max_similar_per_minute','refresh_minutes','timeout_ms'].forEach(k=>{if(n[k]!==undefined&&!(n[k]>0))add(errs,n.id,`${k.replace(/_/g,' ')} must be a positive number.`)});
    (n.exceptions||[]).forEach(e=>{if(!String(e.match||'').trim())add(errs,n.id,'An exception has no text to match.')});
    if(n.type==='semantic'){
      if(!String(n.instruction||'').trim())add(errs,n.id,'The instruction is empty.');
      const ls=(n.labels||[]).map(l=>String(l.label||'').trim());
      if(ls.length<2)add(errs,n.id,'Add at least two labels.');
      if(ls.some(l=>!l))add(errs,n.id,'A label is empty.');
      if(new Set(ls).size!==ls.length)add(errs,n.id,'Labels must be unique.');
      if(ls.some(l=>/\s/.test(l)))add(errs,n.id,'Labels must be single words so the model can answer with one token.');
      const firstDet=p.checks.findIndex(x=>NODE_TYPES[x.type]&&NODE_TYPES[x.type].kind==='rule'&&x.mode!=='off');
      const lastDet=p.checks.map(x=>NODE_TYPES[x.type]&&NODE_TYPES[x.type].kind==='rule'&&x.mode!=='off').lastIndexOf(true);
      if(firstDet>=0&&i<lastDet)add(warns,n.id,'Order affects transformations and decisions. The baseline always sanitizes secrets and personal data before classification.');
    }
  });
  if(p.checks.filter(n=>n.type==='service_access').length>1)p.checks.filter(n=>n.type==='service_access').forEach(n=>add(errs,n.id,'Only one service access stage is allowed.'));
  p.rules.forEach(r=>{
    const svc=S.services.find(s=>s.id===r.service);
    if(!svc){add(errs,r.id,`Service “${r.service}” is not in the catalog.`);return}
    const a=r.action==='*'?null:svc.actions.find(x=>x.name===r.action);
    if(r.action!=='*'&&!a)add(errs,r.id,`Action “${r.action}” does not exist in ${svc.name}.`);
    (r.conditions||[]).forEach(c=>{
      const params=a?a.params:svc.actions.flatMap(x=>x.params);
      if(!params.find(p=>p.name===c.param))add(errs,r.id,`Parameter “${c.param}” does not exist for this action.`);
      if(String(c.value??'').trim()==='')add(errs,r.id,'A condition has no value.');
      if(['lte','gte'].includes(c.op)&&isNaN(Number(c.value)))add(errs,r.id,`“${c.value}” is not a number.`);
    });
  });
  return {errs,warns};
}

const isDirty=()=>diff(S.live,S.draft).length>0;
/* ===================== UI utilities ===================== */
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>t.classList.remove('show'),3200)}
function modal({title,body,actions,wide}){
  const root=$('#modalRoot');const prev=document.activeElement;
  root.innerHTML=`<div class="scrim"><div class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-labelledby="mTitle"><h2 id="mTitle">${title}</h2><div class="mbody">${body}</div><div class="acts">${actions.map((a,i)=>`<button class="btn ${a.kind||''}" data-a="${i}" ${a.disabled?'disabled':''}>${a.label}</button>`).join('')}</div></div></div>`;
  const dialog=root.firstElementChild;const close=()=>{if(root.firstElementChild!==dialog)return;root.innerHTML='';prev&&prev.focus&&prev.focus()};
  root.querySelectorAll('[data-a]').forEach(b=>b.onclick=async()=>{const a=actions[+b.dataset.a];b.disabled=true;try{if(a.run&&await a.run(root)===false)return;close()}catch(err){showError(err)}finally{b.disabled=false}});
  root.querySelector('.scrim').onclick=e=>{if(e.target.classList.contains('scrim'))close()};
  root.onkeydown=e=>{if(e.key==='Escape')close()};
  setTimeout(()=>{const f=root.querySelector('input,textarea,select')||root.querySelector('.btn.primary')||root.querySelector('.btn');f&&f.focus()},20);
  return root;
}
function updateChip(){$('#liveChip span').textContent='Live policy v'+S.live.version}
const stPill=d=>`<span class="st ${d}">${DEC_LABEL[d]}</span>`;
const gly=k=>`<span class="gly" aria-hidden="true">${GLYPH[k]}</span>`;
const reqLabel=req=>req.dir==='tool_call'?`${req.service}.${req.action}`:req.target;

/* ===================== router ===================== */
function route(){
  if(!S.identity||!S.ready){renderLogin();return}
  const h=location.hash.replace(/^#\/?/,'')||'requests';const parts=h.split('/');const page=parts[0];
  document.querySelectorAll('[data-nav]').forEach(a=>{if(a.dataset.nav===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
  S.page=page;S.detailId=null;window.scrollTo(0,0);
  if(page==='requests'&&parts[1]){S.detailId=parts[1];renderDetail(parts[1])}
  else if(page==='services'){if(parts[1])S.selService=parts[1];renderServices()}
  else if(page==='builder'){const tab=['checks','rules','tests'].includes(parts[1])?parts[1]:'checks';S.tab=tab;if(parts[2]){if(tab==='checks')S.sel=parts[2];if(tab==='rules')S.selRule=parts[2];if(tab==='tests')S.selTest=parts[2]}renderBuilder()}
  else if(page==='history'){if(parts[1])S.histSel=+parts[1];renderHistory()}
  else if(page==='training')renderTraining();
  else if(page==='report')renderReport();
  else{S.page='requests';renderRequests()}
}
window.addEventListener('hashchange',route);

/* ===================== REQUESTS ===================== */
function counts(){const c={...BASE};S.events.forEach(e=>c[e.r.decision]++);return c}
function possibleFP(e){if(e.fp)return true;const c=e.r.checks.find(c=>c.id===e.r.trigger);return !!(c&&c.kind==='ai'&&['block','redact'].includes(e.r.decision)&&/red.team|training/i.test(e.req.text||''))}
function visibleEvents(){const f=S.filters,q=f.q.trim().toLowerCase();
  return S.events.filter(e=>(f.status==='all'||e.r.decision===f.status)&&(f.agent==='all'||e.req.agent===f.agent)&&(!f.fp||possibleFP(e))&&(!q||(e.id+' '+e.req.text+' '+e.user+' '+e.req.agent+' '+(e.r.triggerName||'')+' '+reqLabel(e.req)).toLowerCase().includes(q))).slice().reverse().slice(0,120)}
function renderRequests(){
  $('#main').innerHTML=`
  <div class="page-head"><div><p class="eyebrow">AI control layer</p><h1 class="page-title">Requests</h1><p>Persisted server decisions for synthetic calls and evaluations. Counts cover the loaded audit records; no automatic demo traffic is generated.</p></div></div>
  <div class="summary" id="summary"></div>
  <div class="filters">
    <input type="search" id="q" placeholder="Search text, user, agent, service or check" value="${esc(S.filters.q)}" aria-label="Search requests">
    <select id="fAgent" aria-label="Agent"><option value="all">All agents</option>${AGENTS.map(a=>`<option ${S.filters.agent===a?'selected':''}>${esc(a)}</option>`).join('')}</select>
    <label class="chk"><input type="checkbox" id="fFp" ${S.filters.fp?'checked':''}> Possible false positives</label>
    <span class="spacer"></span>
    <span class="live-note ${S.paused?'paused':''}"><i></i>${S.paused?'Paused':'Live'}</span>
    <button class="btn primary small" id="invokeSynthetic">Run synthetic request</button><button class="btn small" id="pause">${S.paused?'Resume':'Pause'}</button>
  </div>
  <div class="table-wrap"><table>
    <thead><tr><th>Time</th><th>Input decision</th><th>User</th><th>Agent</th><th>Type</th><th>Target</th><th>Content</th><th>Decided by</th><th>Policy</th><th class="num">Added latency</th></tr></thead>
    <tbody id="rows"></tbody></table></div>`;
  $('#q').oninput=e=>{S.filters.q=e.target.value;drawRows()};
  $('#fAgent').onchange=e=>{S.filters.agent=e.target.value;drawRows()};
  $('#fFp').onchange=e=>{S.filters.fp=e.target.checked;drawRows()};
  $('#invokeSynthetic').onclick=invokeSynthetic;
  $('#pause').onclick=()=>{S.paused=!S.paused;renderRequests()};
  const open=e=>{const tr=e.target.closest('tr[data-id]');if(tr)location.hash='#/requests/'+tr.dataset.id};
  $('#rows').onclick=open;$('#rows').onkeydown=e=>{if(e.key==='Enter')open(e)};
  drawSummary();drawRows();
}
function drawSummary(){
  const c=counts();const lat=S.events.map(e=>e.r.overhead).sort((a,b)=>a-b);const p95=lat[Math.floor(lat.length*.95)]||0;
  const item=(k)=>`<button class="sum" data-s="${k}" aria-pressed="${S.filters.status===k}"><span class="v">${fmt(c[k])}</span><span class="l"><i style="background:var(--${k})"></i>${DEC_LABEL[k]}</span></button>`;
  $('#summary').innerHTML=['allow','redact','block','throttle','monitor'].map(item).join('')+`<div class="sum static"><span class="v">${Math.round(p95)} ms</span><span class="l">p95 added latency</span></div>`;
  $('#summary').querySelectorAll('[data-s]').forEach(b=>b.onclick=()=>{S.filters.status=S.filters.status===b.dataset.s?'all':b.dataset.s;drawSummary();drawRows()});
}
function drawRows(fresh){
  const rows=visibleEvents();
  $('#rows').innerHTML=rows.length?rows.map(e=>`<tr class="row ${e.id===fresh?'fresh':''}" data-id="${esc(e.id)}" tabindex="0">
    <td class="muted">${t2(e.ts)}</td><td>${stPill(e.r.decision)} ${e.fp?'<span class="tag fp">False positive</span>':''}</td><td>${esc(e.user)}</td><td>${esc(e.req.agent)}</td><td>${DIR_LABEL[e.req.dir]}</td>
    <td class="code">${esc(reqLabel(e.req))}</td><td class="msg"><span>${esc(e.req.dir==='tool_call'?JSON.stringify(e.req.params):e.req.text)}</span></td><td>${e.r.triggerName?esc(e.r.triggerName):'<span class="muted">All passed</span>'}</td>
    <td class="muted">v${e.r.version}</td><td class="num">${ms(e.r.overhead)}${e.r.throttle?` <span class="muted">retry ${(e.r.throttle/1000).toFixed(1)} s</span>`:''}</td></tr>`).join('')
    :`<tr><td colspan="10" class="empty">No requests match these filters. Clear a filter or the search to see more.</td></tr>`;
}

/* ===================== DETAIL ===================== */
function reasonText(req,r){
  if(r.decision==='pending')return 'Run tests to obtain an evaluation from the server.';
  if(r.decision==='allow'){const ex=r.checks.find(c=>c.result==='exception');return ex?`Allowed. ${ex.name} passed it by an exception.`:'Allowed. All checks passed.'}
  const verb={block:'Blocked',redact:'Redacted',throttle:'Throttled',monitor:'Flagged'}[r.decision];
  let s=`${verb} by ${r.triggerName}. ${r.triggerDetail||''}`.trim();
  if(r.decision==='throttle')s+=`. Admission refused; retry after ${((r.retryAfterMs||r.throttle||0)/1000).toFixed(1)} s`;
  if(r.decision==='monitor')s+='. Allowed because the check is in monitor mode';
  return s.replace(/\.\.$/,'.')+(s.endsWith('.')?'':'.');
}
function marked(text,marks){let h=esc(text);[...new Set(marks||[])].filter(Boolean).sort((a,b)=>b.length-a.length).forEach(m=>{h=h.split(esc(m)).join(`<mark>${esc(m)}</mark>`)});return h}
function chainHtml(r){
  const aiSkipped=r.checks.some(c=>c.kind==='ai'&&c.result==='skipped');
  return `<ol class="chain">${r.checks.map(c=>{const ico={pass:'✓',block:'✕',redact:'✎',throttle:'❙❙',monitor:'!',exception:'↷',skipped:'',off:'',na:''}[c.result];
    const head=c.result==='skipped'?'Skipped':c.result==='off'?'Off in policy':c.result==='na'?'Not applicable':c.result==='exception'?'Passed by exception':c.result==='pass'?'Passed':DEC_LABEL[c.result];
    const cls=c.result==='na'?'off':c.result;
    return `<li class="${cls}"><span class="node">${ico}</span><span>${esc(c.name)}<span class="kind">${KIND_LABEL[c.kind]}</span>${c.detail&&!['skipped','off','na'].includes(c.result)?`<br><span class="muted" style="font-size:13px">${esc(c.detail)}</span>`:''}</span><span class="res ${c.kind==='ai'&&c.lat?'ai-ms':''}">${head}${c.lat?', '+ms(c.lat):''}</span></li>`}).join('')}</ol>
  <div class="chain-total"><span>Total added latency${aiSkipped?' (AI checks skipped after an earlier block)':''}</span><span>${ms(r.overhead)}${r.throttle?` + ${(r.throttle/1000).toFixed(1)} s retry-after`:''}</span></div>`;
}
function renderDetail(id){
  const e=S.events.find(x=>x.id===id);
  if(!e){$('#main').innerHTML=`<p class="crumbs"><a href="#/requests">Requests</a></p><h1 class="page-title">Request not found</h1><p class="muted">It may have left the live buffer. Go back to Requests to pick another one.</p>`;return}
  const t={session:e.session||[]},r=e.r,req=e.req;const isCall=req.dir==='tool_call';
  const tc=r.checks.find(c=>c.id===r.trigger);const accessBlock=r.triggerType==='service_access';
  const proc=e.action?.outcome==='not_started'||r.processed==null?'<p class="nothing">Nothing. The request was stopped before it reached the target.</p>':`<div class="payload">${esc(r.processed).replace(/\[([A-Z _:a-z-]+)\]/g,'<span class="red">[$1]</span>')}</div>`;
  $('#main').innerHTML=`
  <p class="crumbs"><a href="#/requests">Requests</a> / ${e.id}</p>
  <div class="detail">
    <div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">${stPill(r.decision)} ${e.fp?'<span class="tag fp">Marked as false positive</span>':''}<span class="muted" style="font-size:14px">${e.ts.toLocaleString('en-GB')}</span></div>
      <h1 class="reason">${esc(reasonText(req,r))}</h1>
      ${e.fp?`<div class="fpnote">${esc(e.fp.by)} marked this as a false positive: “${esc(e.fp.comment||'No comment')}”</div>`:''}
      <section class="sec"><h2>Session context</h2>
        <div class="convo">
          ${t.session.map(([who,txt])=>`<div class="msgb ${who==='tool'?'tool':''}"><div class="who">${who==='user'?esc(e.user):who==='assistant'?req.agent:'Earlier service call by '+req.agent}</div>${esc(txt)}</div>`).join('')}
          <div class="msgb current ${isCall?'tool':''}"><div class="who">${DIR_LABEL[req.dir]}, this request</div><div class="payload">${marked(req.text,r.decision==='allow'?[]:r.marks)}</div></div>
        </div>
      </section>
      <section class="sec"><h2>Sent and received</h2>
        <div class="compare"><div><h3>${req.dir==='output'?'What the model answered':esc(req.agent)+' sent'}</h3><div class="payload">${marked(req.text,r.decision==='allow'?[]:r.marks)}</div></div>
        <div><h3>${req.dir==='output'?'What the agent received':isCall?esc(req.service)+' received':'Locally evaluated content (no model dispatch)'}</h3>${proc}</div></div>
      </section>
      <section class="sec"><h2>Inspection chain <span class="muted" style="font:400 14px var(--sans)">policy v${r.version}</span></h2>${chainHtml(r)}</section>
    </div>
    <aside class="side">
      <div class="box"><h3>Details</h3><dl class="facts">
        <dt>User</dt><dd>${esc(e.user)}</dd><dt>Agent</dt><dd>${esc(req.agent)}</dd><dt>Type</dt><dd>${DIR_LABEL[req.dir]}</dd><dt>Target</dt><dd class="code">${esc(reqLabel(req))}</dd>
        <dt>Policy</dt><dd>v${r.version}${r.version!==S.live.version?` <span class="tag warn">now v${S.live.version}</span>`:''}</dd><dt>Estimated tokens</dt><dd>${r.decision==='block'?'0, not sent':fmt(e.tokens)}</dd><dt>Request ID</dt><dd>${e.id}</dd></dl></div>
      <div class="box"><h3>Actions</h3><div class="actions">
        ${r.decision!=='allow'?`<button class="btn" id="aFp">${e.fp?'Edit false positive note':'Mark as false positive'}</button>`:''}
        ${accessBlock?(r.triggerRule?`<button class="btn" id="aRule">Open rule ${esc(r.triggerRule)}</button>`:`<button class="btn" id="aNewRule">Create a rule for ${esc(req.service)}.${esc(req.action)}</button>`):''}
        ${r.trigger&&!accessBlock?`<button class="btn" id="aEx">Add exception to ${esc(r.triggerName)}</button>`:''}
        <button class="btn" id="aTest">Save as test case</button>
        <button class="btn primary" id="aReplay">Replay with current policy</button>
        ${r.trigger&&!accessBlock?`<button class="btn" id="aOpen">Open ${esc(r.triggerName)} in builder</button>`:''}
      </div><div id="replayOut"></div></div>
    </aside>
  </div>`;
  const b=x=>document.getElementById(x);
  if(b('aFp'))b('aFp').onclick=()=>markFP(e);
  if(b('aEx'))b('aEx').onclick=()=>addException(e);
  if(b('aRule'))b('aRule').onclick=()=>{location.hash='#/builder/rules/'+r.triggerRule};
  if(b('aNewRule'))b('aNewRule').onclick=()=>newRuleFor(req);
  b('aTest').onclick=()=>saveAsTest(e);
  b('aReplay').onclick=()=>replay(e);
  if(b('aOpen'))b('aOpen').onclick=()=>{location.hash='#/builder/checks/'+r.trigger};
  if(S.replay[e.id])drawReplay(e);
}
async function replay(e){try{S.replay[e.id]=await api('/events/'+encodeURIComponent(e.id)+'/replay','POST',isDirty()?{policy:S.draft}:{});drawReplay(e)}catch(err){showError(err)}}
function drawReplay(e){
  const res=S.replay[e.id];if(!res)return;const o=e.r;
  const col=(lbl,r)=>`<div class="col"><small>${lbl}</small>${stPill(r.decision)}</div>`;
  let html=`<div class="replay" style="margin-top:16px">${col('Original, v'+o.version,o)}<span class="arrow">→</span>${col('Current, v'+res.current.version,res.current)}</div>`;
  if(res.draft)html+=`<div class="replay">${col('Original, v'+o.version,o)}<span class="arrow">→</span>${col('Saved draft',res.draft)}</div>`;
  const changed=res.current.decision!==o.decision;
  html+=`<p class="replay-note">Replay uses retained sanitized content and does not dispatch a service. ${changed?`With policy v${res.current.version}: ${esc(reasonText(e.req,res.current))}`:`Same result with policy v${res.current.version}.`}</p>`;
  const out=document.getElementById('replayOut');if(out)out.innerHTML=html;
}
function markFP(e){
  modal({title:'Mark as false positive',body:`<p>This request was ${DEC_LABEL[e.r.decision].toLowerCase()} by ${esc(e.r.triggerName)}. Tell other admins why it should have passed.</p>
    <div class="field"><label for="fpC">Comment</label><textarea id="fpC" style="font-family:var(--sans);font-size:14px">${esc(e.fp?e.fp.comment:'')}</textarea></div>`,
    actions:[{label:'Cancel'},{label:'Mark as false positive',kind:'primary',run:async root=>{await api('/events/'+encodeURIComponent(e.id)+'/review','POST',{fp:true,comment:root.querySelector('#fpC').value.trim()});await refreshState();toast('False positive review saved.');renderDetail(e.id)}}]});
}
function eventToTest(e,expected){
  const q=e.req;const base={id:'t'+(tid++),name:'',agent:q.agent,dir:q.dir,expected};
  if(q.dir==='tool_call')Object.assign(base,{service:q.service,action:q.action,params:clone(q.params)});else Object.assign(base,{target:q.target,text:q.text});
  if(e.evaluationContext)base.meta=clone(e.evaluationContext);else if(q.meta&&Object.keys(q.meta).length)base.meta=clone(q.meta);return base;
}
function saveAsTest(e){
  const def=e.fp?'allow':(e.r.decision==='monitor'?'allow':e.r.decision);
  modal({title:'Save as test case',body:`<p>The request is saved with an expected result. It will run every time the policy changes.</p>
    <div class="field"><label for="tN">Name</label><input type="text" id="tN" value="${esc((e.fp?'Should pass: ':'')+(e.req.dir==='tool_call'?`${e.req.agent} calls ${e.req.service}.${e.req.action}`:e.req.text.slice(0,48)))}"></div>
    <p class="hint">The recorded admission counters are saved with this fixture.</p>
    <div class="field"><span class="lbl">Expected result</span><div class="seg" id="tE">${['allow','redact','block','throttle'].map(x=>`<button data-x="${x}" aria-pressed="${x===def}">${MODE_LABEL[x]}</button>`).join('')}</div></div>`,
    actions:[{label:'Cancel'},{label:'Save test case',kind:'primary',run:root=>{const x=root.querySelector('#tE [aria-pressed="true"]').dataset.x;const t=eventToTest(e,x);t.name=root.querySelector('#tN').value.trim()||'Untitled test';if(x==='redact'&&e.r.processed)t.expected_output=e.r.processed;S.tests.push(t);scheduleTests();toast(`Test case added. ${S.tests.length} tests in the suite.`)}}]});
  document.querySelectorAll('#tE button').forEach(b=>b.onclick=()=>document.querySelectorAll('#tE button').forEach(x=>x.setAttribute('aria-pressed',x===b)));
}
function addException(e){
  const t={};const node=S.live.checks.find(n=>n.id===e.r.trigger);if(!node)return;
  const suggestion=t.suggest||e.req.text;
  modal({title:'Add exception',body:`<p>Requests that match this exception pass <b>${esc(node.name)}</b>. All other checks still run.</p>
    <div class="field"><label for="exA">Agent</label><select id="exA"><option value="">Any agent</option>${AGENTS.map(a=>`<option ${a===e.req.agent?'selected':''}>${esc(a)}</option>`).join('')}</select></div>
    <div class="field"><label for="exM">Exact full request text</label><input type="text" id="exM" value="${esc(suggestion)}"><div class="hint">Case-insensitive full-text match. Added content invalidates the exception.</div></div>
    <div class="field"><label class="chk" style="display:inline-flex"><input type="checkbox" id="exT" checked> Also save this request as a test case expecting Allow</label></div>
    <div class="preview" id="exP"></div>`,
    actions:[{label:'Cancel'},{label:'Check impact and apply',kind:'primary',run:root=>{
      const ex={match:root.querySelector('#exM').value.trim()};const ag=root.querySelector('#exA').value;if(ag)ex.agent=ag;
      if(!ex.match){root.querySelector('#exM').focus();return false}
      if(root.querySelector('#exT').checked){const tc=eventToTest(e,'allow');tc.name='Should pass: '+(e.req.text.slice(0,48));S.tests.push(tc);scheduleTests()}
      const p=clone(S.live);const n=p.checks.find(n=>n.id===node.id);n.exceptions=[...(n.exceptions||[]),ex];
      setTimeout(()=>checkImpact(p,{source:'Console, from request '+e.id,after:()=>{renderDetail(e.id);replay(e)}}),30);
    }}]});
  const upd=()=>{const a=$('#exA').value,m=$('#exM').value.trim();$('#exP').textContent=m?`Requests from ${a||'any agent'} exactly matching “${m}” will skip ${node.name}.`:'Enter the text to match.'};
  $('#exA').onchange=upd;$('#exM').oninput=upd;upd();
}
function newRuleFor(req){
  let i=1;while(S.draft.rules.find(r=>r.id==='r'+i))i++;
  S.draft.rules.push({id:'r'+i,subject:req.agent,service:req.service,action:req.action,reaction:'allow',note:''});
  scheduleDraft();location.hash='#/builder/rules/r'+i;toast('Draft rule created. Review it and save to apply.');
}

/* ===================== BUILDER ===================== */
function renderBuilder(){
  const dirty=isDirty();const nOps=diff(S.live,S.draft).length;const tab=S.tab;
  $('#main').innerHTML=`
  <div class="page-head"><div><p class="eyebrow">Policy</p><h1 class="page-title">Policy builder</h1>
    <div class="vmeta"><span>Live version <b>v${S.live.version}</b></span><span id="dirtyMeta">${dirty?`<span class="dirty">${nOps} draft change${nOps>1?'s':''}</span>`:'No draft changes'}</span><button class="link" id="sim">Check external changes</button></div></div>
    <div class="bbar">${tab!=='tests'?`<button class="btn" id="tYaml" aria-pressed="${S.yaml}">${S.yaml?'Hide YAML':'Show YAML'}</button>`:''}<button class="btn" id="discard" ${dirty?'':'disabled'}>Discard changes</button><button class="btn" id="runT">Run tests</button><button class="btn primary" id="save" ${dirty?'':'disabled'}>Check impact and apply</button></div></div>
  ${S.ext?`<div class="banner" role="status"><div><b>The active policy changed outside this editor</b><br>${esc(S.ext.author)} activated a policy ${ago(S.ext.at)}. Version v${S.ext.v} is now live. Changed items are marked below.</div><button class="btn small" id="extX">Dismiss</button></div>`:''}
  <nav class="subtabs" aria-label="Builder sections">
    <a href="#/builder/checks" aria-selected="${tab==='checks'}">Checks<span>${S.draft.checks.length}</span></a>
    <a href="#/builder/rules" aria-selected="${tab==='rules'}">Service rules<span>${S.draft.rules.length}</span></a>
    <a href="#/builder/tests" aria-selected="${tab==='tests'}">Test cases<span>${S.tests.length}</span></a>
  </nav>
  <div id="bwrap"></div>`;
  if($('#tYaml'))$('#tYaml').onclick=()=>{S.yaml=!S.yaml;renderBuilderKeepScroll()};
  $('#discard').onclick=()=>{S.draft=clone(S.live);scheduleDraft();renderBuilderKeepScroll();toast('Draft changes discarded')};
  $('#runT').onclick=async()=>{location.hash='#/builder/tests';await runSuite()};
  $('#save').onclick=save;
  $('#sim').onclick=()=>refreshState({announce:true}).catch(showError);
  if($('#extX'))$('#extX').onclick=()=>{S.ext=null;renderBuilderKeepScroll()};
  if(tab==='checks')renderChecksTab();else if(tab==='rules')renderRulesTab();else renderTestsTab();
}
function renderBuilderKeepScroll(){const sy=window.scrollY;renderBuilder();window.scrollTo(0,sy)}
function yamlPane(){return `<div class="yamlpane"><div class="yaml-head"><span>policy.yaml, edits apply to the draft</span></div>
  <div class="yaml-wrap"><pre id="yHl" aria-hidden="true"></pre><textarea id="yText" spellcheck="false" wrap="off" aria-label="Policy YAML"></textarea></div><div id="yMsg"></div></div>`}
function refreshMeta(){
  const dirty=isDirty();const n=diff(S.live,S.draft).length;const dm=$('#dirtyMeta');
  if(dm)dm.innerHTML=dirty?`<span class="dirty">${n} draft change${n>1?'s':''}</span>`:'No draft changes';
  if($('#save'))$('#save').disabled=!dirty;if($('#discard'))$('#discard').disabled=!dirty;
  const tabs=document.querySelectorAll('.subtabs a span');if(tabs.length===3){tabs[0].textContent=S.draft.checks.length;tabs[1].textContent=S.draft.rules.length;tabs[2].textContent=S.tests.length}
}
function afterDraftChange(full){
  scheduleDraft();
  if(full){renderBuilderKeepScroll();return}
  if(S.tab==='checks')drawPipe();else if(S.tab==='rules')drawRuleList();
  refreshMeta();if(S.yaml)syncYaml();
}
function changedTag(id,list){const live=(list==='rule'?S.live.rules:S.live.checks).find(x=>x.id===id);const cur=(list==='rule'?S.draft.rules:S.draft.checks).find(x=>x.id===id);
  if(!live)return '<span class="tag new">New</span>';return stableJson(live)!==stableJson(cur)?'<span class="tag warn">Draft</span>':''}

/* ---------- checks tab ---------- */
function renderChecksTab(){
  const groups={};Object.entries(NODE_TYPES).forEach(([k,d])=>{if(k==='service_access')return;(groups[d.group]=groups[d.group]||[]).push([k,d])});
  $('#bwrap').innerHTML=`<div class="builder ${S.yaml?'yaml':''}">
    ${S.yaml?'':`<div class="lib" aria-label="Check library">${Object.entries(groups).map(([g,list])=>`<h3>${g}</h3>${list.map(([k,d])=>`<button data-add="${k}" title="Add ${d.label} after the selected check">${gly(d.kind)}${d.label}<span aria-hidden="true">+</span></button>`).join('')}`).join('')}</div>`}
    <div class="pipe" id="pipe"></div><div id="settings"></div>${S.yaml?yamlPane():''}</div>`;
  document.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>{const i=S.draft.checks.findIndex(n=>n.id===S.sel);addCheck(b.dataset.add,i>=0?i+1:S.draft.checks.length)});
  if(!S.draft.checks.find(n=>n.id===S.sel))S.sel=S.draft.checks[0]&&S.draft.checks[0].id;
  drawPipe();drawSettings();if(S.yaml)initYaml();
}
function openPicker(index){
  const groups={};Object.entries(NODE_TYPES).forEach(([k,d])=>{if(k==='service_access'&&S.draft.checks.some(n=>n.type==='service_access'))return;(groups[d.group]=groups[d.group]||[]).push([k,d])});
  const root=modal({title:'Add a check',body:`<p>The check is added at this point in the pipeline. Deterministic checks should run before AI checks.</p><div class="picker">${Object.entries(groups).map(([g,list])=>`<h3>${g}</h3>${list.map(([k,d])=>`<button data-pick="${k}">${gly(d.kind)}<b>${d.label}</b><small>${d.desc}</small></button>`).join('')}`).join('')}</div>`,actions:[{label:'Cancel'}]});
  root.querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>{root.innerHTML='';addCheck(b.dataset.pick,index)});
}
function addCheck(type,index){
  const base=type==='semantic'?'classifier':type.split('_')[0];let i=1,id=base;while(S.draft.checks.find(n=>n.id===id)||S.draft.rules.find(r=>r.id===id))id=base+'_'+(++i);
  const node=mk(id,type);if(type==='semantic')node.name='Custom AI classification';
  S.draft.checks.splice(Math.max(0,Math.min(index,S.draft.checks.length)),0,node);S.sel=id;afterDraftChange(true);toast(`${node.name} added to the draft`);
}
function keySetting(n){
  switch(n.type){
    case 'semantic':return `${n.applies_to==='output'?'Answers':'Prompts'}, ${n.model}, labels: ${(n.labels||[]).map(l=>l.label+' → '+l.reaction).join(', ')}`;
    case 'pii_detection':return (n.entities||[]).map(x=>x.toUpperCase()).join(', ')||'No data types';
    case 'regex_pattern':return `${(n.patterns||[]).length} pattern${(n.patterns||[]).length===1?'':'s'}`;
    case 'allowed_models':return (n.models||[]).join(', ')||'No models';
    case 'denied_paths':return `${(n.deny_paths||[]).length} denied paths`;
    case 'service_access':return `${S.draft.rules.length} rules, calls without a rule: ${MODE_LABEL[S.draft.default_reaction]}`;
    case 'signature_feed':return 'Local bundled signatures; external refresh is not connected';
    case 'rate_limit':return `${n.max_per_minute} per minute, retry after ${(n.delay_ms/1000).toFixed(1)} s`;
    case 'token_budget':return `${fmt(n.daily_tokens)} estimated tokens per agent per UTC day`;
    case 'loop_detector':return `${n.max_similar_per_minute} similar calls per minute`;
    default:return NODE_TYPES[n.type].desc;
  }
}
function drawPipe(){
  const {errs,warns}=validate(S.draft);const N=S.draft.checks.length;
  const ins=i=>`<div class="wire ins"><button data-ins="${i}" aria-label="Add a check at position ${i+1}" title="Add a check here">+</button></div>`;
  $('#pipe').innerHTML=`<div class="endpoint">Agent request</div>`+S.draft.checks.map((n,i)=>{
    const d=NODE_TYPES[n.type];const ext=S.ext&&S.ext.changes[n.id];const ex=(n.exceptions||[]).length;const stage=n.type==='service_access';
    return ins(i)+`<div class="ncard ${n.id===S.sel?'sel':''} ${n.mode==='off'?'off':''} ${stage?'stage':''}" data-id="${esc(n.id)}" draggable="true" tabindex="0" aria-label="${esc(n.name)}, ${MODE_LABEL[n.mode]}">
      ${gly(d.kind)}<div class="nm">${esc(n.name)} ${changedTag(n.id,'check')}${ex?`<span class="tag">${ex} exception${ex>1?'s':''}</span>`:''}${errs[n.id]?'<span class="tag err">Needs fixing</span>':''}${warns[n.id]?'<span class="tag warn">Check order</span>':''}</div>
      <div class="mode"><span class="mpill ${n.mode==='enforce'?'block':n.mode}">${MODE_LABEL[n.mode]}</span><span class="hits">${HITS[n.id]||0} hits in loaded audit</span></div>
      <div class="sub">${KIND_LABEL[d.kind]}. ${esc(keySetting(n))}${stage?` <button class="link" data-goto-rules>Edit rules</button>`:''}</div>
      ${ext?`<div class="ext">Changed externally: ${ext.map(c=>esc(describe(c).replace(c.label+': ',''))).join('; ')}</div>`:''}
      ${errs[n.id]?`<div class="errs">${errs[n.id].map(esc).join('<br>')}</div>`:''}
      ${warns[n.id]?`<div class="errs" style="color:var(--redact)">${warns[n.id].map(esc).join('<br>')}</div>`:''}
      <div class="tools"><button data-t="up" aria-label="Move up" ${i===0?'disabled':''}>↑</button><button data-t="down" aria-label="Move down" ${i===N-1?'disabled':''}>↓</button><button data-t="off" aria-label="${n.mode==='off'?'Turn on':'Turn off'}">${n.mode==='off'?'◉':'○'}</button><button data-t="del" aria-label="Remove check">✕</button></div>
    </div>`}).join('')+ins(N)+`<button class="btn small add-end" data-ins="${N}">Add check</button><div class="wire"></div><div class="endpoint">Model or service</div>`;
  const pipe=$('#pipe');let dragId=null;
  pipe.querySelectorAll('[data-ins]').forEach(b=>b.onclick=e=>{e.stopPropagation();openPicker(+b.dataset.ins)});
  pipe.querySelectorAll('[data-goto-rules]').forEach(b=>b.onclick=e=>{e.stopPropagation();location.hash='#/builder/rules'});
  pipe.querySelectorAll('.ncard').forEach(c=>{
    c.onclick=e=>{const tb=e.target.closest('[data-t]');const id=c.dataset.id;if(tb){tool(id,tb.dataset.t);return}if(S.sel!==id){S.sel=id;drawPipe();drawSettings();if(S.yaml)highlightYaml()}};
    c.onkeydown=e=>{if(e.key==='Enter'&&e.target===c){S.sel=c.dataset.id;drawPipe();drawSettings();if(S.yaml)highlightYaml()}};
    c.ondragstart=e=>{dragId=c.dataset.id;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',dragId)};
    c.ondragover=e=>{e.preventDefault();c.classList.add('drag-over')};
    c.ondragleave=()=>c.classList.remove('drag-over');
    c.ondrop=e=>{e.preventDefault();c.classList.remove('drag-over');const from=S.draft.checks.findIndex(n=>n.id===dragId);if(from<0||dragId===c.dataset.id)return;const [m]=S.draft.checks.splice(from,1);const to=S.draft.checks.findIndex(n=>n.id===c.dataset.id);S.draft.checks.splice(to,0,m);afterDraftChange()};
  });
}
function tool(id,t){
  const ns=S.draft.checks;const i=ns.findIndex(n=>n.id===id);const n=ns[i];
  if(t==='up'&&i>0)[ns[i-1],ns[i]]=[ns[i],ns[i-1]];
  if(t==='down'&&i<ns.length-1)[ns[i+1],ns[i]]=[ns[i],ns[i+1]];
  if(t==='off'){n.mode=n.mode==='off'?NODE_TYPES[n.type].defaults.mode:'off'}
  if(t==='del'){modal({title:`Remove ${esc(n.name)}?`,body:`<p>The check is removed from the draft. Live traffic is not affected until you apply the change.</p>`,actions:[{label:'Cancel'},{label:'Remove check',kind:'danger',run:()=>{S.draft.checks.splice(i,1);if(S.sel===id)S.sel=null;afterDraftChange(true)}}]});return}
  S.sel=id;afterDraftChange();drawSettings();
}
const seg=(attr,opts,cur)=>`<div class="seg" role="group">${opts.map(m=>`<button data-${attr}="${m}" aria-pressed="${cur===m}">${MODE_LABEL[m]||m}</button>`).join('')}</div>`;
function listField(label,key,n,hint){return `<div class="field"><label for="f_${key}">${label}</label><textarea id="f_${key}" data-list="${key}">${esc((n[key]||[]).join('\n'))}</textarea>${hint?`<div class="hint">${hint}</div>`:''}</div>`}
function numField(label,key,n,step=1){return `<div class="field"><label for="f_${key}">${label}</label><input type="number" id="f_${key}" data-num="${key}" value="${n[key]}" step="${step}" min="0"></div>`}
function exceptionsHtml(n){return `<hr class="divider"><div class="field"><span class="lbl">Exceptions</span>${(n.exceptions||[]).length?n.exceptions.map((e,i)=>`<div class="subrow"><select data-exc="${i}" data-k="agent" aria-label="Agent"><option value="">Any agent</option>${AGENTS.map(a=>`<option ${a===e.agent?'selected':''}>${esc(a)}</option>`).join('')}</select><input type="text" data-exc="${i}" data-k="match" value="${esc(e.match)}" aria-label="Text to match" placeholder="Exact full request text"><button class="x" data-delexc="${i}" aria-label="Remove exception">✕</button></div>`).join(''):'<p class="hint" style="margin:0 0 8px">No exceptions. Add one here or from a blocked request.</p>'}<button class="link" id="addExc">Add exception</button></div>`}
function drawSettings(){
  const box=$('#settings');const n=S.draft.checks.find(n=>n.id===S.sel);
  if(!n){box.innerHTML=`<div class="settings"><p class="muted">Select a check to edit it, or add one with the + buttons in the pipeline.</p></div>`;return}
  const d=NODE_TYPES[n.type];let body=`<div class="field"><label for="f_name">Name</label><input type="text" id="f_name" data-str="name" value="${esc(n.name)}"></div>`;
  if(n.type==='semantic'){
    body+=`<div class="field"><span class="lbl">Mode</span>${seg('mode',d.modes,n.mode)}</div>
    <div class="field"><span class="lbl">Classify</span>${seg('applies',['input','output'],n.applies_to).replace('>input<','>Prompts in<').replace('>output<','>Answers out<')}</div>
    <div class="field"><label for="f_model">Model</label><select id="f_model" data-str="model">${MODELS.map(m=>`<option ${m===n.model?'selected':''}>${esc(m)}</option>`).join('')}</select></div>
    <div class="field"><label for="f_ins">Instruction</label><textarea id="f_ins" data-str="instruction" style="font-family:var(--sans);font-size:14px;min-height:96px">${esc(n.instruction)}</textarea>
      <div class="hint">Instruction v${n.instruction_version||1}${(()=>{const o=S.live.checks.find(x=>x.id===n.id);return o&&o.instruction!==n.instruction?`, edited. Saving creates v${(o.instruction_version||1)+1}`:''})()}. Stored configuration; the current baseline does not execute model instructions or use a provider cache.</div></div>
    <div class="field labels-tbl"><span class="lbl">Labels and reactions</span><div class="hint" style="margin:0 0 8px">Label reactions are enforced by the backend; current labels come from the baseline heuristic.</div>
      ${(n.labels||[]).map((l,i)=>`<div class="subrow"><input type="text" data-lab="${i}" data-k="label" value="${esc(l.label)}" aria-label="Label"><select data-lab="${i}" data-k="reaction" aria-label="Reaction">${['allow','redact','block'].map(x=>`<option value="${x}" ${x===l.reaction?'selected':''}>${MODE_LABEL[x]}</option>`).join('')}</select><button class="x" data-dellab="${i}" aria-label="Remove label">✕</button></div>`).join('')}
      <button class="link" id="addLab">Add label</button></div>
    <div class="field"><span class="lbl">If the model answers with an unknown label</span>${seg('unk',['block','allow'],n.on_unknown)}<div class="hint">An empty or cut-off answer counts as unknown. It is never treated as allowed by default.</div></div>
    <div class="field"><span class="lbl">If the model does not answer in time</span>${seg('tmo',['block','allow'],n.on_timeout)}</div>
    ${numField('Timeout (ms)','timeout_ms',n,50)}
    <div class="sim"><label for="f_sim" class="lbl" style="font-size:13px;font-weight:600;color:var(--ink-2)">Test-only fault injection (does not affect live requests)</label><select id="f_sim" style="width:100%;margin-top:6px;background:var(--bg);border:1px solid var(--line-2);padding:6px 8px"><option value="none">No failure</option><option value="unknown" ${SIM[n.id]==='unknown'?'selected':''}>Model returns an unknown label</option><option value="timeout" ${SIM[n.id]==='timeout'?'selected':''}>Model times out</option></select></div>`;
  } else if(n.type==='service_access'){
    body+=`<div class="field"><span class="lbl">Mode</span>${seg('mode',d.modes,n.mode)}<div class="hint">Monitor logs rule violations without blocking them.</div></div>
    <div class="field"><span class="lbl">Calls without a matching rule</span>${seg('def',['block','allow'],S.draft.default_reaction)}</div>
    <p class="note-box">The most specific rule wins: a named agent beats Any agent, and a named action beats any action. On a tie, Block wins.</p>
    <button class="btn small" id="goRules">Open service rules</button>`;
  } else {
    body+=`<div class="field"><span class="lbl">When the check finds something</span>${seg('mode',d.modes,n.mode)}</div>`;
    if(n.type==='pii_detection')body+=`<div class="field"><span class="lbl">Data types</span><div class="checks">${['email','phone','pesel','iban','card'].map(x=>`<label><input type="checkbox" data-ent="${x}" ${(n.entities||[]).includes(x)?'checked':''}> ${x==='email'||x==='phone'||x==='card'?x[0].toUpperCase()+x.slice(1):x.toUpperCase()}</label>`).join('')}</div></div>`;
    if(n.type==='regex_pattern')body+=listField('Patterns, one per line','patterns',n,'Start a line with (?i) to ignore case.');
    if(['secrets_detection','pii_detection','regex_pattern'].includes(n.type))body+=listField('Service-call argument fields, one per line','fields',n,'Optional. When set, this check only inspects these arguments of a service call, so a routing field such as the recipient address is never rewritten. Prompt and answer text is always inspected in full.');
    if(n.type==='allowed_models')body+=listField('Allowed models, one per line','models',n);
    if(n.type==='denied_paths')body+=listField('Denied paths, one per line','deny_paths',n,'A service call is stopped when any argument contains one of these.');
    if(n.type==='signature_feed')body+=`<p class="note-box">Source and refresh interval are saved as configuration. Runtime uses bundled local signatures and does not fetch this address.</p><div class="field"><label for="f_feed">Feed source</label><input type="text" id="f_feed" data-str="feed" value="${esc(n.feed)}"></div>`+numField('Refresh every (minutes)','refresh_minutes',n);
    if(n.type==='rate_limit')body+=numField('Requests per minute per agent','max_per_minute',n)+numField('Retry-after duration (ms)','delay_ms',n,100);
    if(n.type==='token_budget')body+=numField('Estimated tokens per agent per UTC day','daily_tokens',n,10000);
    if(n.type==='loop_detector')body+=numField('Similar calls per minute','max_similar_per_minute',n);
  }
  if(n.type!=='service_access')body+=exceptionsHtml(n);
  body+=`<hr class="divider"><button class="btn danger small" id="delNode">Remove check</button>`;
  box.innerHTML=`<div class="settings"><div class="head">${gly(d.kind)}<div><h3>${esc(n.name)}</h3><p>${d.desc}</p><p class="muted">id: ${esc(n.id)}, type: ${esc(n.type)}</p></div></div>${body}</div>`;
  const on=(sel,ev,fn)=>box.querySelectorAll(sel).forEach(el=>el.addEventListener(ev,fn));
  const re=()=>{afterDraftChange();drawSettings()};
  on('[data-str]','input',e=>{n[e.target.dataset.str]=e.target.value;afterDraftChange()});
  on('select[data-str]','change',e=>{n[e.target.dataset.str]=e.target.value;afterDraftChange()});
  on('[data-mode]','click',e=>{n.mode=e.target.dataset.mode;re()});
  on('[data-applies]','click',e=>{n.applies_to=e.target.dataset.applies;re()});
  on('[data-unk]','click',e=>{n.on_unknown=e.target.dataset.unk;re()});
  on('[data-tmo]','click',e=>{n.on_timeout=e.target.dataset.tmo;re()});
  on('[data-def]','click',e=>{S.draft.default_reaction=e.target.dataset.def;re()});
  on('[data-num]','input',e=>{n[e.target.dataset.num]=e.target.value===''?0:+e.target.value;afterDraftChange()});
  on('[data-list]','input',e=>{n[e.target.dataset.list]=e.target.value.split('\n').map(s=>s.trim()).filter(Boolean);afterDraftChange()});
  on('[data-ent]','change',e=>{const s=new Set(n.entities||[]);e.target.checked?s.add(e.target.dataset.ent):s.delete(e.target.dataset.ent);n.entities=['email','phone','pesel','iban','card'].filter(x=>s.has(x));afterDraftChange()});
  on('[data-lab]','input',e=>{const l=n.labels[+e.target.dataset.lab];l[e.target.dataset.k]=e.target.dataset.k==='label'?e.target.value.trim():e.target.value;afterDraftChange()});
  on('[data-dellab]','click',e=>{n.labels.splice(+e.target.dataset.dellab,1);re()});
  on('[data-exc]','input',e=>{const x=n.exceptions[+e.target.dataset.exc];const k=e.target.dataset.k;if(k==='agent'&&!e.target.value)delete x.agent;else x[k]=e.target.value;afterDraftChange()});
  on('[data-delexc]','click',e=>{n.exceptions.splice(+e.target.dataset.delexc,1);if(!n.exceptions.length)delete n.exceptions;re()});
  const g=x=>box.querySelector(x);
  if(g('#addLab'))g('#addLab').onclick=()=>{n.labels=[...(n.labels||[]),{label:'',reaction:'block'}];re();const ins=box.querySelectorAll('[data-k="label"]');ins[ins.length-1].focus()};
  if(g('#addExc'))g('#addExc').onclick=()=>{n.exceptions=[...(n.exceptions||[]),{agent:AGENTS[0],match:''}];re();const ins=box.querySelectorAll('[data-exc][data-k="match"]');ins[ins.length-1].focus()};
  if(g('#f_sim'))g('#f_sim').onchange=e=>{SIM[n.id]=e.target.value;S.testResultKey=null;toast('Test fault context updated. Run tests to evaluate it on the server.')};
  if(g('#goRules'))g('#goRules').onclick=()=>{location.hash='#/builder/rules'};
  g('#delNode').onclick=()=>tool(n.id,'del');
}

/* ---------- rules tab ---------- */
function renderRulesTab(){
  $('#bwrap').innerHTML=`<div class="builder b-rules ${S.yaml?'yaml':''}"><div>
    <div class="rtop"><span class="lbl" style="font-weight:600;font-size:14px">Calls without a matching rule</span>${seg('def',['block','allow'],S.draft.default_reaction)}
      <select id="rSub" aria-label="Filter by agent"><option value="all">All agents</option><option value="*" ${S.ruleSubject==='*'?'selected':''}>Any agent rules</option>${AGENTS.map(a=>`<option ${S.ruleSubject===a?'selected':''}>${esc(a)}</option>`).join('')}</select>
      <span class="spacer"></span><button class="btn primary small" id="addRule">Add rule</button>
      <span class="note">The most specific rule wins: a named agent beats Any agent, and a named action beats any action. On a tie, Block wins.</span></div>
    <div id="rlist"></div></div><div id="reditor"></div>${S.yaml?yamlPane():''}</div>`;
  document.querySelectorAll('.rtop [data-def]').forEach(b=>b.onclick=()=>{S.draft.default_reaction=b.dataset.def;afterDraftChange(true)});
  $('#rSub').onchange=e=>{S.ruleSubject=e.target.value;drawRuleList()};
  $('#addRule').onclick=()=>{let i=1;while(S.draft.rules.find(r=>r.id==='r'+i))i++;const svc=S.services[0];S.draft.rules.push({id:'r'+i,subject:AGENTS[0],service:svc.id,action:svc.actions[0].name,reaction:'allow'});S.selRule='r'+i;afterDraftChange(true)};
  if(!S.draft.rules.find(r=>r.id===S.selRule))S.selRule=S.draft.rules[0]&&S.draft.rules[0].id;
  drawRuleList();drawRuleEditor();if(S.yaml)initYaml();
}
function drawRuleList(){
  const {errs}=validate(S.draft);const f=S.ruleSubject;
  const rules=S.draft.rules.filter(r=>f==='all'||r.subject===f);
  const groups=S.services.map(s=>({s,rules:rules.filter(r=>r.service===s.id)}));
  const unknown=rules.filter(r=>!S.services.find(s=>s.id===r.service));
  const card=r=>{const ext=S.ext&&S.ext.changes[r.id];return `<button class="rcard ${r.id===S.selRule?'sel':''}" data-rid="${esc(r.id)}">
    <span class="who"><code>${esc(subj(r.subject))}</code> → <code>${esc(r.service)}.${esc(r.action==='*'?'*':r.action)}</code> ${changedTag(r.id,'rule')}${errs[r.id]?'<span class="tag err">Needs fixing</span>':''}</span>
    <span class="rx"><span class="rpill ${r.reaction}">${MODE_LABEL[r.reaction]}</span></span>
    <span class="cnd">${(r.conditions||[]).length?'If '+esc(r.conditions.map(condText).join(' and ')):''}${r.note?`${(r.conditions||[]).length?'. ':''}${esc(r.note)}`:''}${!(r.conditions||[]).length&&!r.note?'No conditions':''}</span>
    ${ext?`<span class="ext">Changed externally: ${ext.map(c=>esc(describe(c).replace('Rule '+c.label+': ',''))).join('; ')}</span>`:''}</button>`};
  $('#rlist').innerHTML=groups.map(({s,rules})=>{
    const covered=new Set(S.draft.rules.filter(r=>r.service===s.id).map(r=>r.action));
    const unc=covered.has('*')?[]:s.actions.filter(a=>!covered.has(a.name)).map(a=>a.name);
    if(!rules.length&&f!=='all')return '';
    return `<div class="rgroup"><h3>${esc(s.name)} <small>${esc(s.id)}, ${s.actions.length} actions</small></h3>${rules.map(card).join('')}
      ${f==='all'&&unc.length?`<div class="uncovered">No rule for ${unc.map(a=>`<span class="code">${a}</span>`).join(', ')}. Calls without a rule: ${MODE_LABEL[S.draft.default_reaction]}.</div>`:''}</div>`}).join('')+
    (unknown.length?`<div class="rgroup"><h3>Unknown service</h3>${unknown.map(card).join('')}</div>`:'')||'<p class="muted">No rules for this agent.</p>';
  $('#rlist').querySelectorAll('[data-rid]').forEach(b=>b.onclick=()=>{S.selRule=b.dataset.rid;drawRuleList();drawRuleEditor();if(S.yaml)highlightYaml()});
}
function drawRuleEditor(){
  const box=$('#reditor');const r=S.draft.rules.find(x=>x.id===S.selRule);
  if(!r){box.innerHTML='<div class="settings"><p class="muted">Select a rule or add one.</p></div>';return}
  const svc=S.services.find(s=>s.id===r.service);const a=svc&&r.action!=='*'?svc.actions.find(x=>x.name===r.action):null;
  const params=a?a.params:svc?[...new Map(svc.actions.flatMap(x=>x.params).map(p=>[p.name,p])).values()]:[];
  const {errs}=validate(S.draft);
  box.innerHTML=`<div class="settings"><div class="head">${gly('access')}<div><h3>Rule ${esc(r.id)}</h3><p>${esc(`When ${subj(r.subject)} calls ${r.service}.${r.action==='*'?'any action':r.action}${(r.conditions||[]).length?' and '+r.conditions.map(condText).join(' and '):''}: ${MODE_LABEL[r.reaction]}`)}</p></div></div>
    ${errs[r.id]?`<p class="errs" style="color:var(--block);font-size:13.5px;margin:0 0 12px">${errs[r.id].map(esc).join('<br>')}</p>`:''}
    <div class="field"><label for="r_sub">Who</label><select id="r_sub" data-rf="subject"><option value="*" ${r.subject==='*'?'selected':''}>Any agent</option>${AGENTS.map(x=>`<option ${x===r.subject?'selected':''}>${esc(x)}</option>`).join('')}</select><div class="hint">Agent calls use the verified transport identity. This operator console can select synthetic agents for explicit on-behalf-of runs.</div></div>
    <div class="field"><label for="r_svc">Service</label><select id="r_svc" data-rf="service">${S.services.map(s=>`<option value="${s.id}" ${s.id===r.service?'selected':''}>${esc(s.name)} (${s.id})</option>`).join('')}${svc?'':`<option selected>${esc(r.service)}</option>`}</select></div>
    <div class="field"><label for="r_act">Action</label><select id="r_act" data-rf="action"><option value="*" ${r.action==='*'?'selected':''}>Any action</option>${svc?svc.actions.map(x=>`<option value="${x.name}" ${x.name===r.action?'selected':''}>${x.name}${x.destructive?' (destructive)':''}</option>`).join(''):''}</select>${a&&a.destructive?'<div class="hint" style="color:var(--redact)">This action changes or deletes data.</div>':''}</div>
    <div class="field"><span class="lbl">Conditions on parameters</span>
      ${(r.conditions||[]).map((c,i)=>`<div class="subrow" style="grid-template-columns:1fr 110px 1fr auto"><select data-cnd="${i}" data-k="param" aria-label="Parameter">${params.map(p=>`<option ${p.name===c.param?'selected':''}>${esc(p.name)}</option>`).join('')}${params.find(p=>p.name===c.param)?'':`<option selected>${esc(c.param)}</option>`}</select><select data-cnd="${i}" data-k="op" aria-label="Operator">${Object.entries(OPS).map(([k,v])=>`<option value="${k}" ${k===c.op?'selected':''}>${v}</option>`).join('')}</select><input type="text" data-cnd="${i}" data-k="value" value="${esc(c.value)}" aria-label="Value"><button class="x" data-delcnd="${i}" aria-label="Remove condition">✕</button></div>`).join('')}
      ${params.length?'<button class="link" id="addCnd">Add condition</button>':'<p class="hint">This action has no parameters.</p>'}</div>
    <div class="field"><span class="lbl">Reaction</span>${seg('rx',['allow','block'],r.reaction)}</div>
    <div class="field"><label for="r_note">Note</label><input type="text" id="r_note" data-rf="note" value="${esc(r.note||'')}" placeholder="Why this rule exists"></div>
    <hr class="divider"><button class="btn danger small" id="delRule">Remove rule</button></div>`;
  const on=(sel,ev,fn)=>box.querySelectorAll(sel).forEach(el=>el.addEventListener(ev,fn));
  const re=()=>{afterDraftChange();drawRuleEditor()};
  on('select[data-rf]','change',e=>{const k=e.target.dataset.rf;r[k]=e.target.value;if(k==='service'){const s=S.services.find(s=>s.id===r.service);r.action=s&&s.actions[0]?s.actions[0].name:'*';delete r.conditions}if(k==='action'){const s=S.services.find(s=>s.id===r.service);const ac=s&&s.actions.find(x=>x.name===r.action);if(ac&&r.conditions)r.conditions=r.conditions.filter(c=>ac.params.some(p=>p.name===c.param));if(r.conditions&&!r.conditions.length)delete r.conditions}re()});
  on('input[data-rf]','input',e=>{const v=e.target.value;if(v)r.note=v;else delete r.note;afterDraftChange()});
  on('[data-rx]','click',e=>{r.reaction=e.target.dataset.rx;re()});
  on('select[data-cnd]','change',e=>{r.conditions[+e.target.dataset.cnd][e.target.dataset.k]=e.target.value;re()});
  on('input[data-cnd]','input',e=>{r.conditions[+e.target.dataset.cnd].value=e.target.value;afterDraftChange()});
  on('[data-delcnd]','click',e=>{r.conditions.splice(+e.target.dataset.delcnd,1);if(!r.conditions.length)delete r.conditions;re()});
  const g=x=>box.querySelector(x);
  if(g('#addCnd'))g('#addCnd').onclick=()=>{const p=params[0];r.conditions=[...(r.conditions||[]),{param:p.name,op:p.type==='number'?'lte':'eq',value:''}];re();const ins=box.querySelectorAll('input[data-cnd]');ins[ins.length-1].focus()};
  g('#delRule').onclick=()=>modal({title:`Remove rule ${esc(r.id)}?`,body:`<p>${esc(ruleLabel(r))} is removed from the draft. Matching calls will fall back to the default: ${MODE_LABEL[S.draft.default_reaction]}.</p>`,actions:[{label:'Cancel'},{label:'Remove rule',kind:'danger',run:()=>{S.draft.rules=S.draft.rules.filter(x=>x.id!==r.id);afterDraftChange(true)}}]});
}

/* ---------- tests tab ---------- */
function renderTestsTab(){
  $('#bwrap').innerHTML=`<div class="builder b-tests"><div><div class="tsum" id="tsum"></div><div class="table-wrap"><table class="ttable"><thead id="thead"></thead><tbody id="trows"></tbody></table></div></div><div id="teditor"></div></div>`;
  if(!S.tests.find(t=>t.id===S.selTest))S.selTest=S.tests[0]&&S.tests[0].id;
  drawTests();drawTestEditor();
}
function drawTests(){
  scheduleTests();
  const dirty=isDirty();const evaluated=S.testResultKey===evaluationKey();const rows=S.tests.map(t=>({t,cur:runTest(S.live,t),dr:dirty?runTest(S.draft,t):null}));
  const passCur=rows.filter(x=>x.cur.pass).length,passDr=dirty?rows.filter(x=>x.dr.pass).length:null,changed=dirty?rows.filter(x=>x.dr.d!==x.cur.d).length:0;
  $('#tsum').innerHTML=`<div><b>${evaluated?passCur+' / '+rows.length:'Not run'}</b><span>${evaluated?'pass on live':'server evaluation for live'} v${S.live.version}</span></div>${dirty?`<div><b>${evaluated?passDr+' / '+rows.length:'Not run'}</b><span>${evaluated?'pass on your draft':'server evaluation for draft'}</span></div><div><b>${changed}</b><span>decision${changed===1?'':'s'} changed by the draft</span></div>`:''}<span class="spacer"></span><button class="btn primary small" id="addTest">Add test case</button>`;
  $('#thead').innerHTML=`<tr><th>Test</th><th>Request</th><th>Expected</th><th>Live v${S.live.version}</th>${dirty?'<th>Draft</th>':''}</tr>`;
  const cell=x=>x.pending?'<span class="muted">Not run</span>':`<div class="res">${stPill(x.d)}<span class="${x.pass?'ok':'bad'}">${x.pass?'Matches':'Does not match'}</span></div>`;
  $('#trows').innerHTML=rows.length?rows.map(({t,cur,dr})=>`<tr class="row ${t.id===S.selTest?'selrow':''}" data-tid="${esc(t.id)}" tabindex="0"><td><b>${esc(t.name)}</b><br><span class="muted" style="font-size:13px">${esc(t.agent)}</span></td><td class="req code">${esc(testSummary(t))}</td><td><span class="rpill ${t.expected}">${MODE_LABEL[t.expected]}</span></td><td>${cell(cur)}</td>${dirty?`<td>${cell(dr)}${dr.d!==cur.d?' <span class="changed">Changed</span>':''}</td>`:''}</tr>`).join(''):`<tr><td colspan="5" class="empty">No test cases yet. Add one, or save a request from the Requests page.</td></tr>`;
  const sel=e=>{const tr=e.target.closest('tr[data-tid]');if(tr){S.selTest=tr.dataset.tid;drawTests();drawTestEditor()}};
  $('#trows').onclick=sel;$('#trows').onkeydown=e=>{if(e.key==='Enter')sel(e)};
  $('#addTest').onclick=()=>{const t={id:'t'+(tid++),name:'New test case',agent:AGENTS[0],dir:'tool_call',service:S.services[0].id,action:S.services[0].actions[0].name,params:{},expected:'block'};S.tests.push(t);S.selTest=t.id;drawTests();drawTestEditor();refreshMeta()};
}
function drawTestEditor(){
  const box=$('#teditor');const t=S.tests.find(x=>x.id===S.selTest);
  if(!t){box.innerHTML='<div class="settings"><p class="muted">Select a test case.</p></div>';return}
  const svc=S.services.find(s=>s.id===t.service);const a=svc&&svc.actions.find(x=>x.name===t.action);
  const cur=runTest(S.live,t),dr=isDirty()?runTest(S.draft,t):null;
  const resBox=(lbl,x)=>x.pending?`<p class="note-box">${lbl}: run tests to see a server result.</p>`:`<div class="box" style="padding:12px;margin-top:10px"><div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><small class="muted">${lbl}</small>${stPill(x.d)}</div><p style="font-size:13.5px;margin:8px 0 0;color:var(--ink-2)">${esc(reasonText(testReq(t),x.r))}</p>${x.r.processed!=null&&x.r.processed!==testReq(t).text?`<div class="payload" style="font-size:12.5px;margin-top:6px">${esc(x.r.processed)}</div>`:''}<p class="${x.pass?'ok':'bad'}" style="margin:6px 0 0">${x.pass?'Matches the expected result':'Does not match the expected result'}</p></div>`;
  box.innerHTML=`<div class="settings"><div class="head">${gly('rule')}<div><h3>Test case</h3><p>Independent fixture: estimated input tokens plus the usage below. No live counters are consumed; future usage can change admission.</p></div></div>
    <div class="field"><label for="t_name">Name</label><input type="text" id="t_name" data-tf="name" value="${esc(t.name)}"></div>
    <div class="field"><label for="t_ag">Agent</label><select id="t_ag" data-tf="agent">${AGENTS.map(x=>`<option ${x===t.agent?'selected':''}>${esc(x)}</option>`).join('')}</select></div>
    <div class="field"><span class="lbl">Type</span>${seg('tdir',['tool_call','input','output'],t.dir).replace('>tool_call<','>Service call<').replace('>input<','>Prompt<').replace('>output<','>Model answer<')}</div>
    ${t.dir==='tool_call'?`
      <div class="field"><label for="t_svc">Service</label><select id="t_svc" data-tf="service">${S.services.map(s=>`<option value="${s.id}" ${s.id===t.service?'selected':''}>${esc(s.name)}</option>`).join('')}</select></div>
      <div class="field"><label for="t_act">Action</label><select id="t_act" data-tf="action">${svc?svc.actions.map(x=>`<option ${x.name===t.action?'selected':''}>${esc(x.name)}</option>`).join(''):''}</select></div>
      ${a?a.params.map(p=>`<div class="field"><label for="tp_${p.name}">${p.name} <span class="muted">${p.type}${p.required?', required':''}</span></label><input type="text" id="tp_${p.name}" data-tp="${p.name}" value="${esc(t.params&&t.params[p.name]!==undefined?t.params[p.name]:'')}"></div>`).join(''):''}`
    :`<div class="field"><label for="t_tgt">Model</label><input type="text" id="t_tgt" data-tf="target" value="${esc(t.target||'llama3.1:8b')}" list="modelList"><datalist id="modelList">${[...MODELS,'gpt-4o'].map(m=>`<option value="${m}">`).join('')}</datalist></div>
      <div class="field"><label for="t_txt">${t.dir==='output'?'Model answer':'Prompt text'}</label><textarea id="t_txt" data-tf="text" style="font-family:var(--sans);font-size:14px">${esc(t.text||'')}</textarea></div>`}
    <div class="field"><label for="t_used">Tokens already used in this fixture</label><input type="number" min="0" id="t_used" value="${t.meta?.tokens_used||0}"><p class="hint">Saved requests retain their recorded admission context. This is a simulation, not the current live ledger.</p></div>
    <div class="field"><span class="lbl">Expected result</span>${seg('texp',['allow','redact','block','throttle'],t.expected)}</div>
    ${t.expected==='redact'?`<div class="field"><label for="t_out">Expected text after redaction</label><input type="text" id="t_out" data-tf="expected_output" value="${esc(t.expected_output||'')}" placeholder="Leave empty to only check the decision"></div>`:''}
    ${resBox('Live v'+S.live.version,cur)}${dr?resBox('Your draft',dr):''}
    <hr class="divider"><button class="btn danger small" id="delTest">Remove test case</button></div>`;
  const on=(sel,ev,fn)=>box.querySelectorAll(sel).forEach(el=>el.addEventListener(ev,fn));
  const live=()=>{drawTests()};
  on('input[data-tf],textarea[data-tf]','input',e=>{const k=e.target.dataset.tf;if(k==='expected_output'&&!e.target.value)delete t.expected_output;else t[k]=e.target.value;live()});
  on('input[data-tf],textarea[data-tf]','change',()=>drawTestEditor());
  on('select[data-tf]','change',e=>{const k=e.target.dataset.tf;t[k]=e.target.value;if(k==='service'){const s=S.services.find(s=>s.id===t.service);t.action=s.actions[0].name;t.params={}}if(k==='action')t.params={};live();drawTestEditor()});
  on('input[data-tp]','input',e=>{t.params=t.params||{};const name=e.target.dataset.tp,definition=a?.params.find(p=>p.name===name),value=e.target.value;t.params[name]=definition?.type==='boolean'&&['true','false'].includes(value)?value==='true':definition?.type==='number'&&value!==''&&Number.isFinite(Number(value))?Number(value):value;live()});
  on('input[data-tp]','change',()=>drawTestEditor());
  on('[data-tdir]','click',e=>{t.dir=e.target.dataset.tdir;if(t.dir==='tool_call'){t.service=t.service||S.services[0].id;const s=S.services.find(s=>s.id===t.service);t.action=t.action||s.actions[0].name;t.params=t.params||{}}else{t.target=t.target||'llama3.1:8b';t.text=t.text||''}live();drawTestEditor()});
  on('[data-texp]','click',e=>{t.expected=e.target.dataset.texp;live();drawTestEditor()});
  box.querySelector('#t_used').oninput=e=>{t.meta={...(t.meta||{}),tokens_used:Number(e.target.value)};live()};
  box.querySelector('#delTest').onclick=()=>{S.tests=S.tests.filter(x=>x.id!==t.id);S.selTest=null;drawTests();drawTestEditor();refreshMeta()};
}

/* ---------- save & impact ---------- */
function save(){
  const {errs}=validate(S.draft);const n=Object.values(errs).flat().length;
  if(n){toast(`Fix ${n} problem${n>1?'s':''} before applying. They are marked in red.`);if(S.tab==='checks')drawPipe();if(S.tab==='rules'){drawRuleList();drawRuleEditor()}return}
  checkImpact(S.draft,{fromDraft:true});
}
async function checkImpact(policy,{fromDraft=false,source='Console',after}={}){
  try{
    await flushDraft();await flushTests();
    const candidate=clone(policy),tests=clone(S.tests),version=S.live.version;
    const comparison=await api('/compare','POST',{policy:candidate,tests,expectedVersion:version});
    const resultRows=Object.fromEntries(comparison.results.map(r=>[r.id,r]));
    const rows=tests.map(t=>{const row=resultRows[t.id];if(!row)throw Error('Comparison is incomplete.');
      const wrap=r=>{r=r.r||r;const d=r.decision==='monitor'?'allow':r.decision;return {r,d,pass:d===t.expected&&!(t.expected==='redact'&&t.expected_output&&r.processed!==t.expected_output)}};
      const a=wrap(row.live),b=wrap(row.draft);return {t,a,b,st:!b.pass&&a.pass?'broken':b.pass&&!a.pass?'fixed':!b.pass?'failing':a.d!==b.d?'changed':'same'};});
    if(!comparison.complete)throw Error('Comparison is incomplete; activation is unavailable.');
    const mismatch=rows.filter(x=>!x.b.pass).length,broken=rows.filter(x=>x.st==='broken').length,fixed=rows.filter(x=>x.st==='fixed').length;
    const ops=diff(S.live,candidate),nv=version+1;
    const root=modal({title:'Check impact before applying',wide:true,body:`<p>The server evaluated ${rows.length} test cases on live v${version} and this exact candidate. No service was dispatched.</p>
      <ul>${ops.map(o=>`<li>${esc(describe(o))}</li>`).join('')||'<li>No policy changes</li>'}</ul>
      <div class="tsum"><div><b>${broken}</b><span>new mismatches</span></div><div><b>${fixed}</b><span>fixed</span></div><div><b>${mismatch}</b><span>total mismatches</span></div></div>
      <div class="table-wrap"><table class="ttable"><thead><tr><th>Test</th><th>Expected</th><th>Live</th><th>Candidate</th><th>Result</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${esc(x.t.name)}</td><td>${esc(x.t.expected)}</td><td>${stPill(x.a.d)}</td><td>${stPill(x.b.d)}</td><td class="${x.b.pass?'ok':'bad'}">${esc(x.st)}</td></tr>`).join('')}</tbody></table></div>
      <div class="field" style="margin-top:16px"><label for="applyReason">Reason for this change</label><input id="applyReason" value="${esc(source==='Console'?summarize(ops):source)}"></div>
      ${mismatch?'<label class="chk"><input type="checkbox" id="ack"> I reviewed every mismatch and explicitly approve this override</label>':''}
      <p class="hint">Activation is bound to this candidate, test suite and active version. Baseline classification is not a trained model.</p>`,actions:[{label:'Back to editing'},{label:`Apply as v${nv}`,kind:'primary',disabled:!!mismatch,run:async root=>{
        const oldLive=clone(S.live),oldDraft=clone(S.draft),keepDraft=isDirty()&&!fromDraft;
        const state=await api('/activate','POST',{policy:candidate,tests,expectedVersion:version,evaluationId:comparison.id,source:source.startsWith('Rollback')?'Rollback':'Console',reason:root.querySelector('#applyReason').value.trim()||source,overrideMismatches:!!root.querySelector('#ack')?.checked});
        applyState(state,{replaceDraft:true});if(keepDraft){S.draft=rebase(oldLive,oldDraft,S.live);scheduleDraft();}S.ext=null;toast(`Policy v${S.live.version} activated by the server.`);
        if(after)after();else route();
      }}]});
    const ack=root.querySelector('#ack');if(ack)ack.onchange=()=>{root.querySelector('.btn.primary').disabled=!ack.checked};
  }catch(err){showError(err)}
}

/* ---------- YAML pane ---------- */
function initYaml(){
  const ta=$('#yText');if(!ta)return;ta.value=dump(S.draft);S.yamlErr=null;drawYamlHl();showYamlMsg();
  let tmo;
  ta.addEventListener('input',()=>{drawYamlHl();clearTimeout(tmo);tmo=setTimeout(()=>{
    try{S.draft=fromYaml(ta.value);S.yamlErr=null;scheduleDraft();if(S.tab==='checks'){drawPipe();drawSettings()}else{drawRuleList();drawRuleEditor()}refreshMeta()}
    catch(err){S.yamlErr=err.mark?`Line ${err.mark.line+1}: ${err.reason}`:err.message}
    showYamlMsg();drawYamlHl();
  },350)});
  ta.addEventListener('scroll',()=>{const pre=$('#yHl');pre.scrollTop=ta.scrollTop;pre.scrollLeft=ta.scrollLeft});
  const pickFromCursor=()=>{const line=ta.value.slice(0,ta.selectionStart).split('\n').length-1;const id=nodeAtLine(ta.value.split('\n'),line);if(!id)return;
    if(S.tab==='checks'&&S.draft.checks.find(n=>n.id===id)&&id!==S.sel){S.sel=id;drawPipe();drawSettings();drawYamlHl()}
    if(S.tab==='rules'&&S.draft.rules.find(r=>r.id===id)&&id!==S.selRule){S.selRule=id;drawRuleList();drawRuleEditor();drawYamlHl()}};
  ta.addEventListener('click',pickFromCursor);ta.addEventListener('keyup',e=>{if(e.key.startsWith('Arrow'))pickFromCursor()});
  highlightYaml();
}
const ID_LINE=/^  - id: (.+)$/;
function cleanId(s){return s.trim().replace(/^['"]|['"]$/g,'')}
function nodeAtLine(lines,line){let id=null;for(let i=0;i<=line&&i<lines.length;i++){const m=lines[i].match(ID_LINE);if(m)id=cleanId(m[1]);else if(/^\S/.test(lines[i]))id=null}return id}
function blockRange(lines,id){let s=-1,e=lines.length;for(let i=0;i<lines.length;i++){const m=lines[i].match(ID_LINE);if(s>=0&&(m||/^\S/.test(lines[i]))){e=i;break}if(m&&cleanId(m[1])===id)s=i}return s<0?null:[s,e]}
function curSelId(){return S.tab==='rules'?S.selRule:S.sel}
function drawYamlHl(){const ta=$('#yText'),pre=$('#yHl');if(!ta||!pre)return;const lines=ta.value.split('\n');const r=blockRange(lines,curSelId());
  pre.innerHTML=lines.map((l,i)=>`<div class="${r&&i>=r[0]&&i<r[1]?'on':''}">${esc(l)||' '}</div>`).join('');pre.scrollTop=ta.scrollTop}
function highlightYaml(){drawYamlHl();const ta=$('#yText');if(!ta)return;const r=blockRange(ta.value.split('\n'),curSelId());if(r){const lh=13*1.6;const top=r[0]*lh;if(top<ta.scrollTop||top>ta.scrollTop+ta.clientHeight-60)ta.scrollTop=Math.max(0,top-40);$('#yHl').scrollTop=ta.scrollTop}}
function syncYaml(){const ta=$('#yText');if(!ta||document.activeElement===ta)return;const st=ta.scrollTop;ta.value=dump(S.draft);ta.scrollTop=st;S.yamlErr=null;drawYamlHl();showYamlMsg()}
function showYamlMsg(){const m=$('#yMsg');if(!m)return;m.innerHTML=S.yamlErr?`<div class="yaml-err">${esc(S.yamlErr.replace(/\.$/,''))}. The builder keeps the last valid version.</div>`:`<div class="yaml-ok">Valid YAML. Changes appear in the builder as you type.</div>`}

/* ---------- service schema import ---------- */
/* ===================== SERVICES ===================== */
const SAMPLE_SCHEMA=`{
  "id": "tickets",
  "name": "Ticketing",
  "kind": "MCP server",
  "endpoint": "mcp://tickets.internal",
  "owner": "support-eng",
  "actions": [
    { "name": "get_ticket", "desc": "Read a ticket",
      "params": [ { "name": "ticket_id", "type": "string", "required": true } ] },
    { "name": "add_comment", "desc": "Add a comment to a ticket",
      "params": [ { "name": "ticket_id", "type": "string", "required": true },
                  { "name": "text", "type": "string", "required": true } ] },
    { "name": "close_ticket", "desc": "Close a ticket", "destructive": true,
      "params": [ { "name": "ticket_id", "type": "string", "required": true },
                  { "name": "reason", "type": "string" } ] }
  ]
}`;
function parseSchema(text){
  let o;try{o=JSON.parse(text)}catch(e){throw new Error('The schema is not valid JSON: '+e.message)}
  if(!o.id||!/^[a-z][a-z0-9_-]*$/.test(o.id))throw new Error('“id” is required and may contain only lowercase letters, digits, - and _.');
  if(S.services.find(s=>s.id===o.id))throw new Error(`A service with id “${o.id}” already exists.`);
  if(!o.name)throw new Error('“name” is required.');
  if(!Array.isArray(o.actions)||!o.actions.length)throw new Error('“actions” must be a non-empty list.');
  const names=new Set();
  o.actions.forEach((a,i)=>{if(!a.name)throw new Error(`Action ${i+1} has no name.`);if(names.has(a.name))throw new Error(`Action “${a.name}” is listed twice.`);names.add(a.name);
    a.params=a.params||[];if(!Array.isArray(a.params))throw new Error(`Action “${a.name}”: params must be a list.`);
    a.params.forEach(p=>{if(!p.name)throw new Error(`Action “${a.name}” has a parameter without a name.`);if(!['string','number','boolean'].includes(p.type||'string'))throw new Error(`Parameter “${p.name}”: type must be string, number or boolean.`);p.type=p.type||'string'})});
  return {id:o.id,name:o.name,kind:o.kind||'MCP server',endpoint:o.endpoint||'',owner:o.owner||'',verified:null,actions:o.actions.map(a=>({name:a.name,desc:a.desc||'',destructive:!!a.destructive,params:a.params.map(p=>({name:p.name,type:p.type,required:!!p.required}))}))};
}
function renderServices(){
  if(!S.services.find(s=>s.id===S.selService))S.selService=S.services[0].id;
  const s=S.services.find(x=>x.id===S.selService);
  const rulesFor=a=>S.live.rules.filter(r=>r.service===s.id&&(r.action===a||r.action==='*'));
  $('#main').innerHTML=`
  <div class="page-head"><div><p class="eyebrow">Catalog</p><h1 class="page-title">Services</h1><p>Service schemas used by the local synthetic adapter. Import actions and typed parameters, then write and test access rules. Endpoints are descriptive metadata and are never contacted.</p></div>
    <div class="bbar"><button class="btn primary" id="addSvc">Add service</button></div></div>
  <div class="svc">
    <ul class="slist">${S.services.map(x=>`<li><button data-sid="${x.id}" aria-current="${x.id===s.id}">${gly('service')}<b>${esc(x.name)}</b><span class="cnt">${x.actions.length} actions</span><small>${esc(x.id)}, ${esc(x.kind)}</small></button></li>`).join('')}</ul>
    <div>
      <div class="shead"><div><div class="t">${esc(s.name)}</div>
        <div class="smeta"><span>id <b class="code">${esc(s.id)}</b></span><span>${esc(s.kind)}</span><span class="code">${esc(s.endpoint||'No endpoint')}</span>${s.owner?`<span>Owner <b>${esc(s.owner)}</b></span>`:''}<span>${s.verified?`<span class="verified">Local schema verified ${ago(s.verified)}</span>`:'<span class="tag warn">Not verified</span>'}</span></div></div>
        <div class="bbar"><button class="btn" id="verify">Verify local adapter</button><button class="btn" id="svcRule">Add rule</button></div></div>
      <div class="table-wrap"><table class="ttable"><thead><tr><th>Action</th><th>Parameters</th><th>Rules in live policy</th><th></th></tr></thead><tbody>
        ${s.actions.map(a=>{const rs=rulesFor(a.name);return `<tr><td><b class="code">${esc(a.name)}</b> ${a.destructive?'<span class="tag warn">Destructive</span>':''}<br><span class="muted" style="font-size:13px">${esc(a.desc)}</span></td>
          <td><div class="params">${a.params.map(p=>`<span class="param ${p.required?'req':''}">${esc(p.name)}: ${p.type}</span>`).join('')||'<span class="muted">None</span>'}</div></td>
          <td>${rs.length?rs.map(r=>`<div style="margin-bottom:4px"><a href="#/builder/rules/${r.id}">${esc(subj(r.subject))}</a> <span class="rpill ${r.reaction}">${MODE_LABEL[r.reaction]}</span>${(r.conditions||[]).length?` <span class="muted" style="font-size:12.5px">if ${esc(r.conditions.map(condText).join(' and '))}</span>`:''}</div>`).join(''):`<span class="muted">No rule. Calls without a rule: ${MODE_LABEL[S.live.default_reaction]}</span>`}</td>
          <td><button class="btn small" data-addrule="${a.name}">Add rule</button></td></tr>`}).join('')}
      </tbody></table></div>
      <details style="margin-top:20px"><summary class="link" style="display:inline">View schema</summary><div class="yaml" style="font:12.5px/1.6 var(--mono);white-space:pre;overflow-x:auto;background:var(--surface);border:1px solid var(--line);padding:12px;margin-top:10px">${esc(JSON.stringify({id:s.id,name:s.name,kind:s.kind,endpoint:s.endpoint,owner:s.owner,actions:s.actions},null,2))}</div></details>
    </div>
  </div>`;
  document.querySelectorAll('[data-sid]').forEach(b=>b.onclick=()=>{location.hash='#/services/'+b.dataset.sid});
  const mkRule=action=>{let i=1;while(S.draft.rules.find(r=>r.id==='r'+i))i++;S.draft.rules.push({id:'r'+i,subject:AGENTS[0],service:s.id,action:action||s.actions[0].name,reaction:'allow'});scheduleDraft();location.hash='#/builder/rules/r'+i;toast('Draft rule created. Review it and apply.')};
  document.querySelectorAll('[data-addrule]').forEach(b=>b.onclick=()=>mkRule(b.dataset.addrule));
  $('#svcRule').onclick=()=>mkRule();
  $('#verify').onclick=async e=>{e.target.disabled=true;try{const result=await api('/services/'+encodeURIComponent(s.id)+'/verify','POST',{});await refreshState();renderServices();toast(result.message||result.status||'Local synthetic adapter schema verified. No remote endpoint was contacted.')}catch(err){showError(err)}finally{if($('#verify'))$('#verify').disabled=false}};
  $('#addSvc').onclick=addService;
}
function addService(){
  let parsed=null;
  const root=modal({title:'Add service',body:`<p>Import a schema into the local catalog. Verification checks the synthetic adapter schema; it does not connect to the endpoint.</p>
    <div class="field"><label for="sch">Service schema (JSON)</label><textarea id="sch" style="min-height:240px">${esc(SAMPLE_SCHEMA)}</textarea><div class="hint">Format: id, name, kind, endpoint, owner, and actions with typed params.</div></div>
    <div class="bbar"><button class="btn" id="imp">Import schema</button><button class="btn" id="ver" disabled>Verify local adapter</button></div>
    <div class="import-out" id="impOut"></div>`,
    actions:[{label:'Cancel'},{label:'Add service',kind:'primary',disabled:true,run:async()=>{if(!parsed)return false;await api('/services','POST',{service:parsed});await refreshState();S.selService=parsed.id;location.hash='#/services/'+parsed.id;renderServices();toast(`${parsed.name} saved. Access follows the active policy.`)}}]});
  const out=root.querySelector('#impOut'),addBtn=root.querySelector('.acts .btn.primary'),ver=root.querySelector('#ver');
  root.querySelector('#imp').onclick=()=>{try{parsed=parseSchema(root.querySelector('#sch').value);
      out.innerHTML=`<p class="ok" style="margin:0">Schema is valid: ${esc(parsed.name)} with ${parsed.actions.length} actions.</p><ul>${parsed.actions.map(a=>`<li><span class="code">${esc(a.name)}</span>(${a.params.map(p=>esc(p.name)+(p.required?'*':'')).join(', ')})${a.destructive?' <span class="tag warn">Destructive</span>':''}</li>`).join('')}</ul>`;
      addBtn.disabled=false;ver.disabled=false}
    catch(err){parsed=null;addBtn.disabled=true;ver.disabled=true;out.innerHTML=`<div class="yaml-err">${esc(err.message)}</div>`}};
  ver.onclick=()=>{if(!parsed)return;out.insertAdjacentHTML('beforeend','<p class="note-box">The imported schema is valid. Save the service, then verify it against the local synthetic adapter from the catalog.</p>')};
}

/* ===================== HISTORY ===================== */
function renderHistory(){
  const list=S.history.slice().reverse();if(!S.histSel||!S.history.find(h=>h.v===S.histSel))S.histSel=S.live.version;
  const h=S.history.find(h=>h.v===S.histSel);const prev=S.history.find(x=>x.v===h.v-1);const isLive=h.v===S.live.version;
  $('#main').innerHTML=`
  <div class="page-head"><div><p class="eyebrow">Policy</p><h1 class="page-title">Policy history</h1><p>Every version of the policy, who changed it and how. Rolling back creates a new version, history is never deleted.</p></div></div>
  <div class="hist">
    <ul class="vlist">${list.map(x=>`<li><button data-v="${x.v}" aria-current="${x.v===h.v}"><span class="vn">v${x.v}</span><span class="sm">${esc(x.summary)}</span><span class="by">${esc(x.author)}, ${esc(x.source)}</span><span class="by">${x.at.toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short'})}${x.v===S.live.version?' <span class="tag new">Live</span>':''}</span></button></li>`).join('')}</ul>
    <div>
      <div class="vhead"><div><div class="t">Version ${h.v}</div><p class="muted" style="margin:6px 0 0">${esc(h.author)} via ${esc(h.source)}, ${h.at.toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short'})}</p></div>
        ${isLive?'<span class="tag new" style="font-size:13px;padding:4px 10px">Live now</span>':`<button class="btn primary" id="rb">Roll back to v${h.v}</button>`}</div>
      <div class="tabs" role="tablist"><button role="tab" data-tab="ops" aria-selected="${S.histTab==='ops'}">Changes</button><button role="tab" data-tab="yaml" aria-selected="${S.histTab==='yaml'}">YAML diff</button></div>
      <div id="hBody"></div>
    </div>
  </div>`;
  document.querySelectorAll('[data-v]').forEach(b=>b.onclick=()=>{location.hash='#/history/'+b.dataset.v});
  document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{S.histTab=b.dataset.tab;renderHistory()});
  const body=$('#hBody');
  if(S.histTab==='ops'){
    body.innerHTML=prev?(h.ops.length?`<p class="muted" style="margin:0 0 8px">Compared with v${prev.v}</p><ul class="ops">${h.ops.map(o=>`<li><span class="k ${o.op}">${{add:'Added',remove:'Removed',change:'Changed',order:'Reordered'}[o.op]}</span><span>${esc(describe(o))}</span></li>`).join('')}</ul>`:'<p class="muted">No changes in this version.</p>'):'<p class="muted">This is the first recorded version.</p>';
  } else {
    body.innerHTML=prev?`<p class="muted" style="margin:0 0 8px">v${prev.v} → v${h.v}</p><div class="diff">${lineDiff(dump(prev.policy),dump(h.policy)).map(([k,l])=>`<div class="${k}">${k==='a'?'+ ':k==='d'?'- ':'  '}${esc(l)}</div>`).join('')}</div>`:`<div class="diff">${dump(h.policy).split('\n').map(l=>`<div class="c">  ${esc(l)}</div>`).join('')}</div>`;
  }
  const rb=$('#rb');if(rb)rb.onclick=()=>{
    const p=clone(h.policy);if(isDirty())toast('Unsaved changes in the builder will be discarded if you apply the rollback.');
    checkImpact(p,{fromDraft:true,source:'Rollback to v'+h.v,after:()=>{S.histSel=S.live.version;renderHistory()}});
  };
}

/* ===================== TRAINING DATA ===================== */
function renderTraining(){
  const checks=[...new Map(S.training.map(x=>[x.checkId,x.check])).entries()];
  $('#main').innerHTML=`
  <div class="page-head"><div><p class="eyebrow">AI checks</p><h1 class="page-title">Training data</h1><p>Every answer from an AI check is kept as an example. Reviewed examples can later train a smaller, cheaper classifier for a specific rule.</p></div>
    <div class="bbar"><button class="btn primary" id="export">Export reviewed examples</button></div></div>
  <p class="note-box">The model's label is a first draft, not ground truth. Inputs are retained after sanitization. These are actual results of the offline baseline on local synthetic traffic. No automatic retention schedule or model training is configured.</p>
  <div class="summary" id="trSum" style="grid-template-columns:repeat(6,1fr)"></div>
  <div class="filters">
    <select id="trC" aria-label="AI check"><option value="all">All AI checks</option>${checks.map(([id,n])=>`<option value="${id}" ${S.trFilters.check===id?'selected':''}>${esc(n)}</option>`).join('')}</select>
    <select id="trR" aria-label="Review status">${[['all','Any review status'],['unreviewed','Unreviewed'],['needs review','Needs review'],['confirmed','Confirmed'],['corrected','Corrected']].map(([v,l])=>`<option value="${v}" ${S.trFilters.review===v?'selected':''}>${l}</option>`).join('')}</select>
  </div>
  <div class="table-wrap"><table><thead><tr><th>Time</th><th>AI check</th><th>Input after redaction</th><th>Model label</th><th>Human review</th><th>Model, instruction</th><th class="num">Latency</th><th>Cache</th></tr></thead><tbody id="trRows"></tbody></table></div>`;
  $('#trC').onchange=e=>{S.trFilters.check=e.target.value;drawTraining()};
  $('#trR').onchange=e=>{S.trFilters.review=e.target.value;drawTraining()};
  $('#export').onclick=exportTraining;
  drawTraining();
}
function drawTraining(){
  const all=S.training;const reviewed=all.filter(x=>x.review==='confirmed'||x.review==='corrected');
  const hit=all.filter(x=>x.cache==='hit').length;const avg=all.length?all.reduce((s,x)=>s+x.lat,0)/all.length:0;
  const st=(v,l)=>`<div class="sum static"><span class="v">${v}</span><span class="l">${l}</span></div>`;
  $('#trSum').innerHTML=st(fmt(all.length),'Examples')+st(fmt(reviewed.length),'Reviewed')+st(fmt(all.filter(x=>x.review==='corrected').length),'Corrected by a person')+st(fmt(all.filter(x=>x.review==='needs review').length),'Need review')+st(Math.round(hit/Math.max(1,all.length)*100)+'%','Evaluation cache hits')+st(Math.round(avg)+' ms','Average latency');
  const f=S.trFilters;const rows=all.filter(x=>(f.check==='all'||x.checkId===f.check)&&(f.review==='all'||x.review===f.review)).slice().reverse().slice(0,150);
  const labelsOf=(id,example)=>{if(example.allowedLabels)return example.allowedLabels;const n=S.live.checks.find(c=>c.id===id);return n?(n.labels||[]).map(l=>l.label):[]};
  $('#trRows').innerHTML=rows.length?rows.map(x=>`<tr data-ex="${esc(x.id)}"><td class="muted">${t2(x.ts)}</td><td>${esc(x.check)}</td><td class="input">${esc(x.input)}</td><td><span class="lbl-code">${esc(x.label)}</span></td>
    <td>${x.review==='confirmed'?`<span class="ok">Confirmed</span> <span class="muted" style="font-size:12.5px">${esc(x.reviewer||'')}</span>`:x.review==='corrected'?`<span class="changed">Corrected to ${esc(x.corrected)}</span> <span class="muted" style="font-size:12.5px">${esc(x.reviewer||'')}</span>`:
      `<div class="tr-actions">${x.review==='needs review'?'<span class="tag fp">Needs review</span>':''}<button class="btn small" data-ok="${esc(x.id)}">Confirm</button><select data-fix="${esc(x.id)}" aria-label="Correct the label"><option value="">Correct to…</option>${labelsOf(x.checkId,x).filter(l=>l!==x.label).map(l=>`<option>${esc(l)}</option>`).join('')}</select></div>`}</td>
    <td class="muted" style="font-size:13px">${esc(x.model)}, v${x.instruction_version}</td><td class="num">${ms(x.lat)}</td><td class="muted">${x.cache}</td></tr>`).join(''):`<tr><td colspan="8" class="empty">No examples match these filters.</td></tr>`;
  document.querySelectorAll('[data-ok]').forEach(b=>b.onclick=()=>reviewTraining(b.dataset.ok,'confirmed'));
  document.querySelectorAll('[data-fix]').forEach(s=>s.onchange=()=>{if(s.value)reviewTraining(s.dataset.fix,'corrected',s.value)});
}
async function reviewTraining(id,review,corrected=null){try{await api('/training/'+encodeURIComponent(id),'PATCH',{review,corrected});await refreshState();drawTraining();toast('Review saved.')}catch(err){showError(err)}}
async function exportTraining(){
 try{const result=await api('/training/export');const jsonl=result.jsonl||'';const lines=jsonl.trim()?jsonl.trim().split('\n'):[];
  modal({title:'Export reviewed examples',wide:true,body:`<p>${lines.length} reviewed, sanitized examples. Baseline labels are not ground truth.</p><div class="diff" style="max-height:360px;overflow:auto">${lines.map(l=>`<div class="c">${esc(l)}</div>`).join('')||'No reviewed examples yet.'}</div>`,actions:[{label:'Close'},{label:'Download JSONL',kind:'primary',run:()=>download('reviewed-examples.jsonl',jsonl,'application/x-ndjson')},{label:'Copy JSONL',run:async()=>{await navigator.clipboard.writeText(jsonl);toast('JSONL copied.');return false}}]});
 }catch(err){showError(err)}
}

/* ===================== authenticated backend integration ===================== */
S.identity=null;S.ready=false;S.sessionEpoch=0;S.revision=0;S.draftRevision=0;S.testResults={};S.testResultKey=null;
let savedDraft='',savedTests='',draftTimer,testsTimer,draftSaving=null,testsSaving=null,polling=false;
const evaluationKey=()=>stableJson([S.live.version,S.draft,S.tests,SIM]);
function showError(error){if(error?.stale)return;const message=error?.message||String(error);toast(message);$('#connectionStatus').textContent=message;}
async function api(path,method='GET',body){
  if(!S.identity)throw Error('Connect with a local operator account first.');
  const epoch=S.sessionEpoch;const stale=()=>Object.assign(new Error('This response belongs to a disconnected session.'),{stale:true});
  let response;try{response=await fetch('/v1/panel'+path,{method,cache:'no-store',headers:{'Accept':'application/json','X-Action-Gate-Principal':S.identity.principal,'X-Action-Gate-Token':S.identity.token,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});}catch(error){if(epoch!==S.sessionEpoch)throw stale();throw error;}
  if(epoch!==S.sessionEpoch)throw stale();
  let data;try{data=await response.json()}catch(_){if(epoch!==S.sessionEpoch)throw stale();throw Error('The server returned an invalid response ('+response.status+').');}
  if(epoch!==S.sessionEpoch)throw stale();
  if(!response.ok){const detail=data.error?.message||data.error?.detail||data.detail||data.message||data.error;const error=new Error(typeof detail==='string'?detail:JSON.stringify(detail||data));error.status=response.status;throw error;}
  return data;
}
function applyState(state,{replaceDraft=false}={}){
  if(!state||!state.policy)throw Error('The server did not return panel state.');
  const pendingDraft=stableJson(S.draft)!==savedDraft,pendingTests=stableJson(S.tests)!==savedTests;
  S.live=clone(state.policy);S.revision=state.revision;S.draftRevision=state.draft?.revision||0;
  S.services=(state.services||[]).map(s=>({...s,verified:s.verified?new Date(s.verified):null}));
  S.history=(state.history||[]).map(h=>({...h,v:h.v??h.version,at:new Date(h.at||h.createdAt||Date.now())})).sort((a,b)=>a.v-b.v);
  S.history.forEach((h,i)=>{h.ops=h.ops|| (i?diff(S.history[i-1].policy,h.policy):[]);h.summary=h.summary||summarize(h.ops);});
  S.events=(state.events||[]).map(e=>({...e,ts:new Date(e.ts)}));
  S.training=(state.training||[]).map(e=>({...e,ts:new Date(e.ts)}));
  if(replaceDraft||(!pendingTests&&stableJson(S.tests)!==stableJson(state.tests||[]))){S.tests=clone(state.tests||[]);savedTests=stableJson(S.tests);if(!replaceDraft&&S.page==='builder'&&S.tab==='tests'){drawTests();drawTestEditor();}}
  if(replaceDraft||(!pendingDraft&&stableJson(S.draft)!==stableJson(state.draft?.policy||state.policy))){S.draft=clone(state.draft?.policy||state.policy);savedDraft=stableJson(S.draft);if(!replaceDraft&&S.page==='builder')renderBuilderKeepScroll();}
  Object.keys(HITS).forEach(k=>delete HITS[k]);S.events.forEach(e=>e.r.checks.forEach(c=>{if(!['pass','off','skipped','na'].includes(c.result))HITS[c.id]=(HITS[c.id]||0)+1;}));
  const agents=new Set(AGENTS);S.tests.forEach(t=>agents.add(t.agent));S.live.rules.forEach(r=>{if(r.subject!=='*')agents.add(r.subject)});AGENTS.splice(0,AGENTS.length,...agents);
  tid=Math.max(tid,...S.tests.map(t=>Number(String(t.id).replace(/^t/,''))||0))+1;
  updateChip();$('#connectionStatus').textContent=`Connected · ${S.identity.principal} · draft ${S.draftRevision}`;
}
function scheduleDraft(){
  if(!S.identity||stableJson(S.draft)===savedDraft)return;
  clearTimeout(draftTimer);S.testResultKey=null;$('#connectionStatus').textContent='Saving draft…';
  draftTimer=setTimeout(()=>flushDraft().catch(showError),450);
}
async function flushDraft(){
  clearTimeout(draftTimer);if(draftSaving){await draftSaving;return flushDraft()}
  if(!S.identity||stableJson(S.draft)===savedDraft)return;
  const epoch=S.sessionEpoch,snapshot=clone(S.draft),fingerprint=stableJson(snapshot),revision=S.draftRevision;
  draftSaving=(async()=>{const state=await api('/draft','POST',{policy:snapshot,expectedRevision:revision});S.draftRevision=state.draft.revision;S.revision=state.revision;
    // Apply only server-controlled metadata in place so active editor closures remain valid.
    snapshot.version=state.draft.policy.version;S.draft.version=state.draft.policy.version;
    snapshot.checks.forEach(node=>{const normalized=state.draft.policy.checks.find(item=>item.id===node.id);if(node.type==='semantic'&&normalized){node.instruction_version=normalized.instruction_version;const current=S.draft.checks.find(item=>item.id===node.id);if(current&&current.instruction===node.instruction)current.instruction_version=normalized.instruction_version;}});
    savedDraft=stableJson(snapshot);$('#connectionStatus').textContent=`Draft saved · revision ${S.draftRevision}`;})();
  try{await draftSaving}finally{if(epoch===S.sessionEpoch)draftSaving=null}
  if(epoch!==S.sessionEpoch)return;
  if(stableJson(S.draft)!==savedDraft)return flushDraft();
}
function scheduleTests(){
  if(!S.identity||stableJson(S.tests)===savedTests)return;
  clearTimeout(testsTimer);S.testResultKey=null;testsTimer=setTimeout(()=>flushTests().catch(showError),450);
}
async function flushTests(){
  clearTimeout(testsTimer);if(testsSaving){await testsSaving;return flushTests()}
  if(!S.identity||stableJson(S.tests)===savedTests)return;
  const epoch=S.sessionEpoch,tests=clone(S.tests),fingerprint=stableJson(tests);
  testsSaving=(async()=>{const state=await api('/tests','PUT',{tests});savedTests=fingerprint;S.revision=state.revision;})();
  try{await testsSaving}finally{if(epoch===S.sessionEpoch)testsSaving=null}
  if(epoch!==S.sessionEpoch)return;
  if(stableJson(S.tests)!==savedTests)return flushTests();
}
async function runSuite(){
  if(S.runningTests)return;
  const epoch=S.sessionEpoch;S.runningTests=true;try{await flushDraft();await flushTests();const key=evaluationKey();toast('Running tests on the server…');
    const result=await api('/compare','POST',{policy:S.draft,tests:S.tests,expectedVersion:S.live.version,faults:Object.fromEntries(Object.entries(SIM).filter(([,value])=>value!=='none'))});
    if(key!==evaluationKey()){toast('The draft changed during evaluation. Run tests again.');return}
    S.testResults=Object.fromEntries(result.results.map(x=>[x.id,{live:x.live.r||x.live,draft:x.draft.r||x.draft}]));S.testResultKey=key;
    if(S.page==='builder'&&S.tab==='tests'){drawTests();drawTestEditor();}
    toast(`Server evaluated ${result.results.length} test cases${Object.values(SIM).some(v=>v!=='none')?' with test-only faults':''}.`);
  }catch(err){showError(err)}finally{if(epoch===S.sessionEpoch)S.runningTests=false}
}
async function refreshState({announce=false}={}){
  const state=await api('/state'),previous=clone(S.live),oldDraft=clone(S.draft);
  const changed=state.policy.version!==previous.version;
  if(changed&&isDirty()){
    if(S.conflictVersion===state.policy.version)return state;
    S.conflictVersion=state.policy.version;
    const theirs=diff(previous,state.policy),mine=diff(previous,oldDraft);
    modal({title:'The active policy changed while you were editing',wide:true,body:`<p>Another session activated v${state.policy.version}. Choose how to update your draft.</p><h3>External changes</h3><ul>${theirs.map(x=>`<li>${esc(describe(x))}</li>`).join('')||'<li>New generation of the same policy</li>'}</ul><h3>Your draft</h3><ul>${mine.map(x=>`<li>${esc(describe(x))}</li>`).join('')}</ul><p class="hint">Keeping your draft reapplies its changes on the newer active policy. Your draft values win when both changed the same field; review and rerun impact before activation.</p>`,actions:[{label:'Use active policy',run:async()=>{applyState(state,{replaceDraft:true});S.draft=clone(S.live);savedDraft='';await flushDraft();S.conflictVersion=null;route();}},{label:'Keep my changes on top',kind:'primary',run:async()=>{applyState(state,{replaceDraft:true});S.draft=rebase(previous,oldDraft,S.live);savedDraft='';await flushDraft();S.conflictVersion=null;route();}}]});
    return state;
  }
  applyState(state);
  if(changed){const changes={};diff(previous,S.live).forEach(o=>{(changes[o.id]=changes[o.id]||[]).push(o)});S.ext={v:S.live.version,author:'Another authenticated session',at:new Date(),changes};S.testResultKey=null;if(S.page==='builder')renderBuilderKeepScroll();}
  if(announce){if(!changed)toast('Active policy is unchanged. Draft and audit refreshed.');route();}
  return state;
}
function download(filename,text,type='text/plain'){
  const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function renderLogin(){
  $('#main').innerHTML='<div class="page-head"><div><p class="eyebrow">Action Gate</p><h1 class="page-title">Connect to the control panel</h1><p>Use your local operator principal and token above. Policy drafts, tests, service schemas, audit events and reviews are stored by the backend. Credentials stay in memory and are forgotten on reload.</p></div></div>';
  $('#runtimeNotice').hidden=true;$('#disconnect').hidden=true;$('#connect').hidden=false;$('#liveChip span').textContent='Not connected';
}
async function invokeSynthetic(){
  if(!S.tests.length){toast('Add a test case first to define a synthetic request.');return;}
  let invocationKey=crypto.randomUUID(),invocationFingerprint=null;
  const root=modal({title:'Run a synthetic request',wide:true,body:`<p>This sends an explicit request to the local server as the selected test agent. Allowed service calls execute once against the local synthetic adapter. No external endpoint is contacted.</p><div class="field"><label for="invokeCase">Request template</label><select id="invokeCase">${S.tests.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('')}</select></div><pre id="invokePreview" class="payload"></pre>`,actions:[{label:'Cancel'},{label:'Run request',kind:'primary',run:async root=>{await flushTests();const test=S.tests.find(t=>t.id===root.querySelector('#invokeCase').value);const request=testReq(test),fingerprint=JSON.stringify(request);if(invocationFingerprint!==null&&invocationFingerprint!==fingerprint)invocationKey=crypto.randomUUID();invocationFingerprint=fingerprint;const event=await api('/invoke','POST',{request,idempotencyKey:invocationKey,onBehalfOf:request.agent});await refreshState();location.hash='#/requests/'+event.id;renderDetail(event.id);toast('Synthetic request recorded by the server.');}}]});
  const preview=()=>{const t=S.tests.find(t=>t.id===root.querySelector('#invokeCase').value);root.querySelector('#invokePreview').textContent=JSON.stringify(testReq(t),null,2)};
  root.querySelector('#invokeCase').onchange=preview;preview();
}
const originalBuilder=renderBuilder;
renderBuilder=function(){
  originalBuilder();
  const bar=$('.page-head .bbar');if(!bar)return;
  const saveNote=document.createElement('span');saveNote.className='muted';saveNote.style.fontSize='12px';saveNote.textContent='Draft edits autosave; activation is separate.';bar.insertAdjacentElement('afterend',saveNote);
  const importButton=document.createElement('button');importButton.className='btn';importButton.id='importYaml';importButton.textContent='Import YAML';
  const exportButton=document.createElement('button');exportButton.className='btn';exportButton.id='exportYaml';exportButton.textContent='Export YAML';
  const file=document.createElement('input');file.type='file';file.accept='.yaml,.yml,.txt';file.hidden=true;file.id='yamlFile';
  importButton.onclick=()=>file.click();file.onchange=async()=>{try{if(!file.files[0])return;S.draft=fromYaml(await file.files[0].text());S.yamlErr=null;scheduleDraft();renderBuilderKeepScroll();toast('YAML imported into the draft. Review and check impact before applying.')}catch(err){showError(err)}};
  exportButton.onclick=()=>download('policy-draft.yaml',dump(S.draft),'application/yaml');
  bar.append(importButton,exportButton,file);
};
const originalDetail=renderDetail;
renderDetail=function(id){
  originalDetail(id);const event=S.events.find(e=>e.id===id);if(!event||!event.action)return;
  const box=document.createElement('section');box.className='sec';box.id='executionOutcome';
  const action=event.action,output=event.output;
  box.innerHTML=`<h2>Execution and disclosure</h2><dl class="facts"><dt>Action</dt><dd>${esc(action.outcome)}</dd><dt>Dispatched</dt><dd>${action.dispatched?'Yes':'No'}</dd><dt>Disclosure</dt><dd>${esc(output?.disclosure||'none')}</dd><dt>Transport actor</dt><dd>${esc(event.actor||'')}</dd></dl>${action.detail?`<pre class="payload">${esc(typeof action.detail==='string'?action.detail:JSON.stringify(action.detail,null,2))}</pre>`:''}${output?.text?`<pre class="payload">${esc(output.text)}</pre>`:''}${event.outputR?`<h3>Output inspection</h3>${chainHtml(event.outputR)}`:''}<p class="hint">Input policy result, service execution and output disclosure are separate. A withheld output does not undo a completed action.</p>`;
  $('.detail > div').append(box);
};
function resetAsyncState(){
  clearTimeout(draftTimer);clearTimeout(testsTimer);draftSaving=null;testsSaving=null;polling=false;S.runningTests=false;S.conflictVersion=null;S.testResults={};S.testResultKey=null;S.draftRevision=0;S.revision=0;
  Object.keys(SIM).forEach(k=>delete SIM[k]);
}
$('#connectionForm').onsubmit=async event=>{
  event.preventDefault();S.sessionEpoch++;const epoch=S.sessionEpoch;resetAsyncState();S.ready=false;renderLogin();$('#connect').disabled=true;
  S.identity={principal:$('#principal').value.trim(),token:$('#token').value};
  try{const state=await api('/state');applyState(state,{replaceDraft:true});S.ready=true;$('#token').value='';$('#connect').hidden=true;$('#disconnect').hidden=false;$('#runtimeNotice').hidden=false;route();}
  catch(err){if(epoch!==S.sessionEpoch)return;S.identity=null;renderLogin();showError(err)}finally{if(epoch===S.sessionEpoch)$('#connect').disabled=false}
};
$('#disconnect').onclick=()=>{S.sessionEpoch++;resetAsyncState();S.identity=null;S.ready=false;S.events=[];S.training=[];S.replay={};S.tests=[];S.history=[];S.services=[];S.live={version:0,checks:[],rules:[],default_reaction:'block'};S.draft=clone(S.live);savedDraft='';savedTests='';$('#connectionStatus').textContent='Disconnected';$('#modalRoot').innerHTML='';renderLogin();};
try{const theme=localStorage.getItem('gs-theme');if(theme)document.documentElement.dataset.theme=theme}catch(_){}
$('#themeBtn').onclick=()=>{const root=document.documentElement;root.dataset.theme=root.dataset.theme==='light'?'dark':'light';try{localStorage.setItem('gs-theme',root.dataset.theme)}catch(_){}};
$('#liveChip').onclick=()=>{location.hash='#/builder'};
setInterval(async()=>{if(!S.identity||S.paused||polling||draftSaving||testsSaving||$('#modalRoot').children.length)return;polling=true;const epoch=S.sessionEpoch;try{await refreshState();if(S.page==='requests'&&!S.detailId&&$('#rows')){drawSummary();drawRows();}}catch(err){showError(err)}finally{if(epoch===S.sessionEpoch)polling=false}},4000);
window.addEventListener('beforeunload',event=>{if(S.identity&&(stableJson(S.draft)!==savedDraft||stableJson(S.tests)!==savedTests)){event.preventDefault();event.returnValue='';}});
renderLogin();


async function reportApi(path){
  const epoch=S.sessionEpoch;
  const response=await fetch(path,{cache:'no-store',headers:{'X-Action-Gate-Principal':S.identity.principal,'X-Action-Gate-Token':S.identity.token}});
  if(!response.ok)throw Error('Report request failed: '+response.status);
  const data=await response.json();
  if(epoch!==S.sessionEpoch)throw Object.assign(new Error('Disconnected session'),{stale:true});
  return data;
}
function renderReport(){
  $('#main').innerHTML=`<h1 class="page-title">Unified report</h1><p>Panel, MCP and model/legacy operations in the same UTC window. Blocks are policy decisions, not confirmed attacks.</p><div class="filters"><select id="reportPeriod" aria-label="Report period"><option value="60">Last 60 minutes</option><option value="1440">Last 24 hours</option><option value="10080">Last 7 days</option></select><button class="btn" id="loadReport">Refresh report</button><button class="btn" id="exportReport" disabled>Export security audit (NDJSON)</button><input type="search" id="reportSearch" placeholder="Request / operation ID, agent or target" aria-label="Search unified report"></div><div id="reportBody"></div>`;
  let snapshot=null,query='';
  const draw=()=>{if(!snapshot)return;const q=$('#reportSearch').value.toLowerCase();const rows=snapshot.records.filter(r=>JSON.stringify(r).toLowerCase().includes(q));
    $('#reportBody').innerHTML=`<p>${esc(snapshot.window.since)} — ${esc(snapshot.window.until)} · ${snapshot.total} operations</p><p>${esc(snapshot.note)}</p><h2>Requests and usage by agent / model</h2><table><thead><tr><th>Source</th><th>Agent / model</th><th>Requests</th><th>Synthetic estimated tokens</th><th>Provider reported tokens</th><th>Unknown model usage</th></tr></thead><tbody>${snapshot.byAgentModel.map(g=>`<tr><td>${esc(g.source)}</td><td>${esc(g.agent)} / ${esc(g.model||"—")}</td><td>${g.requests}</td><td>${g.syntheticEstimatedTokens}</td><td>${g.providerReportedTokens}</td><td>${g.unknownModelUsage}</td></tr>`).join('')}</tbody></table><table><thead><tr><th>ID / source</th><th>Agent / target</th><th>Decision / outcome</th><th>Evidence</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.invocation_id)}<br>${esc(r.source)}</td><td>${esc(r.agent)}<br>${esc(r.target)}</td><td>${esc(r.decision)} / ${esc(r.action_outcome)}</td><td><details><summary>Operation metadata</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details></td></tr>`).join('')}</tbody></table>`;
  };
  $('#reportSearch').oninput=draw;
  $('#loadReport').onclick=async()=>{try{const until=new Date(),since=new Date(until-Number($('#reportPeriod').value)*60000);query=new URLSearchParams({since:since.toISOString(),until:until.toISOString()}).toString();snapshot=await reportApi('/v1/report?'+query);if(S.page!=='report')return;draw();$('#exportReport').disabled=false;}catch(e){showError(e)}};
  $('#exportReport').onclick=async()=>{try{let cursor=null,rows=[];do{const p=await reportApi('/v1/audit/events?'+query+'&limit=500'+(cursor?'&cursor='+encodeURIComponent(cursor):''));rows.push(...p.events);cursor=p.nextCursor;}while(cursor);download('security-audit.ndjson',rows.map(r=>JSON.stringify(r)).join('\n')+'\n','application/x-ndjson');}catch(e){showError(e)}};
  $('#loadReport').click();
}
