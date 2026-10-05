import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["ERP_DATA_DIR"] = tempfile.mkdtemp()


@pytest.fixture(scope="session")
def app():
    import manage  # builds the app and gives us the demo() loader
    with manage.app.app_context():
        manage.demo()
    return manage.app


@pytest.fixture()
def ctx(app):
    with app.app_context():
        yield
