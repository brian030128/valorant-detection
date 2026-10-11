import json
from tools.dataset_progress import snapshot, display


def test_job_failure_overrides_unrelated_old_log(tmp_path):
    (tmp_path/'generation_status.json').write_text(json.dumps({'phase':'failed','current_map':'ascent','error':'renderer crashed'}))
    old=tmp_path/'old.log';old.write_text('VALIDATED 10000/10000')
    state=snapshot(tmp_path,30000,old)
    assert state['failure'] and state['checked']==0
    output=display(state,tmp_path,30000,old,0)
    assert 'JOB FAILED' in output and 'renderer crashed' in output
    assert 'job keeps running' not in output


def test_active_retry_does_not_report_terminal_failure(tmp_path):
    log=tmp_path/'retry.log';log.write_text('AssertionError from previous attempt')
    (tmp_path/'generation_status.json').write_text(json.dumps({'phase':'rendering','current_log':str(log)}))
    assert not snapshot(tmp_path,30000,tmp_path/'old.log')['failure']
