import unittest
from unittest.mock import patch
from engine.tests import test_operator_mcp_http as fixtures
from zylch.operator_mcp.server import create_server

class ProjectHTTPTests(unittest.TestCase):
    def test_real_sdk_scopes_and_post_write_revocation(self):
        fixture=fixtures.OperatorHTTPTests();calls=[];revoke=[False]
        class Service:
            def __init__(self,port):pass
            async def list(self,grant,*args):calls.append('read');return {'items':[{'project':'ordinary-private-canary'}]}
            async def files(self,grant,*args):return {'items':[]}
            async def read(self,grant,*args):return {'text':'private-content-canary'}
            async def history(self,grant,*args):return {'items':[]}
            async def write(self,grant,*args):
                calls.append('write')
                if revoke[0]:fixture.payload['active']=False
                return {'revision':2,'sha256':'a'*64,'private':'write-result-canary'}
            async def create(self,grant,*args):calls.append('create');return {'project':'created'}
        def configured(verifier,*args,**kwargs):
            verifier.allowed_scopes|={'projects.read','projects.write'}
            return create_server(verifier,*args,**kwargs)
        async def exercise():
            client=await fixture.session()
            catalog={t.name:t for t in (await client.list_tools()).tools}
            expected={'list_projects','list_project_files','read_project','project_history','write_project','create_project'}
            self.assertTrue(expected<=set(catalog))
            self.assertTrue(catalog['read_project'].annotations.readOnlyHint)
            self.assertFalse(catalog['write_project'].annotations.readOnlyHint)
            denied=await client.call_tool('list_projects',{})
            self.assertTrue(denied.isError);self.assertEqual(calls,[])
            fixture.payload['scope']+=' projects.read';fixture.payload['source_classes'].append('projects')
            allowed=await client.call_tool('list_projects',{})
            self.assertFalse(allowed.isError)
            self.assertIn('ordinary-private-canary',str(allowed))
            denied=await client.call_tool('write_project',{'space_id':'company','project':'notes','path':'a.md','content':'hello','expected_revision':1})
            self.assertTrue(denied.isError);self.assertEqual(calls,['read'])
            fixture.payload['scope']+=' projects.write'
            okay=await client.call_tool('write_project',{'space_id':'company','project':'notes','path':'a.md','content':'hello','expected_revision':1})
            self.assertFalse(okay.isError)
            revoke[0]=True
            uncertain=await client.call_tool('write_project',{'space_id':'company','project':'notes','path':'a.md','content':'hello','expected_revision':1})
            self.assertTrue(uncertain.isError)
            self.assertNotIn('write-result-canary',str(uncertain))
            self.assertIn('inspect current bytes/history',str(uncertain))
            self.assertEqual(calls,['read','write','write'])
        with patch('engine.tests.test_operator_mcp_http.create_server',configured),patch('zylch.operator_mcp.projects.ProjectService',Service):
            fixture.run_case(exercise)
