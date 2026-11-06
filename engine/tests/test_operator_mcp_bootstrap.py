"""Authenticated SDK bootstrap and native hook adapter checks; no provider/model."""
import base64
from dataclasses import replace
import hashlib
import json
import unittest
from types import SimpleNamespace

import httpx
from cs.codex_bootstrap import recipe, merge
from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.bootstrap import BootstrapService
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
from zylch.operator_mcp.server import create_server
from engine.tests.test_operator_mcp_http import OperatorHTTPTests


class BootstrapTests(unittest.TestCase):
    def test_command_free_preserving_merge(self):
        old={'description':'Existing owner config','hooks':{'Stop':[{'hooks':[{'type':'command','command':'existing'}]}], 'SessionStart':[{'hooks':[{'type':'command','command':'existing-start'}]}]},'other':{'keep':True}}
        result=merge(old,'existing-operator','owner')
        self.assertEqual(result['hooks']['Stop'],old['hooks']['Stop'])
        self.assertEqual(result['hooks']['SessionStart'][0],old['hooks']['SessionStart'][0])
        self.assertEqual(result['other'],old['other'])
        self.assertEqual(merge(result,'existing-operator','owner'),result)
        self.assertEqual(len(old['hooks']['SessionStart']),1)
        for event,groups in recipe('existing-operator','owner')['hook_fragment']['hooks'].items():
            handler=groups[0]['hooks'][0]
            self.assertEqual(handler['type'],'mcp_tool');self.assertNotIn('command',handler)
            self.assertEqual(handler['input']['hook_event'],event)
            self.assertEqual(handler['input']['session_id'],'${session_id}')
        with self.assertRaises(ValueError):merge(result,'existing-operator','other')
        for value in ([],None,{'hooks':[]},{'hooks':{'SessionStart':None}}):
            with self.assertRaises(ValueError):merge(value,'existing-operator','owner')
        for value in ('', ' wrong', 'server\nname'):
            with self.assertRaises(ValueError):recipe(value,'owner')

    def test_sdk_current_rules_hook_dedup_pages_setup_and_revocation(self):
        fixture=OperatorHTTPTests()
        async def exercise():
            fixture.payload.update(scope='operator.read email.read draft.read instructions.read',source_classes=['mail','drafts','instructions'],instruction_paths=['mail/owner@example.test.md','procedures.md'])
            original=fixture.verifier
            verifier=GrantVerifier(issuer=original.issuer,introspection_url=original.endpoint,service_client_id=original.service_client_id,service_client_secret=original.service_client_secret,resource=original.resource,profile_uid='owner',company_ref='company',allowed_client_ids={'native-client'},http_client=original.http_client,instructions_enabled=True)
            binding=ProfileBinding('owner','owner@example.test','company',frozenset({'ordinary-mailbox'}),True)
            revision=[1];body=['Current company procedures.']
            reads=[]
            def published(email):
                reads.append(email)
                return [{'space_id':'company','project':'operator-instructions','path':path,'revision':revision[0],'size':len(text.encode()),'sha256':hashlib.sha256(text.encode()).hexdigest(),'content_base64':base64.b64encode(text.encode()).decode()} for path,text in [('procedures.md',body[0]),('mail/owner@example.test.md','Sign as the configured team.')]]
            async def forbidden(*args):raise AssertionError('bootstrap must not read mail/tasks/provider')
            port=NativeReadPort(lambda:binding,{'emails.search':forbidden,'emails.list_by_thread':forbidden,'drafts.list':forbidden},instruction_reader=published)
            server=create_server(verifier,port,allowed_hosts=['engine.example.test']);app=server.streamable_http_app()
            await fixture.stack.enter_async_context(server.session_manager.run())
            fixture.http=await fixture.stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://engine.example.test',headers={'Authorization':'Bearer test-opaque-access-token'}))
            client=await fixture.session()
            result=await client.call_tool('cs_bootstrap',{})
            self.assertFalse(result.isError,str(result))
            context=result.structuredContent
            self.assertTrue(context['coverage']['instructions_complete']);self.assertEqual(context['account']['email'],'owner@example.test')
            self.assertEqual(context['instructions']['authority'],'engine_published_copy')
            self.assertEqual(context['instructions']['documents'][1]['text'],body[0])
            self.assertNotIn('service-secret',str(result));self.assertNotIn('native-client',str(result))
            setup=await client.call_tool('cs_bootstrap',{'codex_server':'existing-operator'})
            self.assertEqual(setup.structuredContent['codex_setup']['expected_profile_uid'],'owner')
            args={'session_id':'test-session','hook_event':'UserPromptSubmit','expected_profile_uid':'owner'}
            async def hook(**kw):
                value=await client.call_tool('cs_bootstrap_hook',{**args,**kw});self.assertFalse(value.isError,str(value));return json.loads(value.content[0].text)['hookSpecificOutput']['additionalContext']
            # First prompt is the cold-start fallback if SessionStart had no server.
            first=await hook();self.assertIn(body[0],first)
            self.assertEqual(await hook(),'')
            self.assertIn(body[0],await hook(hook_event='SessionStart',source='compact'))
            body[0]='Updated exact rule.';revision[0]=2
            self.assertIn(body[0],await hook())
            self.assertIn(body[0],await hook(force=True))
            body[0]='è' * 20000;revision[0]=3
            large=await client.call_tool('cs_bootstrap',{});self.assertFalse(large.isError,str(large))
            self.assertFalse(large.structuredContent['coverage']['instructions_complete'])
            next_read=next(x for x in large.structuredContent['next_read'] if x['instruction_path']=='procedures.md')
            page=await client.call_tool('cs_bootstrap',next_read);self.assertFalse(page.isError,str(page))
            self.assertEqual(page.structuredContent['instruction_page']['text'],body[0][:8192])
            body[0]='Changed since continuation.';revision[0]=4
            self.assertTrue((await client.call_tool('cs_bootstrap',next_read)).isError)
            for changes in ({'expected_profile_uid':'other'},{'session_id':'bad\nname'},{'hook_event':'Stop'},{'force':'true'},{'surprise':True}):
                self.assertTrue((await client.call_tool('cs_bootstrap_hook',{**args,**changes})).isError)
            before=len(reads);fixture.payload['active']=False
            refused = await fixture.http.post('/mcp', json={'jsonrpc':'2.0','id':99,'method':'tools/call','params':{'name':'cs_bootstrap','arguments':{}}})
            self.assertEqual(refused.status_code,401);self.assertEqual(len(reads),before)
        fixture.run_case(exercise)

    def test_sdk_legacy_reader_identity_only_does_not_read_rules(self):
        fixture=OperatorHTTPTests()
        async def exercise():
            client=await fixture.session();result=await client.call_tool('cs_bootstrap',{})
            self.assertFalse(result.isError,str(result))
            self.assertEqual(result.structuredContent['instructions']['status'],'denied')
            self.assertFalse(result.structuredContent['coverage']['instructions_complete'])
            self.assertEqual(fixture.calls,[])
        fixture.run_case(exercise)

    def test_service_cache_bound_ttl_scope_and_return_recheck(self):
        import asyncio
        from cs.operator_read import ReadGrant,ReadError
        async def exercise():
            now=[0];valid=[True];grant=ReadGrant('owner','owner','company','client','resource',9999999999,frozenset({'operator.read'}),frozenset(),frozenset(),'grant')
            class Verifier:
                async def verify_token(self,token):return SimpleNamespace(claims=grant) if valid[0] else None
                def grant(self,claims):return claims
            class Port:
                async def identity(self,g):return {'profile_uid':'owner','company_ref':'company','email':'owner@example.test','capabilities':['operator_identity']}
            service=BootstrapService(Verifier(),Port(),clock=lambda:now[0],cache_limit=2,ttl=5)
            args=dict(hook_event='UserPromptSubmit',expected_profile_uid='owner')
            for session in ['one','two','three']:await service.hook('opaque',session_id=session,**args)
            self.assertEqual(len(service._returned),2)
            self.assertEqual((await service.hook('opaque',session_id='three',**args))['hookSpecificOutput']['additionalContext'],'')
            now[0]=6
            self.assertTrue((await service.hook('opaque',session_id='three',**args))['hookSpecificOutput']['additionalContext'])
            original=Port.identity
            async def revoke(self,g):
                result=await original(self,g);valid[0]=False;return result
            Port.identity=revoke
            with self.assertRaises(ReadError):await service.context('opaque')
        asyncio.run(exercise())
