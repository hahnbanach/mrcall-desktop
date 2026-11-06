import json
import unittest
from contextlib import AsyncExitStack
from dataclasses import replace
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from engine.tests import test_operator_mcp_issuer as fixtures
from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.permissions import SCOPES
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
from zylch.operator_mcp.server import create_server


class StableRoutingTests(unittest.TestCase):
    def test_one_actual_sdk_session_same_credentials_owner_upgrade_and_feature_addition(self):
        fixture=fixtures.IssuerTests();writes=[];revoke=[False]
        class Projects:
            def __init__(self,port):pass
            async def list(self,grant,*args):return {'items':[{'project':'unchanged-connection-marker'}]}
            async def files(self,grant,*args):return {'items':[]}
            async def read(self,grant,*args):return {'text':'document'}
            async def history(self,grant,*args):return {'items':[]}
            async def create(self,grant,*args):return {'project':'created'}
            async def write(self,grant,*args):
                writes.append(args)
                if revoke[0]:fixture.issuer.revoke(grant.grant_id)
                return {'revision':2,'marker':'mutating-result-canary'}
        class Pricing:
            def __init__(self,port):pass
            async def context(self,grant):return {'marker':'new-feature-without-reconnect'}
            async def document(self,grant,*args):return {}
            async def calculate(self,grant,*args):return {}
        async def exercise():
            client=await fixture.register()
            pair=(await fixture.exchange(client,await fixture.code(client))).json()
            original_access=fixture.store.get('access',pair['access_token'])
            original_refresh=fixture.store.get('refresh',pair['refresh_token'])
            gid=(await fixture.introspect(pair['access_token'])).json()['grant_id']
            fixture.policy=replace(fixture.policy,operator_enabled=True,allowed_scopes=SCOPES-{'pricing.use'})
            verifier=GrantVerifier(issuer=fixture.issuer.issuer,introspection_url=fixture.issuer.issuer+'/introspect',
                service_client_id=fixture.policy.service_client_id,service_client_secret=fixture.policy.service_secret,
                resource=fixture.policy.resource,profile_uid='owner',company_ref='company',allowed_client_ids={client['client_id']},
                http_client=fixture.http,operator_enabled=True)
            port=NativeReadPort(lambda:ProfileBinding('owner',fixture.policy.email,'company',frozenset({'mailbox'}),True))
            server=create_server(verifier,port,allowed_hosts=['engine.example.test'])
            app=server.streamable_http_app()
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(server.session_manager.run())
                http=await stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                    base_url='https://engine.example.test',headers={'Authorization':'Bearer '+pair['access_token']}))
                read,write,_=await stack.enter_async_context(streamable_http_client('https://engine.example.test/mcp',http_client=http))
                session=await stack.enter_async_context(ClientSession(read,write));await session.initialize()
                schemas={t.name:t.inputSchema for t in (await session.list_tools()).tools if t.name.startswith('operator_')}
                denied=await session.call_tool('operator_read',{'name':'list_projects','arguments':{}})
                self.assertTrue(denied.isError)
                listed=await fixture.http.get('/desktop/grants',headers={'Authorization':'Bearer test-desktop-owner-token'})
                grant=next(row for row in listed.json()['grants'] if row['grant_id']==gid)
                body={'grant_id':gid,'payload_sha256':grant['payload_sha256']}
                for token in ('test-other-owner-token','not-an-owner-token'):
                    bad=await fixture.http.post('/desktop/grants/upgrade',headers={'Authorization':'Bearer '+token},json=body)
                    self.assertEqual(bad.status_code,403)
                changed=await fixture.http.post('/desktop/grants/upgrade',headers={'Authorization':'Bearer test-desktop-owner-token'},json=body)
                self.assertEqual(changed.status_code,200,changed.text)
                self.assertEqual(changed.json()['scopes'],['operator.read','operator.use'])
                legacy = await fixture.http.get('/desktop/grants', headers={'Authorization':'Bearer test-desktop-owner-token'})
                legacy_row = next(row for row in legacy.json()['grants'] if row['grant_id'] == gid)
                self.assertEqual(legacy_row['scopes'], grant['scopes'])
                self.assertTrue(legacy_row['operator_access'])
                modern = await fixture.http.get('/desktop/grants', headers={'Authorization':'Bearer test-desktop-owner-token', 'X-MrCall-Operator-Access':'stable-v1'})
                modern_row = next(row for row in modern.json()['grants'] if row['grant_id'] == gid)
                self.assertEqual(modern_row['scopes'], ['operator.read', 'operator.use'])
                allowed=await session.call_tool('operator_read',{'name':'list_projects','arguments':{}})
                self.assertFalse(allowed.isError,allowed)
                self.assertIn('unchanged-connection-marker',str(allowed))
                before_feature=await session.call_tool('operator_read',{'name':'pricing_context','arguments':{}})
                self.assertTrue(before_feature.isError)
                fixture.policy=replace(fixture.policy,allowed_scopes=SCOPES)
                after_feature=await session.call_tool('operator_read',{'name':'pricing_context','arguments':{}})
                self.assertFalse(after_feature.isError,after_feature)
                self.assertIn('new-feature-without-reconnect',str(after_feature))
                self.assertEqual(schemas,{t.name:t.inputSchema for t in (await session.list_tools()).tools if t.name.startswith('operator_')})
                catalog=[];offset=0
                while True:
                    page=await session.call_tool('operator_capabilities',{'limit':10,'offset':offset})
                    self.assertFalse(page.isError,page);data=page.structuredContent;catalog+=data['items']
                    if data['next_offset'] is None:break
                    offset=data['next_offset']
                self.assertIn('pricing_context',{row['name'] for row in catalog})
                args={'space_id':'company','project':'notes','path':'a.md','content':'hello','expected_revision':1}
                for route,name,params in [('operator_read','write_project',args),('operator_action','operator_read',{}),('operator_action','native.shell',{}),('operator_action','write_project',{**args,'arbitrary':'bad'})]:
                    refused=await session.call_tool(route,{'name':name,'arguments':params});self.assertTrue(refused.isError,(route,name,refused))
                self.assertEqual(writes,[])
                self.assertEqual(fixture.store.get('access',pair['access_token']),original_access)
                self.assertEqual(fixture.store.get('refresh',pair['refresh_token']),original_refresh)
                self.assertEqual([fixture.store.count(n) for n in ('clients','grants','pending','access','refresh')],[1,1,1,1,1])
                revoke[0]=True
                uncertain=await session.call_tool('operator_action',{'name':'write_project','arguments':args})
                self.assertTrue(uncertain.isError)
                self.assertNotIn('mutating-result-canary',str(uncertain))
                self.assertEqual(len(writes),1)
        with patch('zylch.operator_mcp.projects.ProjectService',Projects),patch('zylch.operator_mcp.pricing.PricingService',Pricing):
            fixture.run_case(exercise)
