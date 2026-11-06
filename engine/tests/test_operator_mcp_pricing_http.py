import unittest
from unittest.mock import patch
from engine.tests.test_operator_mcp_http import OperatorHTTPTests
from zylch.operator_mcp.server import create_server

class PricingHTTPTests(unittest.TestCase):
    def test_real_sdk_pricing_tools_refuse_old_grant_and_revalidate_before_result(self):
        fixture = OperatorHTTPTests()
        class Service:
            def __init__(self, port): pass
            async def context(self, grant):
                if revoke[0]: fixture.payload['active'] = False
                return {'internal_price_marker':'private-cost-value'}
            async def document(self, grant, *args): return {'document':'source'}
            async def calculate(self, grant, *args): return {'quote':'calculated'}
        revoke = [False]
        def configured(verifier, *args, **kwargs):
            verifier.allowed_scopes = verifier.allowed_scopes | {'pricing.use'}
            return create_server(verifier, *args, **kwargs)
        async def exercise():
            fixture.payload['scope'] += ' pricing.use'
            fixture.payload['source_classes'].append('pricing')
            client = await fixture.session()
            tools = {t.name for t in (await client.list_tools()).tools}
            self.assertTrue({'pricing_context','pricing_document','pricing_calculate'} <= tools)
            allowed = await client.call_tool('pricing_context', {})
            self.assertFalse(allowed.isError)
            self.assertEqual(allowed.structuredContent['internal_price_marker'],'private-cost-value')
            fixture.payload['scope'] = fixture.payload['scope'].replace(' pricing.use','')
            fixture.payload['source_classes'].remove('pricing')
            refused = await client.call_tool('pricing_context', {})
            self.assertTrue(refused.isError)
            self.assertNotIn('private-cost-value',str(refused))
            identity = await client.call_tool('operator_identity', {})
            self.assertFalse(identity.isError)
            fixture.payload['scope'] += ' pricing.use';fixture.payload['source_classes'].append('pricing')
            revoke[0] = True
            refused = await client.call_tool('pricing_context', {})
            self.assertTrue(refused.isError)
            self.assertNotIn('private-cost-value',str(refused))
        with patch('engine.tests.test_operator_mcp_http.create_server',configured), patch('zylch.operator_mcp.pricing.PricingService',Service):
            fixture.run_case(exercise)
