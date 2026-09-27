"""Security (#2): CE-only API/pages, and a webhook that only trusts signed SNS messages.

1. The events/stats API and the two pages were readable by any logged-in user
   (students, HS admins): bounce/complaint recipients and subjects, searchable.
2. sns_endpoint accepted unsigned messages (forged events) and fetched any
   SubscribeURL it was sent (SSRF).
"""
import base64
import datetime
import json
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import Client, TestCase, override_settings

from ses_tracking import sns_verify
from ses_tracking.models import SESEvent

User = get_user_model()

CERT_URL = 'https://sns.us-west-2.amazonaws.com/SimpleNotificationService-abc.pem'
TOPIC = 'arn:aws:sns:us-west-2:123456789012:ses-events'
WEBHOOK = '/ses/webhooks/sns/ses-events/'


def _login(user):
    saved = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    try:
        c = Client()
        c.force_login(user)
    finally:
        user_logged_in.receivers = saved
    return c


def _user(username, role):
    u = User.objects.create(username=username, email=f'{username}@example.com')
    u.groups.add(Group.objects.get_or_create(name=role)[0])
    return u


class ApiAndPagesAreCeOnlyTests(TestCase):
    API = ['/ses/webhooks/api/events/', '/ses/webhooks/api/events.json',
           '/ses/webhooks/api/stats/', '/ses/webhooks/api/stats.json',
           '/ses/webhooks/api/stats/summary/', '/ses/webhooks/api/stats/date_range/',
           '/ses/webhooks/api/stats/aggregate/', '/ses/webhooks/api/stats/latest/']
    PAGES = ['/ses/webhooks/sns/bounces-complaints/', '/ses/webhooks/sns/daily_email_stats/']

    def test_non_ce_roles_are_refused_everywhere(self):
        for role in ('student', 'highschool_admin', 'instructor'):
            c = _login(_user(f'u_{role}', role))
            for url in self.API:
                self.assertEqual(c.get(url).status_code, 403, (role, url))
            for url in self.PAGES:
                resp = c.get(url)
                self.assertNotEqual(resp.status_code, 200, (role, url))
                self.assertEqual(resp.status_code, 302, (role, url))

    def test_ce_can_read_them(self):
        c = _login(_user('u_ce', 'ce'))
        for url in ['/ses/webhooks/api/events/', '/ses/webhooks/api/stats/'] + self.PAGES:
            self.assertEqual(c.get(url).status_code, 200, url)


def _make_signer():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'sns.amazonaws.com')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return key, cert.public_bytes(serialization.Encoding.PEM)


KEY, CERT_PEM = _make_signer()


def _sign(message, version='2', key=KEY):
    message = dict(message, SignatureVersion=version, SigningCertURL=message.get(
        'SigningCertURL', CERT_URL))
    algo = hashes.SHA256() if version == '2' else hashes.SHA1()
    canonical = sns_verify.canonical_string(message).encode()
    message['Signature'] = base64.b64encode(
        key.sign(canonical, padding.PKCS1v15(), algo)).decode()
    return message


def _bounce_notification(**overrides):
    ses = {'eventType': 'Bounce',
           'mail': {'messageId': 'm-1', 'timestamp': '2026-09-27T10:00:00.000Z',
                    'destination': ['x@example.com'], 'commonHeaders': {'subject': 'Hi'}},
           'bounce': {'bounceType': 'Permanent', 'bounceSubType': 'General',
                      'bouncedRecipients': [{'emailAddress': 'x@example.com'}],
                      'timestamp': '2026-09-27T10:00:00.000Z'}}
    msg = {'Type': 'Notification', 'MessageId': 'sns-1', 'TopicArn': TOPIC,
           'Message': json.dumps(ses), 'Timestamp': '2026-09-27T10:00:01.000Z'}
    msg.update(overrides)
    return msg


@patch('ses_tracking.sns_verify._fetch_cert', return_value=CERT_PEM)
class WebhookVerificationTests(TestCase):
    def _post(self, message):
        return Client().post(WEBHOOK, data=json.dumps(message), content_type='application/json')

    def test_signed_notification_is_processed(self, _fetch):
        resp = self._post(_sign(_bounce_notification()))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(SESEvent.objects.filter(event_type='bounce').exists())

    def test_signature_version_1_is_accepted(self, _fetch):
        self.assertEqual(self._post(_sign(_bounce_notification(), version='1')).status_code, 200)

    def test_unsigned_notification_is_rejected_and_stores_nothing(self, _fetch):
        resp = self._post(_bounce_notification())
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(SESEvent.objects.exists())

    def test_tampered_message_is_rejected(self, _fetch):
        msg = _sign(_bounce_notification())
        msg['Message'] = msg['Message'].replace('x@example.com', 'victim@example.com')
        self.assertEqual(self._post(msg).status_code, 403)
        self.assertFalse(SESEvent.objects.exists())

    def test_signed_by_a_different_key_is_rejected(self, _fetch):
        other_key, _ = _make_signer()
        self.assertEqual(self._post(_sign(_bounce_notification(), key=other_key)).status_code, 403)

    def test_cert_url_off_amazon_is_rejected_without_fetching(self, _fetch):
        for url in ('https://evil.example.com/cert.pem',
                    'http://sns.us-west-2.amazonaws.com/cert.pem',
                    'https://sns.us-west-2.amazonaws.com.evil.com/cert.pem'):
            msg = _sign(_bounce_notification(SigningCertURL=url))
            self.assertEqual(self._post(msg).status_code, 403, url)
        _fetch.assert_not_called()

    @override_settings(SES_TRACKING_ALLOWED_TOPIC_ARNS=['arn:aws:sns:us-west-2:123456789012:other'])
    def test_topic_outside_the_allow_list_is_rejected(self, _fetch):
        self.assertEqual(self._post(_sign(_bounce_notification())).status_code, 403)

    @override_settings(SES_TRACKING_ALLOWED_TOPIC_ARNS=[TOPIC])
    def test_topic_in_the_allow_list_is_accepted(self, _fetch):
        self.assertEqual(self._post(_sign(_bounce_notification())).status_code, 200)

    def _subscription(self, url):
        return {'Type': 'SubscriptionConfirmation', 'MessageId': 'sub-1', 'Token': 't',
                'TopicArn': TOPIC, 'Message': 'confirm', 'SubscribeURL': url,
                'Timestamp': '2026-09-27T10:00:01.000Z'}

    def test_subscription_confirms_only_signed_amazon_urls(self, _fetch):
        good = 'https://sns.us-west-2.amazonaws.com/?Action=ConfirmSubscription&Token=t'
        with patch('ses_tracking.views._confirm_subscription') as confirm:
            # unsigned: never followed
            self.assertEqual(self._post(self._subscription(good)).status_code, 403)
            # signed, but pointing somewhere else (SSRF): never followed
            evil = 'http://169.254.169.254/latest/meta-data/'
            self.assertEqual(self._post(_sign(self._subscription(evil))).status_code, 403)
            confirm.assert_not_called()
            # signed and on sns.*.amazonaws.com: confirmed
            self.assertEqual(self._post(_sign(self._subscription(good))).status_code, 200)
            confirm.assert_called_once_with(good)

    def test_garbage_body_is_a_400_not_a_500(self, _fetch):
        resp = Client().post(WEBHOOK, data='not json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)
