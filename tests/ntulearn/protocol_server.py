"""Synthetic NTULearn stdio server; no network or account credentials."""
from fixtures import COURSE, PREFIX, RESPONSES, FixtureSession
from ntulearn.client.client import LearnClient
from ntulearn import mcp_server
from shared.server import main

if __name__ == "__main__":
    RESPONSES[f'{PREFIX}/courses/{COURSE}/contents/_202_1/attachments']['results'][0].update(fileName='example.txt', mimeType='text/plain')
    mcp_server.session.close()
    mcp_server.session = FixtureSession()
    mcp_server.client = LearnClient(mcp_server.session)
    main()
