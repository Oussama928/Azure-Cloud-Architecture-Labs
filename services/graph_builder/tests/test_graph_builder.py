"""
Tests for Graph Builder Service
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from services.graph_builder.src.main import GraphBuilder


class TestGraphBuilder:
    """Test graph builder functionality."""
    
    @pytest.fixture
    def builder(self):
        with patch.dict('os.environ', {
            'COSMOS_DB_ENDPOINT': 'https://test.gremlin.cosmos.azure.com:443/',
            'COSMOS_DB_KEY': 'test-key'
        }):
            with patch('services.graph_builder.src.main.CosmosClient'):
                return GraphBuilder()
    
    @pytest.mark.asyncio
    async def test_build_from_traces(self, builder):
        """Test building graph from traces."""
        result = await builder.build_from_traces(lookback_hours=1)
        
        assert "edges_processed" in result
        assert "vertices_updated" in result
        assert "edges_updated" in result
        assert "timestamp" in result
        assert result["edges_processed"] > 0
    
    @pytest.mark.asyncio
    async def test_compute_blast_radius(self, builder):
        """Test blast radius computation."""
        result = await builder.compute_blast_radius("payment-service", max_hops=3)
        
        assert "source_service" in result
        assert "affected_services" in result
        assert "hop_count" in result
        assert "paths" in result
        assert "total_affected" in result
    
    @pytest.mark.asyncio
    async def test_get_service_dependencies(self, builder):
        """Test getting service dependencies."""
        result = await builder.get_service_dependencies("payment-service", direction="both")
        
        assert "upstream" in result
        assert "downstream" in result


class TestGraphBuilderHTTP:
    """Test HTTP endpoints."""
    
    @pytest.fixture
    def mock_req(self):
        req = MagicMock()
        req.params = {}
        req.get_json = AsyncMock(return_value={})
        return req
    
    @pytest.mark.asyncio
    async def test_build_action(self, mock_req):
        """Test build action endpoint."""
        mock_req.params = {"action": "build"}
        mock_req.get_json = AsyncMock(return_value={"lookback_hours": 1})
        
        with patch('services.graph_builder.src.main.GraphBuilder') as mock_builder_class:
            mock_builder = AsyncMock()
            mock_builder.build_from_traces = AsyncMock(return_value={
                "edges_processed": 10,
                "vertices_updated": 5,
                "edges_updated": 10,
                "timestamp": "2024-01-15T10:00:00Z"
            })
            mock_builder_class.return_value = mock_builder
            
            from services.graph_builder.src.main import main
            response = await main(mock_req)
            
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_blast_radius_action(self, mock_req):
        """Test blast radius endpoint."""
        mock_req.params = {"action": "blast-radius", "service": "payment-service", "hops": "3"}
        
        with patch('services.graph_builder.src.main.GraphBuilder') as mock_builder_class:
            mock_builder = AsyncMock()
            mock_builder.compute_blast_radius = AsyncMock(return_value={
                "source_service": "payment-service",
                "affected_services": ["checkout-service", "order-service"],
                "hop_count": 3,
                "paths": [["payment-service", "checkout-service"]],
                "total_affected": 2
            })
            mock_builder_class.return_value = mock_builder
            
            from services.graph_builder.src.main import main
            response = await main(mock_req)
            
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_dependencies_action(self, mock_req):
        """Test dependencies endpoint."""
        mock_req.params = {"action": "dependencies", "service": "payment-service", "direction": "both"}
        
        with patch('services.graph_builder.src.main.GraphBuilder') as mock_builder_class:
            mock_builder = AsyncMock()
            mock_builder.get_service_dependencies = AsyncMock(return_value={
                "dependencies": ["auth-service", "fraud-service"],
                "dependents": ["checkout-service", "order-service"]
            })
            mock_builder_class.return_value = mock_builder
            
            from services.graph_builder.src.main import main
            response = await main(mock_req)
            
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_invalid_action(self, mock_req):
        """Test invalid action returns 400."""
        mock_req.params = {"action": "invalid"}
        
        from services.graph_builder.src.main import main
        response = await main(mock_req)
        
        assert response.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])