"""Presence and result checks are separate from the final course grade."""
from .capstone_evidence import inspect as evidence

def inspect(root):
    saved=evidence(root)
    names={'analyst':'Executed analyst and supporting evidence','decision_event':'Saved decision and automatic evaluation',
           'comparison':'Complete first-attempt comparison','explanations':'Saved short explanations','result':'Result target'}
    return {'state':'invalid' if saved['errors'] else 'complete' if saved['ready'] else 'partial' if saved['activity'] else 'empty',
            'entries':[{'id':key,'loop':name,'status':'saved' if saved['gates'][key] else 'missing',
                        'message':'Saved' if saved['gates'][key] else 'Still missing','href':'#'+('compare' if key in ('comparison','explanations','result') else 'decide' if key=='decision_event' else 'run')}
                       for key,name in names.items()],
            'message':'Partial work can be submitted. The course Grader assesses implementation and explanations.', 'errors':saved['errors']}
