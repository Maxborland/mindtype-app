import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_first_run_wizard_does_not_register_byok_page(qapp):
    from app.ui.setup_wizard import SetupWizard

    class ConfigStub:
        def update(self, **values):
            pass

    wizard = SetupWizard(
        config=ConfigStub(),
        translate_func=lambda key: key,
        license_manager=object(),
    )

    assert wizard.pageIds() == [0, 1, 2, 3, 4]
    assert not hasattr(wizard, "api_key_page")

    wizard.close()


def test_first_run_wizard_recommends_cloud_activation(qapp):
    from app.ui.setup_wizard import SetupWizard

    class ConfigStub:
        def update(self, **values):
            pass

    wizard = SetupWizard(
        config=ConfigStub(),
        translate_func=lambda key: key,
        license_manager=object(),
    )

    assert wizard.key_or_demo_page.is_demo_selected() is False

    wizard.close()
