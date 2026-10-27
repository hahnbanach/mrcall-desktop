"""Reviewed immutable fingerprints of complete engine workflow tool schemas."""

from types import MappingProxyType

PUBLIC_WORKFLOW_TOOL_FINGERPRINTS = MappingProxyType(
    {
        "workflow_ask_user": frozenset(
            ("779746954e221b8e68295e42f4438dfb7e4f787ebef85d576206b9958f20f77b",)
        ),
        "workflow_calculate": frozenset(
            ("4ac7c9fa74adbb94875b3dc35a188ace1e70e22c1af0867e9e69f127347bf551",)
        ),
        "workflow_deadline": frozenset(
            ("ecd299cb2a0b7908fb6eb69c2586d925d5c730d98508d0901ce55739fd283a3a",)
        ),
        "workflow_finish_report": frozenset(
            (
                "010964f38cd9f74273981aebc94c87c7e710ba3fe52a21eb1d7a0cebc895daa8",
                "f38a8df3a5af9c5b34393b00f213d898c7b09c5c46eb755318ce0d734062b80c",
            )
        ),
        "workflow_legal_fetch": frozenset(
            ("0ff06ad95deb068e71dd58cc6442d5d40e54b42c068c6d5edaa2eba8f612179b",)
        ),
        "workflow_legal_passage": frozenset(
            ("cb33434dcc4bbb81f6bad61891bea32e7b383849ae468e08aa72a2bcd670a9f8",)
        ),
        "workflow_legal_read": frozenset(
            ("e09e97066ead6805c7cb23ffb12a1cc961e3cb98a29b9f26f85e78e57a661361",)
        ),
        "workflow_legal_search": frozenset(
            ("c576ecc322af05aa1b00ebd224b02f7fe1f52f9db1f2acd9bbd6a1e1afbc8c6c",)
        ),
        "workflow_read_document": frozenset(
            ("bfbfaea94f6437173a7c390f0500cd3e226bb82ebddc2b306b63335da7f506a5",)
        ),
        "workflow_read_reference": frozenset(
            ("900380f9671ba4822f0cbf37aacab2bd343a5119303ebc0dc7a19344d4ffcf47",)
        ),
    }
)
