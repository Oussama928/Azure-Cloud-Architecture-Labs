"""Blast Radius Calculator for Graph Builder."""

import logging
import os
from typing import Any, Dict, List, Optional, Set

from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.process.graph_traversal import __
from services.shared.cosmos import get_cosmos_config_from_env
import urllib.parse

logger = logging.getLogger(__name__)


class BlastRadiusCalculator:
    """Calculates blast radius from a service using graph traversal."""
    
    def __init__(self, gremlin_client=None):
        self.gremlin_client = gremlin_client
        self._connection = None
        self._g = None
    
    async def _connect(self):
        """Establish connection to Cosmos DB Gremlin."""
        if self._g is not None:
            return
            
        config = get_cosmos_config_from_env()
        endpoint = config["endpoint"]
        key = config["key"]
        database = config["database"]
        graph = config["graph"]
        
        if not endpoint or not key:
            raise ValueError("Cosmos DB credentials not configured. Set COSMOS_DB_ENDPOINT and COSMOS_DB_KEY environment variables.")
        
        parsed = urllib.parse.urlparse(endpoint)
        host = parsed.netloc
        
        self._client = client.Client(
            f"wss://{host}/gremlin",
            "g",
            username=f"/dbs/{database}/colls/{graph}",
            password=key,
            message_serializer=serializer.GraphSONSerializersV2d0()
        )
        
        self._connection = DriverRemoteConnection(
            f"wss://{host}/gremlin",
            "g",
            username=f"/dbs/{database}/colls/{graph}",
            password=key
        )
        
        self._g = traversal().withRemote(self._connection)
        logger.info("Connected to Cosmos DB Gremlin")
    
    async def _close(self):
        """Close connections."""
        if self._client:
            self._client.close()
        if self._connection:
            self._connection.close()
        self._g = None
    
    async def compute_blast_radius(
        self,
        service_name: str,
        max_hops: int = 3,
        include_paths: bool = True
    ) -> Dict[str, Any]:
        """Compute blast radius from a service."""
        logger.info(f"Computing blast radius for {service_name} (max_hops: {max_hops})")
        
        await self._connect()
        
        try:
            # Query for affected services (reverse dependencies)
            affected_query = f"""
            g.V().has('serviceName', '{service_name}')
            .repeat(__.in('depends_on').simplePath())
            .times({max_hops})
            .emit()
            .dedup()
            .values('serviceName')
            """
            
            result_set = self._client.submit(affected_query)
            affected_services = list(result_set)
            
            # Remove the source service itself
            affected_services = [s for s in affected_services if s != service_name]
            result_data = {
                "source_service": service_name,
                "affected_services": affected_services,
                "hop_count": max_hops,
                "total_affected": len(affected_services)
            }
            
            if include_paths:
                paths = await self._get_dependency_paths(service_name, affected_services, max_hops)
                result_data["paths"] = paths
            
            critical = await self._identify_critical_services(affected_services)
            result_data["critical_services_affected"] = critical
            
            return result_data
            
        except Exception as e:
            logger.error(f"Blast radius computation failed: {e}")
            raise
        finally:
            await self._close()
    
    async def _get_dependency_paths(
        self,
        source: str,
        targets: List[str],
        max_hops: int
    ) -> List[List[str]]:
        """Get dependency paths from source to each target."""
        
        paths = []
        
        for target in targets:
            query = f"""
            g.V().has('serviceName', '{source}')
            .repeat(__.in('depends_on').simplePath())
            .times({max_hops})
            .until(has('serviceName', '{target}'))
            .path()
            .by('serviceName')
            .limit(5)
            """
            
            try:
                result_set = self._client.submit(query)
                for path in result_set:
                    if isinstance(path, list):
                        paths.append(path)
            except Exception as e:
                logger.warning(f"Failed to get path to {target}: {e}")
        
        return paths
    
    async def _identify_critical_services(self, services: List[str]) -> List[str]:
        """Identify critical services based on dependent count."""
        
        critical = []
        
        for service in services:
            query = f"""
            g.V().has('serviceName', '{service}')
            .in('depends_on').count()
            """
            
            try:
                result_set = self._client.submit(query)
                count = list(result_set)[0] if result_set else 0
                
                if count > 3:  # Threshold for critical
                    critical.append(service)
            except Exception as e:
                logger.warning(f"Failed to check criticality for {service}: {e}")
        
        return critical
    
    async def close(self):
        """Close connections."""
        await self._close()


async def compute_blast_radius(
    service_name: str,
    max_hops: int = 3,
    gremlin_client=None
) -> Dict[str, Any]:
    """Convenience function to compute blast radius."""
    
    calculator = BlastRadiusCalculator(gremlin_client)
    return await calculator.compute_blast_radius(service_name, max_hops)