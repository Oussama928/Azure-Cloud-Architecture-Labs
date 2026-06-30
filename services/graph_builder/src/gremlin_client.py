"""Gremlin Client for ChangeTrace Graph Builder."""

import logging
import os
from typing import Any, Dict, List, Optional

from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.process.graph_traversal import __

logger = logging.getLogger(__name__)


class GremlinClient:
    """Async wrapper for Gremlin client."""
    
    def __init__(
        self,
        endpoint: Optional[str] = None,
        key: Optional[str] = None,
        database: Optional[str] = None,
        graph: Optional[str] = None
    ):
        self.endpoint = endpoint or os.getenv("COSMOS_DB_ENDPOINT")
        self.key = key or os.getenv("COSMOS_DB_KEY")
        self.database = database or os.getenv("COSMOS_DB_DATABASE", "changetrace-graph")
        self.graph = graph or os.getenv("COSMOS_DB_GRAPH", "dependency-graph")
        
        self._client = None
        self._connection = None
        self._g = None
    
    async def connect(self) -> None:
        """Establish connection to Cosmos DB Gremlin."""
        if not self.endpoint or not self.key:
            raise ValueError("Cosmos DB endpoint and key required")
        
        # Format: https://account.gremlin.cosmos.azure.com:443/
        import urllib.parse
        parsed = urllib.parse.urlparse(self.endpoint)
        host = parsed.netloc
        
        self._client = client.Client(
            f"wss://{host}/gremlin",
            "g",
            username=f"/dbs/{self.database}/colls/{self.graph}",
            password=self.key,
            message_serializer=serializer.GraphSONSerializersV2d0()
        )
        
        self._connection = DriverRemoteConnection(
            f"wss://{host}/gremlin",
            "g",
            username=f"/dbs/{self.database}/colls/{self.graph}",
            password=self.key
        )
        
        self._g = traversal().withRemote(self._connection)
        
        logger.info("Connected to Cosmos DB Gremlin")
    
    async def close(self) -> None:
        """Close connections."""
        if self._client:
            self._client.close()
        if self._connection:
            self._connection.close()
        logger.info("Closed Gremlin connections")
    
    def execute_query(self, query: str) -> List[Any]:
        """Execute Gremlin query synchronously."""
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            result_set = self._client.submit(query)
            return list(result_set)
        except Exception as e:
            logger.error(f"Gremlin query failed: {query[:200]}... Error: {e}")
            raise
    
    async def execute_query_async(self, query: str) -> List[Any]:
        """Execute Gremlin query asynchronously."""
        # Gremlin Python client is synchronous, run in executor
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.execute_query, query)
    
    def get_traversal(self):
        """Get Gremlin traversal source."""
        if not self._g:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._g
    
    # Convenience methods for common operations
    
    async def upsert_service(self, service_name: str, properties: Dict[str, Any], tenant_id: str | None = None) -> None:
        """Upsert a service vertex."""
        tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
        g = self.get_traversal()
        
        query = g.V().hasLabel('Service').has('serviceName', service_name).has('tenantId', tenant_id).fold().coalesce(
            __.unfold(),
            __.addV('Service').property('serviceName', service_name).property('tenantId', tenant_id)
        )
        
        for key, value in properties.items():
            query = query.property(key, value)
        
        query.iterate()
    
    async def upsert_dependency(
        self,
        source_service: str,
        target_service: str,
        properties: Dict[str, Any],
        tenant_id: str | None = None,
    ) -> None:
        """Upsert a dependency edge."""
        tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
        g = self.get_traversal()
        
        query = g.V().hasLabel('Service').has('serviceName', source_service).has('tenantId', tenant_id).as_('s') \
            .V().hasLabel('Service').has('serviceName', target_service).has('tenantId', tenant_id).as_('t') \
            .coalesce(
                __.inE('depends_on').where(__.outV().as_('s')),
                __.addE('depends_on').from_('s').to('t')
            )
        
        for key, value in properties.items():
            query = query.property(key, value)
        
        query.iterate()
    
    async def get_blast_radius(
        self,
        service_name: str,
        max_hops: int = 3,
        tenant_id: str | None = None,
    ) -> Dict[str, Any]:
        """Get blast radius from a service."""
        tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
        g = self.get_traversal()
        
        query = g.V().hasLabel('Service').has('serviceName', service_name).has('tenantId', tenant_id) \
            .repeat(__.in_('depends_on').simplePath()) \
            .times(max_hops) \
            .emit() \
            .dedup() \
            .values('serviceName')
        
        affected = [r for r in query if r != service_name]
        
        paths_query = g.V().hasLabel('Service').has('serviceName', service_name).has('tenantId', tenant_id) \
            .repeat(__.in_('depends_on').simplePath()) \
            .times(max_hops) \
            .until(__.has('serviceName', within(affected))) \
            .path() \
            .by('serviceName') \
            .limit(20)
        
        paths = [list(p) for p in paths_query]
        
        return {
            "source_service": service_name,
            "affected_services": affected,
            "hop_count": max_hops,
            "paths": paths,
            "total_affected": len(affected)
        }
    
    async def get_service_dependencies(
        self,
        service_name: str,
        direction: str = "both",
        tenant_id: str | None = None,
    ) -> Dict[str, List[str]]:
        """Get direct dependencies for a service."""
        tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "demo-tenant")
        g = self.get_traversal()
        
        results = {"upstream": [], "downstream": []}
        
        if direction in ("in", "both"):
            query = g.V().hasLabel('Service').has('serviceName', service_name).has('tenantId', tenant_id).in_('depends_on').values('serviceName')
            results["upstream"] = list(query)
        
        if direction in ("out", "both"):
            query = g.V().hasLabel('Service').has('serviceName', service_name).has('tenantId', tenant_id).out('depends_on').values('serviceName')
            results["downstream"] = list(query)
        
        return results


# Singleton instance
_gremlin_client: Optional[GremlinClient] = None


async def get_gremlin_client() -> GremlinClient:
    """Get or create singleton Gremlin client."""
    global _gremlin_client
    
    if _gremlin_client is None:
        _gremlin_client = GremlinClient()
        await _gremlin_client.connect()
    
    return _gremlin_client


async def close_gremlin_client() -> None:
    """Close singleton Gremlin client."""
    global _gremlin_client
    
    if _gremlin_client:
        await _gremlin_client.close()
        _gremlin_client = None
