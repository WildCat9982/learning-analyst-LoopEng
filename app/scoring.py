"""Deterministic course points. Never execute learner code or ask a model for outcomes."""
import json
import math
import sys
from pathlib import Path


def finite(value,maximum):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=maximum:
        raise ValueError('Invalid component points; retry grading.')
    return value


def apply(grade,rubric,workspace):
    if rubric.get('scoring',{}).get('policy')!='loopeng-capstone-v1':return grade
    from .capstone_evidence import inspect
    saved=inspect(workspace)
    empty=saved.get('activity') is False
    raw=grade.get('dimensions',[])
    if empty:
        raw=[{'name':d['name'],'score':0,**({'components':dict.fromkeys(d['components'],0)} if d.get('components') else {})} for d in rubric['dimensions']]
        grade={**grade,'working':[],'pushFurther':['No saved capstone activity was found. Build and run your analyst, then save your decision and comparison.']}
    if len(raw)!=3:raise ValueError('Three grading parts are required.')
    gates=saved['gates'];missing=[k for k,v in gates.items() if not v]
    comparison=saved.get('comparison',{})
    parts=[]
    for i,(spec,dimension) in enumerate(zip(rubric['dimensions'],raw)):
        maximum=spec['maxPoints']
        if i==2:
            earned=comparison.get('outcome_points',0)
        else:
            values=dimension.get('components',{})
            if set(values)!=set(spec['components']):raise ValueError('Return the named component points for each assessed part.')
            earned=sum(finite(values[k],m) for k,m in spec['components'].items())
            # Missing execution/events cannot earn their presence points from a claim alone.
            if i==0 and not gates['analyst']:
                earned-=values['execution'] if not saved.get('proposal') else 0
            if i==1 and not gates['decision_event']:earned-=values['event']
        parts.append({**dimension,'partId':spec['partId'],'maxPoints':maximum,'earnedPoints':round(earned,6)})
    earned=sum(p['earnedPoints'] for p in parts)
    scale=69/earned if missing and earned>69 else 1
    for part in parts:
        part.update(reportedPoints=part['earnedPoints']*scale,fractionalScore=part['earnedPoints']*scale/part['maxPoints'],score=part['earnedPoints']*10/part['maxPoints'])
    total=sum(p['reportedPoints'] for p in parts)
    return {**grade,'dimensions':parts,'overall':round(total,6),'earnedTotal':round(earned,6),
            'reportedTotal':round(total,6),'passingThreshold':70,'missingMinimum':missing,
            'capApplied':scale<1,'emptySubmission':empty,'scoringPolicy':'loopeng-capstone-v1','outcome':comparison,
            'verdict':'Passing' if not missing and total>=70 else 'Not yet passing'}


if __name__=='__main__':
    payload=json.load(sys.stdin)
    if payload.get('action')=='capstone_context':
        from .capstone_evidence import grading_context
        try:result=grading_context(Path(payload['workspace']))
        except (OSError,ValueError,KeyError,TypeError,AttributeError):result={'available':False,'message':'Inspect partial saved evidence; no valid complete comparison.'}
    else:result=apply(payload['grade'],payload['rubric'],Path(payload['workspace']))
    print(json.dumps(result))
