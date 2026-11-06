import asyncio
import os
import unittest
from unittest.mock import patch

from zylch.rpc import operator_operations
from zylch.rpc.native_owner_context import authenticated_owner_request, require_owner


class NativeAdmissionTests(unittest.TestCase):
    def test_cached_login_or_client_human_flag_cannot_confirm(self):
        for name, method in operator_operations.METHODS.items():
            with self.subTest(name=name), patch('zylch.services.task_assignment_identity.actor') as actor:
                with self.assertRaises(PermissionError):
                    asyncio.run(method({'human': True, 'approved': True}, lambda *args: None))
                actor.assert_not_called()

    def test_transport_context_is_owner_bound_and_cleared(self):
        with patch.dict(os.environ, {'OWNER_ID': 'owner'}):
            with self.assertRaises(PermissionError):
                with authenticated_owner_request('other'):
                    pass
            with authenticated_owner_request('owner'):
                with patch('zylch.services.task_assignment_identity.actor') as actor:
                    actor.return_value.uid = 'owner'
                    self.assertIs(require_owner(), actor.return_value)
            with self.assertRaises(PermissionError):
                require_owner()
