"""Controlled saved evidence for policy tests, never shipped as learner activity."""
import json
from pathlib import Path
from app.capstone_evidence import DOCUMENTS,CRITERIA,digest,comparison,batch

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

def fixture(root,before=(3,3,3),after=(4,4,4),choice='apply'):
    folder=root/'capstone/candidates/c1';baseline=root/'capstone/baseline';evaluation=folder/'evaluation'
    original='## Procedure\nUse tools.\n### Ambiguities\nIdentify uncertainty.\n'
    selected=original+'\nAsk specific questions.\n' if choice=='apply' else original
    settings={'review_model':'fixed','grader_model':'fixed','budget':3,'cap':40,'rubric_sha256':'fixed',
              'documents':{n:digest('REQUIREMENT: '+n) for n in DOCUMENTS}}
    refs=[]
    for stage,where,counts,instructions in (('before',baseline,before,original),('after',evaluation,after,selected)):
        write(where/'settings.json',settings);(where/'AGENTS.md').write_text(instructions)
        for i,name in enumerate(DOCUMENTS):
            criteria=[{'name':c,'passed':i<counts[k],'gap':'Missing choice' if i>=counts[k] else '', 'evidence':'The saved line.'} for k,c in enumerate(CRITERIA)]
            grade={'result':'satisfied' if all(c['passed'] for c in criteria) else 'needs_revision','criteria':criteria,'analysis_markdown':f'# {stage} {name}\nSaved first draft','explanation':'Actual controlled evaluation'}
            rec={'id':stage+str(i),'doc_name':name,'model':'fixed','execution_mode':'live','instructions':instructions,'requirement_doc':'REQUIREMENT: '+name,'grading':[grade,{'result':'satisfied','criteria':[{**c,'passed':True} for c in criteria],'analysis_markdown':'Later corrected report'}],
                 'messages':[{'type':'ai','tool_calls':[{'id':'fetch','name':'fetch_requirement'},{'id':'write','name':'write_file'}]},{'type':'tool','tool_call_id':'fetch','content':'REQUIREMENT: '+name},{'type':'tool','tool_call_id':'write','content':'Updated file /analysis.md'}],
                 'status':'satisfied','trace':[{'actor':'Tool','action':'fetch_requirement'},{'actor':'Tool','action':'write_file'}]}
            write(where/f'run_{i+1:02}_{Path(name).stem}.json',rec)
            write(where/'checkpoints'/(name+'.json'),{'grading':rec['grading']})
            if stage=='before':refs.append(rec['id']+':clarity')
    write(root/'capstone/index.json',{'candidates':['c1']})
    source=folder/'analyst-attempts/a.py';source.parent.mkdir(parents=True,exist_ok=True);source.write_text('def review(instructions,saved_runs,model):\n return saved_runs\n')
    proposal={'decision':'propose' if choice!='keep' else 'keep','explanation':'Supported finding or reason to keep.','evidence_ids':refs,'section':'### Ambiguities','change':'Ask specific questions.',
              'source_path':str(source.relative_to(root)),'source_sha256':digest(source.read_bytes())}
    write(folder/'proposal.json',proposal);write(source.with_suffix('.result.json'),{'status':'completed','proposal':proposal})
    write(source.with_suffix('.input.json'),{'instructions':original,'saved_runs':batch(baseline)['records']})
    decision={'decision':choice,'instructions':selected,'original_instructions':original,'reason':'The evidence supports this decision.', 'event_id':'event1','proposal_sha256':digest(json.dumps(proposal,sort_keys=True))}
    write(folder/'decision.json',decision);write(folder/'event.json',{'id':'event1','candidate':'c1','instructions_sha256':digest(selected),'status':'completed','evaluation_job':'job1'})
    write(root/'batch-jobs/job1.json',{'id':'job1','label':'capstone-c1','status':'completed','metadata':{'operation':'capstone_evaluation','candidate':'c1','event_id':'event1','instructions_sha256':digest(selected)}})
    result=comparison(root,folder);write(folder/'comparison.json',result)
    write(folder/'outcome.json',{'explanation':'The counts support this outcome, with a small-sample limitation.','comparison_sha256':digest(json.dumps(result,sort_keys=True))})
    return folder
