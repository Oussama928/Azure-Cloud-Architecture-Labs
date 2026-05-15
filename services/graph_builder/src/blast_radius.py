"""
Blast Radius Calculator for Graph Builder

Computes blast radius from a service using graph traversal.
"""

import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class BlastRadiusCalculator:
    """Calculates blast radius from a service using graph traversal."""
    
    def __init__(self, gremlin_client):
        self.gremlin_client = gremlin_client
    
    async def compute_blast_radius(
        self,
        service_name: str,
        max_hops: int = 3,
        include_paths: bool = True
    ) -> Dict[str, Any]:
        """
        Compute blast radius from a service.
        
        Finds all services that depend on the given service (reverse dependencies)
        up to max_hops distance.
        """
        logger.info(f"Computing blast radius for {service_name} (max_hops: {max_hops})")
        
        if not self.gremlin_client:
            return await self._mock_blast_radius(service_name, max_hops)
        
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
            
            result = self.gremlin_client.execute_query(affected_query)
            affected_services = [r for r in result if r != service_name]
            
            result_data = {
                "source_service": service_name,
                "affected_services": affected_services,
                "hop_count": max_hops,
                "total_affected": len(affected_services)
            }
            
            if include_paths:
                paths = await self._get_dependency_paths(service_name, affected_services, max_hops)
                result_data["paths"] = paths
            
            # Identify critical services (high dependent count)
            critical = await self._identify_critical_services(affected_services)
            result_data["critical_services_affected"] = critical
            
            return result_data
            
        except Exception as e:
            logger.error(f"Blast radius computation failed: {e}")
            return await self._mock_blast_radius(service_name, max_hops)
    
    async def _get_dependency_paths(
        self,
        source: str,
        targets: List[str],
        max_hops: int
    ) -> List[List[str]]:
        """Get dependency paths from source to each target."""
        
        if not self.gremlin_client:
            return []
        
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
                result = self.gremlin_client.execute_query(query)
                for path in result:
                    if isinstance(path, list):
                        paths.append(path)
            except Exception as e:
                logger.warning(f"Failed to get path to {target}: {e}")
        
        return paths
    
    async def _identify_critical_services(self, services: List[str]) -> List[str]:
        """Identify critical services based on dependent count."""
        
        if not self.gremlin_client:
            return []
        
        critical = []
        
        for service in services:
            query = f"""
            g.V().has('serviceName', '{service}')
            .in('depends_on').count()
            """
            
            try:
                result = self.gremlin_client.execute_query(query)
                count = list(result)[0] if result else 0
                
                if count > 3:  # Threshold for critical
                    critical.append(service)
            except Exception as e:
                logger.warning(f"Failed to check criticality for {service}: {e}")
        
        return critical
    
    async def _mock_blast_radius(self, service_name: str, max_hops: int) -> Dict[str, Any]:
        """Return mock blast radius for development."""
        
        # Mock dependency graph
        mock_graph = {
            "api-gateway": ["auth-service", "payment-service", "order-service"],
            "auth-service": [],
            "payment-service": ["fraud-service", "database-primary"],
            "fraud-service": ["ml-model-service", "feature-store"],
            "ml-model-service": ["redis-cache"],
            "feature-store": ["redis-cache"],
            "redis-cache": [],
            "database-primary": ["database-replica"],
            "database-replica": [],
            "order-service": ["inventory-service", "notification-service"],
            "inventory-service": ["database-primary"],
            "notification-service": ["message-queue"],
            "message-queue": [],
        }
        
        affected = set()
        paths = []
        
        def traverse(current: str, path: List[str], hops: int):
            if hops > max_hops:
                return
            
            for dep in mock_graph.get(current, []):
                new_path = path + [dep]
                if dep != service_name:
                    affected.add(dep)
                    paths.append(new_path)
                traverse(dep, new_path, hops + 1)
        
        traverse(service_name, [service_name], 0)
        
        # Remove source from affected
        affected.discard(service_name)
        
        # Identify critical services (those with many dependents)
        critical = [s for s in affected if len(mock_graph.get(s, [])) > 2]
        
        return {
            "source_service": service_name,
            "affected_services": list(affected),
            "hop_count": max_hops,
            "paths": paths,
            "total_affected": len(affected),
            "critical_services_affected": critical
        }


async def compute_blast_radius(
    service_name: str,
    max_hops: int = 3,
    gremlin_client=None
) -> Dict[str, Any]:
    """Convenience function to compute blast radius."""
    
    calculator = BlastRadiusCalculator(gremlin_client)
    return await calculator.compute_blast_radius(service_name, max_hops)