from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from ses_tracking import routing


def _user(email, *, secondary='', alt='', groups=(), username=None):
    User = get_user_model()
    user = User.objects.create(
        username=username or email,
        email=email,
        secondary_email=secondary,
        alt_email=alt,
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _config(roles, mode='active'):
    return {'mode': mode, 'roles': roles}


class RoutingMapTests(TestCase):

    def test_selected_secondary_replaces_the_primary(self):
        _user('teach@college.edu', secondary='teach@home.com',
              groups=['instructor'])
        mapping = routing.build_routing_map(
            ['teach@college.edu'], _config({'instructor': ['secondary']}))
        self.assertEqual(mapping, {'teach@college.edu': ['teach@home.com']})

    def test_multiple_kinds_produce_multiple_targets(self):
        _user('s@college.edu', secondary='s@home.com', alt='s@alt.com',
              groups=['student'])
        mapping = routing.build_routing_map(
            ['s@college.edu'],
            _config({'student': ['primary', 'secondary', 'alt']}))
        self.assertEqual(
            mapping,
            {'s@college.edu': ['s@college.edu', 's@home.com', 's@alt.com']},
        )

    def test_kinds_are_unioned_across_a_users_groups(self):
        _user('both@college.edu', secondary='both@home.com',
              alt='both@alt.com', groups=['instructor', 'highschool_admin'])
        mapping = routing.build_routing_map(
            ['both@college.edu'],
            _config({'instructor': ['secondary'],
                     'highschool_admin': ['alt']}),
        )
        self.assertEqual(
            sorted(mapping['both@college.edu']),
            ['both@alt.com', 'both@home.com'],
        )

    def test_lookup_by_secondary_address_also_routes(self):
        _user('teach@college.edu', secondary='teach@home.com',
              groups=['instructor'])
        mapping = routing.build_routing_map(
            ['teach@home.com'], _config({'instructor': ['secondary']}))
        self.assertEqual(mapping, {'teach@home.com': ['teach@home.com']})

    def test_lookup_is_case_insensitive(self):
        _user('teach@college.edu', secondary='teach@home.com',
              groups=['instructor'])
        mapping = routing.build_routing_map(
            ['TEACH@College.EDU'], _config({'instructor': ['secondary']}))
        self.assertEqual(mapping, {'teach@college.edu': ['teach@home.com']})

    def test_blank_selected_field_falls_back_to_the_original(self):
        _user('teach@college.edu', secondary='', groups=['instructor'])
        mapping = routing.build_routing_map(
            ['teach@college.edu'], _config({'instructor': ['secondary']}))
        self.assertEqual(mapping, {})

    def test_invalid_selected_field_is_skipped(self):
        _user('teach@college.edu', secondary='not-an-email',
              alt='teach@alt.com', groups=['instructor'])
        mapping = routing.build_routing_map(
            ['teach@college.edu'],
            _config({'instructor': ['secondary', 'alt']}))
        self.assertEqual(mapping, {'teach@college.edu': ['teach@alt.com']})

    def test_user_in_no_configured_group_is_untouched(self):
        _user('staff@college.edu', secondary='staff@home.com',
              groups=['ce'])
        mapping = routing.build_routing_map(
            ['staff@college.edu'], _config({'instructor': ['secondary']}))
        self.assertEqual(mapping, {})

    def test_address_matching_no_user_is_untouched(self):
        mapping = routing.build_routing_map(
            ['stranger@example.com'], _config({'instructor': ['secondary']}))
        self.assertEqual(mapping, {})

    def test_shared_secondary_takes_the_first_match(self):
        # Both users share the same secondary_email, but each has a
        # different alt_email, so which one is "first" is distinguishable
        # in the result: if the code picked the second user (or an
        # arbitrary one) the assertion below would fail.
        first = _user('a@college.edu', secondary='shared@home.com',
                       alt='a@alt.com', groups=['instructor'], username='a')
        _user('b@college.edu', secondary='shared@home.com',
              alt='b@alt.com', groups=['instructor'], username='b')
        mapping = routing.build_routing_map(
            ['shared@home.com'],
            _config({'instructor': ['secondary', 'alt']}))
        self.assertEqual(
            mapping,
            {'shared@home.com': ['shared@home.com', first.alt_email]},
        )

    def test_empty_role_map_routes_nothing(self):
        _user('teach@college.edu', secondary='teach@home.com',
              groups=['instructor'])
        self.assertEqual(
            routing.build_routing_map(['teach@college.edu'], _config({})), {})

    def test_one_query_regardless_of_address_count(self):
        _user('a@college.edu', secondary='a@home.com',
              groups=['instructor'], username='a')
        _user('b@college.edu', secondary='b@home.com',
              groups=['instructor'], username='b')
        config = _config({'instructor': ['secondary']})
        with self.assertNumQueries(2):  # users + prefetched groups
            routing.build_routing_map(
                ['a@college.edu', 'b@college.edu'], config)

        # Add a third user/address and confirm the count does not grow --
        # the property under test is "constant in N", not "equals 2".
        _user('c@college.edu', secondary='c@home.com',
              groups=['instructor'], username='c')
        with self.assertNumQueries(2):
            routing.build_routing_map(
                ['a@college.edu', 'b@college.edu', 'c@college.edu'], config)


class RecipientListTests(TestCase):

    def test_rewrites_and_preserves_display_names(self):
        routed = routing.route_recipient_list(
            ['Jane Doe <teach@college.edu>'],
            {'teach@college.edu': ['teach@home.com']},
        )
        self.assertEqual(routed, ['Jane Doe <teach@home.com>'])

    def test_expands_one_address_into_several(self):
        routed = routing.route_recipient_list(
            ['s@college.edu'],
            {'s@college.edu': ['s@home.com', 's@alt.com']},
        )
        self.assertEqual(routed, ['s@home.com', 's@alt.com'])

    def test_drops_blank_entries(self):
        self.assertEqual(routing.route_recipient_list(['', 'a@b.com'], {}),
                         ['a@b.com'])

    def test_dedupes_case_insensitively(self):
        routed = routing.route_recipient_list(
            ['teach@college.edu', 'TEACH@HOME.com'],
            {'teach@college.edu': ['teach@home.com']},
        )
        self.assertEqual(routed, ['teach@home.com'])

    def test_unmatched_addresses_pass_through_unchanged(self):
        self.assertEqual(
            routing.route_recipient_list(['stranger@example.com'], {}),
            ['stranger@example.com'],
        )

    def test_unmatched_addresses_pass_through_unvalidated(self):
        # Deliberately malformed and NOT in the routing map: this branch
        # must never validate or drop addresses we were not asked to
        # touch -- validation applies only to substituted-in targets.
        self.assertEqual(
            routing.route_recipient_list(['not-an-email'], {}),
            ['not-an-email'],
        )


class ActiveFlagTests(TestCase):

    def test_missing_mode_is_inactive(self):
        self.assertFalse(routing.routing_is_active({}))
        self.assertFalse(routing.routing_is_active(None))

    def test_explicit_active(self):
        self.assertTrue(routing.routing_is_active({'mode': 'active'}))

    def test_explicit_inactive(self):
        self.assertFalse(routing.routing_is_active({'mode': 'inactive'}))

    def test_load_config_returns_empty_dict_when_setting_is_missing(self):
        self.assertEqual(routing.load_config(), {})
