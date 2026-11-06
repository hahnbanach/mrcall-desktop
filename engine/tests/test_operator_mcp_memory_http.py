"""Maintained SDK memory routing/permission/revocation checks; no model calls."""
import unittest
from unittest.mock import patch
import httpx
from engine.tests.test_operator_mcp_http import OperatorHTTPTests
from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
from zylch.operator_mcp.server import create_server
from cs.operator_read import ReadError

class MemoryHTTPTests(unittest.TestCase):
    def test_same_existing_session_full_access_stable_routing_and_return_revocation(self):
        fixture=OperatorHTTPTests();calls=[];revoke=[False]
        class Memory:
            def __init__(self,port):pass
            async def search(self,grant,*args):
                if 'operator.use' not in grant.scopes:raise ReadError('memory_permission_denied')
                calls.append(args)
                if revoke[0]:fixture.payload['active']=False
                return {'source':'company_memory','items':[{'blob_id':'memory-one','excerpt':'stored-memory-marker'}]}
            async def read(self,grant,*args):return await self.search(grant,*args)
        async def exercise():
            o=fixture.verifier
            verifier=GrantVerifier(issuer=o.issuer,introspection_url=o.endpoint,service_client_id=o.service_client_id,service_client_secret=o.service_client_secret,resource=o.resource,profile_uid='owner',company_ref='company',allowed_client_ids={'native-client'},http_client=o.http_client,operator_enabled=True)
            port=NativeReadPort(lambda:ProfileBinding('owner','owner@example.test','company',frozenset({'ordinary-mailbox'})))
            server=create_server(verifier,port,allowed_hosts=['engine.example.test']);app=server.streamable_http_app()
            await fixture.stack.enter_async_context(server.session_manager.run())
            fixture.http=await fixture.stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://engine.example.test',headers={'Authorization':'Bearer test-opaque-access-token'}))
            client=await fixture.session()
            denied=await client.call_tool('operator_read',{'name':'search_memory','arguments':{'query':'Kohana'}});self.assertTrue(denied.isError);self.assertEqual(calls,[])
            # Same session, same access token; authority is current at introspection.
            fixture.payload['scope']='operator.read operator.use';fixture.payload['source_classes']=[];fixture.payload['mailbox_ids']=[]
            names=[];offset=0
            while True:
                page=await client.call_tool('operator_capabilities',{'offset':offset,'limit':10});self.assertFalse(page.isError,str(page));data=page.structuredContent;names += [r['name'] for r in data['items']]
                if data['next_offset'] is None:break
                offset=data['next_offset']
            self.assertTrue({'search_memory','read_memory'}<=set(names))
            default=await client.call_tool('operator_read',{'name':'search_memory','arguments':{'query':'Kohana'}});self.assertFalse(default.isError,str(default));self.assertEqual(calls[-1],('Kohana',5,'auto'))
            value=await client.call_tool('operator_read',{'name':'search_memory','arguments':{'query':'Kohana','mode':'text'}});self.assertFalse(value.isError,str(value));self.assertIn('stored-memory-marker',str(value))
            for args in ({'query':'x','limit':True},{'query':'x','limit':21},{'query':'x','extra':'bad'}):self.assertTrue((await client.call_tool('search_memory',args)).isError)
            before=len(calls);revoke[0]=True
            value=await client.call_tool('search_memory',{'query':'Kohana'});self.assertTrue(value.isError);self.assertNotIn('stored-memory-marker',str(value));self.assertEqual(len(calls),before+1)
        with patch('zylch.operator_mcp.memory.MemoryService',Memory):fixture.run_case(exercise)
