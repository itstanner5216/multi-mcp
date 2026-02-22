import pytest
import subprocess
import time
import os
import pytest
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from pathlib import Path
from tests.utils import run_e2e_test_with_client
from pathlib import Path

# 🔍 Resolve absolute path to deployment.yaml
KIND_CLUSTER_NAME = "multi-mcp-test"
IMAGE_NAME = "multi-mcp"
NODE_PORT = 30080
BASE_DIR = Path(__file__).parent.parent.resolve()  # go up from tests/
K8S_MANIFESTS_DIR = Path(f"{BASE_DIR}/examples/k8s")
EXPECTED_TOOLS=["unit_convertor__convert_temperature","unit_convertor__convert_length", "calculator__add", "calculator__multiply"]
TEST_PROMPTS=[
        ("Convert temperature of 100 Celsius to Fahrenheit?", "212"),
        ("what's the answer for (10 + 5)?", "15"),
    ]


def run(cmd, **kwargs):
    """Run a shell command and raise error on failure."""
    print(f"🛠️  Running: {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)

def get_kind_node_ip():
    """Get the IP address of the kind node for NodePort access."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", f"{KIND_CLUSTER_NAME}-control-plane"],
        stdout=subprocess.PIPE,
        check=True,
        text=True
    )
    return result.stdout.strip() or "localhost"  # fallback to localhost if empty

def teardown_kind_cluster():
    """Delete the kind cluster unless explicitly skipped."""
    if os.getenv("SKIP_KIND_TEARDOWN") == "1":
        print("⚠️ Skipping kind cluster teardown (SKIP_KIND_TEARDOWN=1)")
        return
    run(["kind", "delete", "cluster", "--name", KIND_CLUSTER_NAME])

@pytest.fixture(scope="session")
def setup_kind_cluster():
    """Setup a Kind cluster, load Docker image, deploy MultiMCP, and wait for rollout. Returns the cluster IP."""
    run(["kind", "delete", "cluster", "--name", KIND_CLUSTER_NAME])
    run(["kind", "create", "cluster", "--name", KIND_CLUSTER_NAME])
    run(["kind", "load", "docker-image", IMAGE_NAME, "--name", KIND_CLUSTER_NAME])
    run(["kubectl", "apply", "-f", f"{K8S_MANIFESTS_DIR}/multi-mcp.yaml"])

    print("⏳ Waiting for deployment to be ready...")
    run([
        "kubectl", "rollout", "status",
        "deployment/multi-mcp",
        "--timeout=60s"
    ])
    time.sleep(20) # TODO- replace with get_tools

    kind_ip = get_kind_node_ip()
    return kind_ip

@pytest.mark.asyncio
async def test_sse_mode(setup_kind_cluster):
    """Test MultiMCP inside a Kubernetes cluster (via SSE and NodePort service)."""

    cluster_ip = setup_kind_cluster
    url=f"http://{cluster_ip}:{NODE_PORT}/sse"
    print(f"Start K8s test with mcp server in url: {url} ")

    async with MultiServerMCPClient() as client:
        await client.connect_to_server(
            "multi-mcp",
            transport="sse",
            url=url,
        )
        await run_e2e_test_with_client(client,EXPECTED_TOOLS,TEST_PROMPTS)

    teardown_kind_cluster()
