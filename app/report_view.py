"""Read-only, draft-specific evidence for Learning's compact report panel."""
import difflib


def report_view(record, draft=1):
    grades = record.get('grading', [])
    if type(draft) is not int or not 1 <= draft <= len(grades):
        raise ValueError('Choose an existing saved report draft.')
    selected = grades[draft-1]
    following = grades[draft] if draft < len(grades) else None
    def label(number):
        return 'First draft' if number == 1 else 'Revised draft ' + str(number-1)
    difference = list(difflib.unified_diff(selected.get('analysis_markdown', '').splitlines(),
                         following.get('analysis_markdown', '').splitlines(), n=1, lineterm='')) if following else []
    return {'run_id': record['id'], 'requirement': record.get('requirement_doc', ''),
            'draft': draft, 'label': label(draft), 'selected': selected,
            'next': following, 'next_label': label(draft+1) if following else None,
            'changes': '\n'.join(difference[:28]), 'changes_truncated': len(difference) > 28,
            'final_status': record['status'], 'revisions': max(0, len(grades)-1),
            'drafts': [{'number': i, 'label': label(i), 'status': g.get('result', 'not_verified')}
                       for i, g in enumerate(grades, 1)], 'trace': record.get('trace', [])}
