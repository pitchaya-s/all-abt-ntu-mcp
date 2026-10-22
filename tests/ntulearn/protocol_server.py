"""Synthetic NTULearn stdio server; no network or account credentials."""
from fixtures import FixtureSession
from ntulearn_mcp.client import LearnClient
from ntulearn_mcp import tools
from shared.server import main

if __name__ == "__main__":
    tools.session.close()
    tools.session = FixtureSession()
    tools.client = LearnClient(tools.session)
    main()
