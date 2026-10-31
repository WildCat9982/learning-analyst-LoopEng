'use strict';
let current=null, readiness=null, timer=null, refreshing=null, pendingAction=null;
let reportOrigin='run', reportTrigger=null, reportFocus=null, reportSequence=0, outcomeError=false;
const htmlKeys=new Map();
const $=s=>document.querySelector(s);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const criteria=['completeness','clarity','depth'];
const title=x=>x.charAt(0).toUpperCase()+x.slice(1);
function active(job){return !!job&&['queued','running'].includes(job.status);}
function readDraft(key){try{return sessionStorage.getItem(key);}catch{return null;}}
function writeDraft(key,value){try{sessionStorage.setItem(key,value);}catch{}}
function clearDraft(key){try{sessionStorage.removeItem(key);}catch{}}
function message(text){$('#message').hidden=!text;$('#message').textContent=text||'';}
async function api(path,body){
 const controller=new AbortController(), deadline=setTimeout(()=>controller.abort(),15000);
 try{
  const r=await fetch('api/'+path,{...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),signal:controller.signal});
  let d;try{d=await r.json();}catch{throw Error('The connection was interrupted. Reconnect to your saved work or ask Coding chat for help.');}
  if(!r.ok)throw Error(d.error||'This action could not finish. Try again.');
  return d;
 }catch(e){if(e.name==='AbortError')throw Error('The connection took too long. Reconnect to check your saved work.');throw e;}
 finally{clearTimeout(deadline);}
}
function setHTML(selector,key,html){
 const el=$(selector);if(htmlKeys.get(selector)===key)return;
 const focused=el.contains(document.activeElement)?document.activeElement:null;
 const focusKey=focused?.dataset.focus;
 const opened=new Map(Array.from(el.querySelectorAll('details[id]')).map(d=>[d.id,d.open]));
 el.innerHTML=html;htmlKeys.set(selector,key);
 for(const [id,open] of opened){const d=document.getElementById(id);if(d&&el.contains(d))d.open=open;}
 if(focusKey){const same=Array.from(el.querySelectorAll('[data-focus]')).find(e=>e.dataset.focus===focusKey);same?.focus({preventScroll:true});}
}
function bindField(field,key,saved){
 if(field.dataset.draftKey!==key){
  field.dataset.draftKey=key;field.value=readDraft(key)??saved??'';
 }else if(document.activeElement!==field&&readDraft(key)===null)field.value=saved??'';
 field.oninput=()=>{writeDraft(key,field.value);if(field.name==='explanation'){outcomeError=false;renderOutcome();renderReadiness();}};
}
function outcomeDirty(){return !!current?.comparison?.complete&&$('#outcome-form textarea').value.trim()!==(current.outcome?.explanation||'');}
function reduced(){return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;}
function jump(step,target){
 const card=document.getElementById(step);if(!card)return;
 card.open=true;
 const el=target?document.querySelector(target):card.querySelector('summary');
 if(el){for(let p=el.parentElement;p&&p!==card;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;}
 card.scrollIntoView({block:'start',behavior:reduced()?'instant':'smooth'});
 if(el&&!el.disabled&&!el.hidden){if(!el.hasAttribute('tabindex')&&!['TEXTAREA','BUTTON','A','SUMMARY','SELECT'].includes(el.tagName))el.tabIndex=-1;el.focus({preventScroll:true});}
}
function token(value,label){
 if(typeof value!=='boolean')return '<span class="check-pending">'+(label?esc(label)+': ':'')+'Not evaluated</span>';
 return '<span class="'+(value?'check-pass':'check-fail')+'">'+(label?esc(label)+': ':'')+(value?'✓ Pass':'✕ Fail')+'</span>';
}
function reportButton(id,label,focus){
 return id?'<button class="text-button" data-report="'+esc(id)+'" data-focus="'+esc(focus)+'">'+esc(label)+'</button>':esc(label);
}
function baselineTable(rows){
 return '<div class="table-scroll"><table class="baseline-table"><caption>Baseline · first-draft quality</caption><thead><tr><th scope="col">Requirement</th>'+criteria.map(k=>'<th scope="col">'+title(k)+'</th>').join('')+'</tr></thead><tbody>'+
 rows.map(r=>'<tr><th scope="row">'+reportButton(r.before_run,r.title,'baseline-'+r.document)+'</th>'+criteria.map(k=>'<td>'+token(r.before?.[k])+'</td>').join('')+'</tr>').join('')+
 '</tbody></table></div>';
}
function table(rows,complete=false){
 return '<p class="narrow-table-help">Scroll sideways to see both versions.</p><div class="table-scroll"><table><caption>First-draft quality · before and after</caption><thead><tr><th scope="col">Requirement</th><th scope="col">Before</th><th scope="col">After</th></tr></thead><tbody>'+
 rows.map(r=>'<tr><th scope="row">'+esc(r.title)+'</th>'+['before','after'].map(phase=>'<td>'+criteria.map(k=>{
  const left=r.before?.[k],right=r.after?.[k];
  const change=complete&&phase==='after'&&typeof left==='boolean'&&typeof right==='boolean'&&left!==right?'<span class="change-label '+(right?'check-improved':'check-regressed')+'">'+(right?'↑ Improved':'↓ Regressed')+'</span>':'';
  return '<span class="criterion-token">'+token(r[phase]?.[k],title(k))+change+'</span>';
 }).join('')+(r[phase+'_run']?reportButton(r[phase+'_run'],'View report',phase+'-'+r.document):'')+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
}
function counts(c){return criteria.map(k=>title(k)+': '+(c?.[k]||0)+'/5').join(' · ');}
function comparisonSummary(c,busy){
 if(!c.complete){
  const n=(c.rows||[]).filter(r=>r.after).length;
  return '<p class="notice"><strong>'+(busy?'Evaluation in progress':'Evaluation incomplete')+' · '+n+' of 5 evaluated</strong></p><p>The overall result and change will appear when all five evaluations are saved.</p>';
 }
 const changes={improved:0,regressed:0};
 for(const r of c.rows||[])for(const k of criteria)if(typeof r.before?.[k]==='boolean'&&typeof r.after?.[k]==='boolean'&&r.before[k]!==r.after[k])changes[r.after[k]?'improved':'regressed']++;
 return '<p class="notice '+(c.qualifies?'positive':'')+'"><strong>'+esc(c.status)+'</strong></p><p>First-draft quality: <strong>'+(c.passed?.[0]||0)+'/15 → '+(c.passed?.[1]||0)+'/15</strong> ('+(c.change_percentage_points>0?'+':'')+(c.change_percentage_points||0)+' percentage points).</p><p>Before: '+counts(c.before)+'<br>After: '+counts(c.after)+'</p><p>'+changes.improved+' checks improved · '+changes.regressed+' regressed. The result target uses totals for each criterion.</p>';
}
function showStatus(selector,text,state='idle'){
 const el=$(selector);el.hidden=!text;el.dataset.state=state;el.setAttribute('aria-busy',String(['queued','running','saving'].includes(state)));
 el.innerHTML=(['queued','running','saving'].includes(state)?'<span class="running-dot" aria-hidden="true"></span>':'')+esc(text);
}
function decisionConfirmation(s){
 const d=s.decision||{},j=s.job,c=s.comparison||{};
 if(pendingAction?.kind==='decision')return 'Saving your decision…';
 if(!d.decision)return '';
 const prefix=d.decision==='apply'?'Change saved.':'Original instructions kept.';
 if(c.complete&&s.event?.status==='completed')return prefix+' Evaluation complete. Review the results in Step 4.';
 if(j?.status==='queued')return prefix+' Evaluation queued. Follow progress in Step 4.';
 if(j?.status==='running')return prefix+(d.decision==='apply'?' Evaluating the updated instructions…':' Evaluating the results…');
 if(j?.status==='failed')return prefix+' Evaluation failed. Resume in Step 4.';
 if(j?.status==='interrupted')return prefix+' Evaluation stopped. Resume in Step 4.';
 return prefix+' Evaluation is waiting to start. Resume in Step 4.';
}
function renderProgress(s){
 const j=s.job,p=s.proposal||{},d=s.decision||{},busy=active(j);
 let text='',state=j?.status||'idle';
 if(pendingAction?.kind==='cancel'&&busy){text='Stopping…';state='saving';}
 else if(pendingAction?.kind==='resume'&&!d.decision){text='Resuming analysis…';state='saving';}
 else if(pendingAction&&['analysis','new'].includes(pendingAction.kind)){text='Starting analysis…';state='saving';}
 else if(!d.decision&&busy){
  text=j.status==='queued'?'Analysis queued.':s.baseline?.complete?'Your analyst is reviewing the results…':'Reviewing requirements · '+Math.min(5,j.completed||0)+' of 5 saved';
 }else if(!d.decision&&['failed','interrupted'].includes(j?.status))text=j.error||'Analysis stopped. Resume your saved work.';
 else if(p.decision)text='Analysis complete. Review the suggestion in Step 3.';
 showStatus('#analysis-progress',text,state);
 let evaluation='';
 if(d.decision){
  if(pendingAction?.kind==='cancel'){evaluation='Stopping…';state='saving';}
  else if(pendingAction?.kind==='resume'){evaluation='Reconnecting to your saved work…';state='saving';}
  else if(j?.status==='queued')evaluation='Evaluation queued.';
  else if(busy)evaluation='Evaluating requirements · '+Math.min(5,j.completed||0)+' of 5 saved';
  else if(['failed','interrupted'].includes(j?.status))evaluation=j.error||'Evaluation stopped. Resume your saved work.';
  else evaluation=s.comparison?.complete?'Evaluation complete. Compare the results below.':'Evaluation is waiting to start. Resume your saved work.';
 }
 showStatus('#evaluation-progress',evaluation,state);
 const confirmation=decisionConfirmation(s);
 setHTML('#decision-saved',JSON.stringify([d,s.event,confirmation]),d.decision?'<p class="notice"><strong>'+esc(confirmation)+'</strong></p><p>'+esc(d.reason)+'</p><a href="#compare" data-step="compare">Open Step 4</a><details id="instruction-difference"><summary>View saved instruction difference</summary><pre>'+esc(d.diff||'The original instructions were kept.')+'</pre></details><details id="automatic-trigger"><summary>How this decision starts the next reviews</summary><p>Saved decision → chosen instructions → evaluation of the same five requirements.</p></details>':confirmation?'<p role="status">'+esc(confirmation)+'</p>':'');
 const resume=!!j&&['failed','interrupted'].includes(j.status)||!!d.decision&&!s.comparison?.complete&&!busy;
 $('#resume').hidden=!resume;$('#resume').disabled=busy||!!pendingAction;
 $('#cancel').hidden=!busy;$('#cancel').disabled=!!pendingAction;
 $('#job-controls').hidden=!(resume||busy);
 const dest=$(d.decision?'#evaluation-controls':'#analysis-controls');
 if($('#job-controls').parentElement!==dest)dest.appendChild($('#job-controls'));
}
function renderOutcome(){
 if(!current)return;
 const field=$('#outcome-form textarea'),saved=current.outcome?.explanation,dirty=outcomeDirty();
 $('#outcome-form').hidden=!current.comparison?.complete;
 $('#save-outcome').disabled=!!pendingAction;$('#save-outcome').textContent=outcomeError?'Retry save':'Save explanation';
 let text='',state='check-pending';
 if(pendingAction?.kind==='outcome')text='Saving…';
 else if(outcomeError){text='Could not save. Your answer is still here. Try again.';state='check-missing';}
 else if(saved&&!dirty){text='Saved. Edit if needed.';state='check-saved';}
 else if(field.value.trim())text='Unsaved changes.';
 else if(saved)text='Unsaved changes. Your previous answer is saved.';
 else text='Add your outcome explanation.';
 $('#outcome-status').textContent=text;$('#outcome-status').className=state;
}
function render(s){
 const j=s.job,busy=active(j),p=s.proposal||{},d=s.decision||{},c=s.comparison||{};
 $('#build-status').textContent=s.analyst_built?'Analyst found':'Start in Coding chat';
 $('#analyse').hidden=!!p.decision||!!d.decision;
 $('#analyse').disabled=busy||!!pendingAction||!s.analyst_built;
 $('#analyse').textContent=s.baseline?.valid?'Resume analysis':'Run analysis';
 $('#build-needed').hidden=!!s.analyst_built;
 $('#run-status').textContent=p.decision?'Analysis complete':busy?(s.baseline?.complete?'Analyst reviewing results':'Reviews running'):s.baseline?.complete?'Reviews saved':j?.status==='failed'?'Needs attention':'Not run';
 const rows=c.rows||[];
 setHTML('#baseline',JSON.stringify([rows.map(r=>({document:r.document,title:r.title,before:r.before,before_run:r.before_run})),s.baseline?.valid,s.baseline?.complete]),s.baseline?.valid?'<p><strong>'+(s.baseline.complete?'Baseline saved':'Baseline in progress')+'</strong></p><p>These checks use each report\'s first draft, before the agent revises it.</p>'+baselineTable(rows):'');
 setHTML('#requirements',JSON.stringify(s.requirements),(s.requirements||[]).map((r,i)=>'<details id="requirement-'+i+'"><summary>'+esc(r.title)+'</summary><p class="requirement-text">'+esc(r.text)+'</p></details>').join(''));
 $('#decision-status').textContent=d.decision?'Decision saved':p.decision?'Your decision':'Waiting for analysis';
 if(p.decision){
  setHTML('#proposal',JSON.stringify([s.candidate,p]),'<h3>Analyst finding</h3><p>'+esc(p.explanation)+'</p><ul>'+(p.evidence||[]).map((e,i)=>'<li>'+reportButton(e.run_id,(rows.find(r=>r.before_run===e.run_id)?.title||'Saved report')+' · first draft','evidence-'+i)+'<p>'+esc(e.quote).slice(0,350)+'</p></li>').join('')+'</ul>'+(p.decision==='propose'?'<h3>Suggested instruction change</h3><p>'+esc(p.section)+'</p><pre>'+esc(p.change)+'</pre>':''));
  if($('#decide').dataset.stageCandidate!==s.candidate){$('#decide').open=true;$('#decide').dataset.stageCandidate=s.candidate;}
 }else setHTML('#proposal','empty','');
 $('#decision-form').hidden=!p.decision||!!d.decision;
 bindField($('#decision-form textarea'),'capstone-reason-'+s.candidate,'');
 setHTML('#decision-buttons',String(p.decision),p.decision==='keep'?'<button value="keep">Keep original and evaluate</button>':'<button value="apply">Accept and evaluate</button><button class="secondary" value="reject">Keep original and evaluate</button>');
 $('#decision-buttons').querySelectorAll('button').forEach(b=>b.disabled=busy||!!pendingAction);
 $('#comparison-status').textContent=c.complete?'Experiment complete':d.decision?(j?.status==='failed'?'Evaluation needs attention':j?.status==='interrupted'?'Evaluation stopped':j?.status==='queued'?'Evaluation queued':j?.status==='running'?'Evaluating':'Waiting to evaluate'):'Waiting for a decision';
 if(d.decision){
  if($('#compare').dataset.stageCandidate!==s.candidate){$('#compare').open=true;$('#compare').dataset.stageCandidate=s.candidate;}
  let note='';
  if(c.complete&&!c.qualifies){
   const kept=['keep','reject'].includes(d.decision),declining=criteria.filter(k=>c.after?.[k]<c.before?.[k]);
   const why=kept&&c.passed[0]<12?'The original baseline is below 12/15. Keeping it does not meet the result target.':declining.length?'The total for '+declining.map(title).join(', ')+' fell.':'This change needs at least 12/15 checks or three more than the baseline.';
   note='<p>'+esc(why)+' You can explain this result and submit partial work, or test a different supported suggestion.</p>';
  }
  setHTML('#comparison',JSON.stringify([s.candidate,c,busy]),comparisonSummary(c,busy)+note+table(rows,!!c.complete));
 }else setHTML('#comparison','empty','');
 bindField($('#outcome-form textarea'),'capstone-outcome-'+s.candidate,s.outcome?.explanation);
 renderOutcome();
 $('#new-candidate').hidden=!c.complete;$('#new-candidate').disabled=busy||!!pendingAction;
 setHTML('#history',JSON.stringify([s.candidates,s.candidate]),(s.candidates||[]).map((id,i)=>'<button class="text-button" data-candidate="'+esc(id)+'" data-focus="history-'+i+'">Decision '+(i+1)+(id===s.candidate?' · current':'')+'</button>').join(' '));
 renderProgress(s);
}
function destination(e){
 const s=current||{},p=s.proposal||{},d=s.decision||{},c=s.comparison||{},busy=active(s.job),built=s.analyst_built;
 const wait={step:'run',target:'#analysis-progress',text:busy?'Analysis running.':'Run the analysis.',action:'Open Step 2',state:busy?'pending':'missing'};
 const decision=p.decision?{step:'decide',target:'#decision-form textarea',text:'Add your decision reason.',action:'Open Step 3',state:'missing'}:wait;
 const evaluation={step:'compare',target:busy?'#evaluation-progress':'#resume',text:busy?(s.job.status==='queued'?'Evaluation queued.':'Evaluation running.'):'Resume the evaluation.',action:'Open Step 4',state:busy?'pending':'missing'};
 const id=e.id||({'Executed analyst and supporting evidence':'analyst','Saved decision and automatic evaluation':'decision_event','Complete first-attempt comparison':'comparison','First-draft quality comparison':'comparison','Saved short explanations':'explanations','Result target':'result'}[e.loop]);
 const names={analyst:'Analyst recommendation',decision_event:'Decision and evaluation',comparison:'First-draft comparison',explanations:'Your explanations',result:'Result target'};
 if((s.gates?.[id]??(e.status==='saved'))&&!(id==='explanations'&&outcomeDirty()))return {id,name:names[id]||e.loop,state:'saved',text:'Saved.'};
 let next;
 if(id==='analyst')next=!built?{step:'build',target:'#build summary',text:'Build your analyst.',action:'Open Step 1',state:'missing'}:{...wait,target:busy?'#analysis-progress':$('#resume').hidden?'#analyse':'#resume'};
 else if(id==='decision_event'||id==='comparison')next=d.decision?evaluation:decision;
 else if(id==='explanations'){
  if(!d.reason)next=decision;
  else if(!c.complete)next=evaluation;
  else next={step:'compare',target:$('#outcome-form textarea').value.trim()?'#save-outcome':'#outcome-form textarea',text:outcomeError?'Retry saving your explanation.':$('#outcome-form textarea').value.trim()?'Save your explanation.':'Add your outcome explanation.',action:'Open Step 4',state:outcomeDirty()&&s.outcome?.saved_at?'pending':'missing'};
 }else if(id==='result')next=c.complete?{step:'compare',target:'#comparison',text:'Below the result target. Partial work can be submitted.',action:'Review results',state:'missing'}:d.decision?evaluation:decision;
 else next=wait;
 return {id,name:names[id]||e.loop,...next};
}
function renderReadiness(){
 if(!current||!readiness)return;
 const entries=readiness.entries.map(destination);
 const key=JSON.stringify(entries);
 setHTML('#readiness',key,entries.map(e=>'<div class="readiness-item" data-readiness="'+esc(e.id)+'"><strong>'+esc(e.name)+'</strong><span class="'+(e.state==='saved'?'check-saved':e.state==='pending'?'check-pending':'check-missing')+'">'+(e.state==='saved'?'✓ ':e.state==='pending'?'◷ ':'✕ ')+esc(e.text)+'</span>'+(e.step?'<a class="text-button" href="#'+esc(e.step)+'" data-step="'+esc(e.step)+'" data-target="'+esc(e.target||'')+'">'+esc(e.action)+'</a>':'')+'</div>').join(''));
 const incomplete=entries.filter(e=>e.state!=='saved');
 let summary;
 if(active(current.job))summary=current.decision?.decision?'Evaluation is running in Step 4.':'Analysis is running in Step 2.';
 else if(outcomeDirty()&&current.comparison?.complete)summary=$('#outcome-form textarea').value.trim()?'Save your explanation to include it in your submission.':'Add your outcome explanation in Step 4.';
 else if(current.evidence_ready&&!current.comparison?.qualifies)summary='Your evidence is saved. The result is below target; partial work can be submitted.';
 else if(!incomplete.length)summary='Evidence ready for submission';
 else if(incomplete.length===1&&incomplete[0].id==='explanations')summary='One item remains: save your outcome explanation in Step 4.';
 else summary=incomplete.length+' items remain. Follow the links below to continue.';
 $('#submission-status').textContent=summary;
}
async function refresh(){
 if(refreshing)return refreshing;
 refreshing=(async()=>{
  let reconnect=false;
  try{current=await api('capstone');render(current);readiness=await api('readiness');renderReadiness();if(readiness.errors?.length)message(readiness.errors.join(' '));}
  catch(e){message(e.message);reconnect=true;}
  finally{clearTimeout(timer);if(reconnect||active(current?.job))timer=setTimeout(refresh,2000);}
 })();
 try{return await refreshing;}finally{refreshing=null;}
}
async function action(path,body,kind,onSaved){
 if(pendingAction)return false;
 pendingAction={kind};message('');
 if(current){render(current);renderReadiness();}
 try{
  const result=await api(path,body);onSaved?.(result);
  if(refreshing)await refreshing;
  await refresh();return true;
 }catch(e){message(e.message);if(kind==='outcome')outcomeError=true;await refresh();if(kind==='outcome'&&current?.outcome?.explanation===body.explanation.trim()){outcomeError=false;clearDraft('capstone-outcome-'+current.candidate);message('');return true;}return false;}
 finally{pendingAction=null;if(current){render(current);renderReadiness();}}
}
function placeReport(origin){
 reportOrigin=origin||reportOrigin;
 const host=document.querySelector('#'+reportOrigin+' .step-body');if(host)host.appendChild($('#report'));
 $('#report').hidden=false;
}
function closeReport(){
 reportSequence++;$('#report').hidden=true;
 const card=document.getElementById(reportOrigin);
 let target=reportTrigger?.isConnected?reportTrigger:null;
 if(!target&&reportFocus)target=Array.from(card.querySelectorAll('[data-focus]')).find(e=>e.dataset.focus===reportFocus);
 (target||card.querySelector('summary'))?.focus({preventScroll:true});
}
async function showReport(id,draft=1,trigger=null,origin=null,changing=false){
 const sequence=++reportSequence;
 if(trigger){reportTrigger=trigger;reportFocus=trigger.dataset.focus;}
 try{
  const r=await api('capstone/reports/'+encodeURIComponent(id)+'?draft='+draft);if(sequence!==reportSequence)return;
  placeReport(origin);
  const verdict={satisfied:'Passed',needs_revision:'Needs revision',ungraded:'Not verified',failed:'Needs attention',max_iterations_reached:'Review stopped'};
  $('#report').innerHTML='<button id="close-report">Close report</button><h2 tabindex="-1">'+esc(r.phase)+' · '+esc(r.title)+' · '+esc(r.label)+'</h2><label>Saved draft <select id="draft-select">'+r.drafts.map(x=>'<option value="'+x.number+'" '+(x.number===r.draft?'selected':'')+'>'+esc(x.label)+'</option>').join('')+'</select></label><p><strong>Selected draft: '+esc(verdict[r.selected.result]||r.selected.result)+'</strong>. Final run: '+esc(verdict[r.final_status]||r.final_status)+' after '+r.revisions+' correction(s).</p><h3>Feedback on this draft</h3><ul>'+r.selected.criteria.map(c=>'<li>'+token(c.passed,title(c.name))+' '+esc(c.gap||'')+'</li>').join('')+'</ul><details><summary>Read this report and its requirement</summary><p class="requirement-text">'+esc(r.requirement)+'</p><pre>'+esc(r.selected.analysis_markdown)+'</pre></details><details><summary>View tool use and verification corrections</summary><p>Check what was fetched, which write/edit produced this draft, and what feedback a later correction addressed.</p><pre>'+esc(JSON.stringify(r.trace,null,2))+'</pre>'+(r.next?'<h3>Next correction · '+esc(r.next_label)+'</h3><pre>'+esc(r.changes)+'</pre>':'<p>No later correction in this run.</p>')+'</details>';
  $('#draft-select').onchange=e=>showReport(id,Number(e.target.value),null,reportOrigin,true);
  if(changing)$('#draft-select').focus({preventScroll:true});else{$('#report').scrollIntoView({block:'start',behavior:reduced()?'instant':'smooth'});$('#report h2').focus({preventScroll:true});}
 }catch(e){if(sequence===reportSequence)message(e.message);}
}
$('#analyse').onclick=()=>action('capstone/analyze',{},'analysis');
$('#resume').onclick=()=>action('capstone/resume',{candidate:current.candidate},'resume');
$('#cancel').onclick=()=>action('batch-jobs/'+current.job.id+'/cancel',{},'cancel');
$('#new-candidate').onclick=()=>action('capstone/analyze',{new_candidate:true},'new');
$('#decision-form').onsubmit=e=>{e.preventDefault();if(e.submitter)action('capstone/decisions',{candidate:current.candidate,decision:e.submitter.value,reason:e.target.elements.reason.value},'decision');};
$('#outcome-form').onsubmit=e=>{
 e.preventDefault();const text=e.target.elements.explanation.value,key='capstone-outcome-'+current.candidate;
 action('capstone/outcome',{candidate:current.candidate,explanation:text},'outcome',saved=>{current.outcome=saved;outcomeError=false;if(text.trim()===saved.explanation)clearDraft(key);});
};
document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-step],[data-report],[data-candidate],#close-report');if(!el)return;
 if(el.dataset.step){e.preventDefault();jump(el.dataset.step,el.dataset.target);return;}
 if(el.id==='close-report'){closeReport();return;}
 const origin=el.closest('.step-card')?.id||'compare';
 if(el.dataset.report){await showReport(el.dataset.report,1,el,origin);return;}
 if(el.dataset.candidate){
  const sequence=++reportSequence;reportTrigger=el;reportFocus=el.dataset.focus;
  try{
   const old=await api('capstone?candidate='+encodeURIComponent(el.dataset.candidate));if(sequence!==reportSequence)return;
   placeReport('compare');
   $('#report').innerHTML='<button id="close-report">Close report</button><h2 tabindex="-1">Saved decision '+((current.candidates||[]).indexOf(el.dataset.candidate)+1)+'</h2>'+comparisonSummary(old.comparison||{},false)+table(old.comparison?.rows||[],!!old.comparison?.complete);
   $('#report').scrollIntoView({block:'start',behavior:reduced()?'instant':'smooth'});$('#report h2').focus({preventScroll:true});
  }catch(error){message(error.message);}
 }
});
refresh();
