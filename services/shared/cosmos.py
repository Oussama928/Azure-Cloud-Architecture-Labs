import logging
import os
import urllib.parse
from typing import Optional

from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal

logger = logging.getLogger(__name__)


def _normalize_gremlin_endpoint(endpoint: str) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    return f"wss://{parsed.netloc}/gremlin"


def get_cosmos_config_from_env() -> dict:
    endpoint = os.getenv("COSMOS_DB_ENDPOINT") or ""
    key = os.getenv("COSMOS_DB_KEY") or os.getenv("COSMOS_DB_PRIMARY_KEY") or ""
    database = os.getenv("COSMOS_DB_DATABASE", "changetrace-graph")
    graph = os.getenv("COSMOS_DB_GRAPH", "dependency-graph")

    conn_str = os.getenv("COSMOS_CONNECTION_STRING", "")
    if not endpoint and conn_str:
        for param in conn_str.split(";"):
            param = param.strip()
            if param.startswith("AccountEndpoint="):
                endpoint = param[16:]
            elif param.startswith("AccountKey="):
                key = param[11:]

    if not endpoint:
        cosmos_name = os.getenv("COSMOS_DB_NAME", "")
        if cosmos_name:
            endpoint = f"wss://{cosmos_name}.gremlin.cosmos.azure.com:443/"

    # Convert HTTPS endpoint to WSS for Gremlin
    if endpoint.startswith("https://"):
        endpoint = endpoint.replace("https://", "wss://").replace("documents.azure.com", "gremlin.cosmos.azure.com")

    return {
        "endpoint": endpoint,
        "key": key,
        "database": database,
        "graph": graph,
    }


def create_gremlin_client(
    endpoint: str,
    key: str,
    database: str = "changetrace-graph",
    graph: str = "dependency-graph",
) -> Optional[client.Client]:
    if not endpoint or not key:
        logger.warning("Cosmos DB credentials not configured")
        return None

    endpoint = _normalize_gremlin_endpoint(endpoint)
    username = f"/dbs/{database}/colls/{graph}"
    gremlin_client = client.Client(
        endpoint,
        "g",
        username=username,
        password=key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )
    logger.info("Initialized Gremlin client")
    return gremlin_client


def create_traversal_source(
    endpoint: str,
    key: str,
    database: str = "changetrace-graph",
    graph: str = "dependency-graph",
) -> Optional[DriverRemoteConnection]:
    if not endpoint or not key:
        return None
    endpoint = _normalize_gremlin_endpoint(endpoint)
    username = f"/dbs/{database}/colls/{graph}"
    return DriverRemoteConnection(endpoint, "g", username=username, password=key)
