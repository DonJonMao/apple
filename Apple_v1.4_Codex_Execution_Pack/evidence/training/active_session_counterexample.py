from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
from streamlit.testing.v1 import AppTest
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

with TemporaryDirectory(prefix='active-session-review-') as temp:
    os.chdir(temp);path=Path(temp)/'db.sqlite3'
    app=AppTest.from_string('from healthzip.db.repository import Repository\nfrom healthzip.ui.training_page import render_training\n'
        f'repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()').run(timeout=30)
    app.text_input(key='start_name').set_value('Old unfinished session')
    app.button(key='training_start').click().run(timeout=30)
    first=app.selectbox(key='resume_training').value
    app.text_input(key='start_name').set_value('New requested session')
    app.button(key='training_start').click().run(timeout=30)
    selected=app.selectbox(key='resume_training').value
    repo=Repository(path);svc=TrainingService(repo);sessions=svc.list_sessions()
    latest=sessions[0]
    print(json.dumps({'first_id':first,'new_id':latest['id'],'new_name':latest['name'],
        'selected_id':selected,'selected_name':svc.get_session(selected)['name'],
        'active_training_state':app.session_state['active_training'],'errors':[e.value for e in app.exception]},ensure_ascii=False))
    repo.close()
