"""Sent Email API and page: a CIS role AND ses_tracking.view_sent_email
(sent-email spec §3, §4)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.signals import user_logged_in
from django.test import Client, TestCase, override_settings

from ses_tracking.models import SentEmail

API = '/ses/webhooks/api/sent-email/'
PAGE = '/ses/webhooks/sent-email/'


def _client(user):
    saved = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    try:
        c = Client()
        c.force_login(user)
    finally:
        user_logged_in.receivers = saved
    return c


def _user(name, ce=True, perm=False, superuser=False):
    User = get_user_model()
    make = User.objects.create_superuser if superuser else User.objects.create_user
    user = make(username=name, email=f'{name}@x.com', password='x')
    if ce:
        user.groups.add(Group.objects.get_or_create(name='ce')[0])
    if perm:
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label='ses_tracking', codename='view_sent_email'))
    return user


def _rows(resp):
    data = resp.json()
    return data['results'] if isinstance(data, dict) and 'results' in data else (
        data['data'] if isinstance(data, dict) and 'data' in data else data)


class SentEmailApiAccessTests(TestCase):

    def setUp(self):
        self.row = SentEmail.objects.create(path='queue', subject='Hi', delivered_to=['a@x.com'],
                                            search_addresses='a@x.com', html_body='<p>secret</p>')

    def test_non_ce_user_is_refused(self):
        self.assertEqual(_client(_user('stu', ce=False)).get(API).status_code, 403)

    def test_ce_without_permission_is_refused_list_and_detail(self):
        c = _client(_user('ce1'))
        self.assertEqual(c.get(API).status_code, 403)
        self.assertEqual(c.get(f'{API}{self.row.pk}/').status_code, 403)

    def test_ce_with_permission_can_list_without_bodies(self):
        resp = _client(_user('ce2', perm=True)).get(API, {'format': 'datatables', 'draw': 1})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('secret', resp.content.decode())
        self.assertIn('Hi', resp.content.decode())

    def test_detail_has_body_and_timeline(self):
        resp = _client(_user('ce3', perm=True)).get(f'{API}{self.row.pk}/', {'format': 'json'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['html_body'], '<p>secret</p>')
        self.assertIn('events', resp.json())

    def test_superuser_passes(self):
        self.assertEqual(_client(_user('su', superuser=True)).get(API).status_code, 200)

    def test_search_and_ordering_do_not_500(self):
        c = _client(_user('ce4', perm=True))
        resp = c.get(API, {'format': 'datatables', 'draw': 1, 'search[value]': 'a@x',
                           'order[0][column]': 0, 'order[0][dir]': 'desc',
                           'columns[0][data]': 'sent_at', 'columns[0][name]': 'sent_at',
                           'columns[0][searchable]': 'true', 'columns[0][orderable]': 'true',
                           'columns[1][data]': 'subject', 'columns[1][name]': 'subject',
                           'columns[1][searchable]': 'true', 'columns[1][orderable]': 'true'})
        self.assertEqual(resp.status_code, 200)

    def test_address_filter(self):
        SentEmail.objects.create(path='queue', subject='Other', search_addresses='b@x.com')
        resp = _client(_user('ce5', perm=True)).get(API, {'format': 'json', 'address': 'a@x.com'})
        self.assertEqual([r['subject'] for r in _rows(resp)], ['Hi'])


class SentEmailPageTests(TestCase):

    def test_page_needs_the_permission(self):
        resp = _client(_user('p1')).get(PAGE)
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Can view sent email', resp.content.decode())

    def test_page_renders_for_permitted_user(self):
        resp = _client(_user('p2', perm=True)).get(PAGE)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Opened (approximate)', resp.content.decode())

    def test_stored_html_is_never_inlined_in_the_page(self):
        SentEmail.objects.create(path='queue', subject='x', html_body='<script>alert(1)</script>')
        resp = _client(_user('p3', perm=True)).get(PAGE)
        self.assertNotIn('<script>alert(1)</script>', resp.content.decode())

    def test_modal_uses_a_sandboxed_iframe_without_scripts(self):
        html = _client(_user('p4', perm=True)).get(PAGE).content.decode()
        self.assertIn('sandbox=""', html)
        self.assertNotIn('allow-scripts', html)

    def test_debug_banner_shows_only_when_switched_on(self):
        c = _client(_user('p5', perm=True))
        self.assertNotIn('Debug routing is ON', c.get(PAGE).content.decode())
        with override_settings(SES_TRACKING_DEBUG_ROUTING=True):
            self.assertIn('Debug routing is ON', c.get(PAGE).content.decode())

    def test_health_note_when_trackable_mail_but_no_opens(self):
        SentEmail.objects.create(path='queue', subject='x', trackable=True)
        html = _client(_user('p6', perm=True)).get(PAGE).content.decode()
        self.assertIn('No open events received in 7 days', html)


class MenuSeedTests(TestCase):

    def test_menu_item_seeded_under_email_stats_once(self):
        import json
        from cis.models.settings import Setting
        from ses_tracking.migrations._menu import add_sent_email
        value = {'ce_menu': json.dumps([{'type': 'nav-item', 'name': 'ses_daily_stats',
                                         'label': 'Email Stats', 'sub_menu': []}])}
        Setting.objects.update_or_create(key='cis.settings.menu', defaults={'value': value})
        add_sent_email(Setting)
        add_sent_email(Setting)
        menu = json.loads(Setting.objects.get(key='cis.settings.menu').value['ce_menu'])
        self.assertEqual([s['name'] for s in menu[0]['sub_menu']], ['ses_sent_email'])


class TableTemplateEscapingTests(TestCase):
    """Values from the API go into HTML attributes (title, data-id), so the
    escaper must encode quotes, and nothing is wired through inline onclick."""

    def _js(self):
        from django.template.loader import render_to_string
        return render_to_string('ses_tracking/sent_email/_table.html',
                                {'table_id': 't', 'api_url': '/x/'})

    def test_escaper_encodes_quotes(self):
        js = self._js()
        self.assertIn("&quot;", js)
        self.assertIn("&#39;", js)

    def test_no_inline_onclick_built_from_data(self):
        self.assertNotIn('onclick=', self._js())
