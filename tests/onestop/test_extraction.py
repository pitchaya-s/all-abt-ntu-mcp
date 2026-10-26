"""Exercise the browser projection against synthetic widget scopes."""

from importlib.util import find_spec
import unittest

from onestop.session import _EXTRACT


@unittest.skipUnless(find_spec("playwright"), "The optional personal extra is not installed")
class ExtractionTests(unittest.TestCase):
    def test_projection_excludes_prefilled_hidden_identity_and_conversation_values(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                self.skipTest("Optional Chromium is not installed")
            try:
                page = browser.new_page()
                page.set_content('<div id="form" widget="widget" data="data"></div>'
                                 '<div id="header" widget="widget" data="data"></div>'
                                 '<div id="ticket" widget="widget" data="data"></div>'
                                 '<div id="fields" widget="widget" data="data"></div>')
                page.evaluate("""() => {
                  const scopes = {
                    form: {widget: {id: 'ntu-widget-sc-cat-item-v2'}, data: {
                      recordFound: true, sc_cat_item: {sys_id: '3'.repeat(32), name: 'Example', can_view: true,
                        description: '<p>Instructions</p>', _fields: {
                          visible: {name: 'email', label: 'Email', type: 'email', visible: true,
                            value: 'private-default-secret', display_value: 'private-default-secret', mandatory: true},
                          hidden: {name: 'hidden', label: 'Hidden', type: 'string', visible: false,
                            value: 'private-hidden-secret'},
                          layout: {name: 'layout', type: 'container_start', visible: true}
                        }, client_script: 'private-script-secret', _attachmentGUID: 'private-guid-secret'}}},
                    header: {widget: {id: 'ntu_student_header_v2'}, data: {profile: 'private-profile-secret'}},
                    ticket: {widget: {id: 'ntu_ticket_conversations'}, data: {number: 'REQ000001',
                      stream: {user_login: 'private-login-secret', entries: [{element: 'work_notes', value: 'private-worknote-secret'}]}}},
                    fields: {widget: {id: 'ntu_ticket_fields'}, data: {fields: [], variables: [
                      {name: 'hidden', label: 'Hidden', display_value: 'private-answer-secret', visible_standalone: false},
                      {name: 'purpose', label: 'Purpose', display_value: 'Visible answer', visible_standalone: true}]}}
                  };
                  window.angular = {element: e => ({scope: () => scopes[e.id], injector: () => ({get: () => ({valueOf: v => v})})})};
                }""")
                result = page.evaluate(_EXTRACT)
                self.assertNotIn("private-", str(result))
                self.assertEqual(len(result["item"]["fields"]), 1)
                self.assertEqual(result["item"]["fields"][0]["name"], "email")
                self.assertEqual(result["ticket_fields"]["variables"][0]["display_value"], "Visible answer")
            finally:
                browser.close()
