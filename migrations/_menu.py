"""Add "Sent Email" under the CE "Email Stats" menu.

The CE sidebar is the cis.settings.menu Setting (a JSON string per role
under '<role>_menu'), so a new page reaches the menu only through data.
Idempotent; skips a tenant whose menu has no Email Stats item.
"""
import json

ITEM = {'label': 'Sent Email', 'name': 'ses_sent_email', 'url': 'ses_tracking:sent-email'}


def add_sent_email(Setting):
    for setting in Setting.objects.filter(key__endswith='cis.settings.menu'):
        value = setting.value or {}
        try:
            menu = json.loads(value.get('ce_menu') or '[]')
        except (AttributeError, TypeError, ValueError):
            continue
        parent = next((item for item in menu if item.get('name') == 'ses_daily_stats'), None)
        if parent is None:
            continue
        subs = parent.setdefault('sub_menu', [])
        if any(sub.get('name') == ITEM['name'] for sub in subs):
            continue
        subs.insert(0, dict(ITEM))
        value['ce_menu'] = json.dumps(menu)
        setting.value = value
        setting.save(update_fields=['value'])
