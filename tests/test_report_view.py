"""Read-only report reader, draft verdicts, and one-failure teaching cases."""
import json
import pytest
from app import core
from app.report_view import report_view


def test_view_pairs_selected_draft_with_its_feedback_not_final_verdict():
    record={'id':'example','requirement_doc':'REQUIREMENT: Notifications\nKeep unread for 30 days.',
            'status':'satisfied','grading':[
                {'result':'needs_revision','analysis_markdown':'No scenario','criteria':[{'name':'depth','passed':False,'gap':'Missing boundary'}]},
                {'result':'needs_revision','analysis_markdown':'Added an unsupported policy','criteria':[{'name':'depth','passed':False,'gap':'Unsupported policy'}]},
                {'result':'satisfied','analysis_markdown':'Boundary example labeled illustrative','criteria':[{'name':'depth','passed':True}]}]}
    selected=report_view(record,2)
    assert selected['selected']['result']=='needs_revision'
    assert selected['final_status']=='satisfied' and selected['revisions']==2
    assert selected['next']['result']=='satisfied' and selected['label']=='Revised draft 1'
    assert '-Added an unsupported policy' in selected['changes']
    assert '+Boundary example labeled illustrative' in selected['changes']
    assert report_view(record,3)['next'] is None
    for invalid in (0,4,None,True):
        with pytest.raises(ValueError):report_view(record,invalid)
