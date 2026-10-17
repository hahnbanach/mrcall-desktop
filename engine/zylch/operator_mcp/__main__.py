"""Explicit Linux authorization issuer; never activates a profile daemon."""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="MrCall operator authorization issuer")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    if sys.platform != "linux" or not 1024 <= args.port <= 65535 or not args.store.is_absolute():
        parser.error(
            "Linux, private absolute store and explicit unprivileged loopback port required"
        )
    try:
        import uvicorn
        from .broker_store import BrokerStore
        from .grant_api import FirebaseOwnerVerifier, create_issuer_app
        from .issuer import DesktopGrantIssuer
        from .policy import broker_policy, load_broker_config

        config = load_broker_config(args.config)
        issuer = DesktopGrantIssuer(
            BrokerStore(args.store),
            issuer=config["issuer"],
            policy_resolver=broker_policy(args.config),
            native_callbacks={(item["host"], item["path"]) for item in config["native_callbacks"]},
        )
        app = create_issuer_app(
            issuer, owner_verifier=FirebaseOwnerVerifier(config["firebase_project"])
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="critical")
    except Exception:
        parser.exit(1, "Operator issuer configuration or runtime unavailable.\n")


if __name__ == "__main__":
    main()
