"""Tests for Graph Builder Service."""

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
            b = GraphBuilder()
            b._gremlin_client = MagicMock()
            b._gremlin_client.submit = MagicMock()
            b._g = MagicMock()
            return b

    @pytest.mark.asyncio
    async def test_build_from_traces(self, builder):
        """Test building graph from traces."""
        mock_result = MagicMock()
        mock_result.all.return_value = MagicMock(return_value=[
            ["payment-service", "checkout-service"],
            ["order-service", "payment-service"],
        ])
        builder._gremlin_client.submit.return_value = mock_result
        builder._logs_client = MagicMock()

        with patch.object(builder, '_extract_edges_from_traces', new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = [
                {"source": "payment-service", "target": "checkout-service", "count": 100, "latency_p99": 50, "timestamp": "2024-01-15T10:00:00Z"},
                {"source": "order-service", "target": "payment-service", "count": 50, "latency_p99": 30, "timestamp": "2024-01-15T10:00:00Z"},
            ]

            with patch.object(builder, '_update_graph', new_callable=AsyncMock) as mock_update:
                mock_update.return_value = {"vertices": 3, "edges": 2}

                with patch.object(builder, '_connect', new_callable=AsyncMock):
                    with patch.object(builder, '_close', new_callable=AsyncMock):
                        result = await builder.build_from_traces(lookback_hours=1)

        assert "edges_processed" in result
        assert "vertices_updated" in result
        assert "edges_updated" in result
        assert "timestamp" in result
        assert result["edges_processed"] == 2

    @pytest.mark.asyncio
    async def test_compute_blast_radius(self, builder):
        """Test blast radius computation."""
        mock_result = MagicMock()
        mock_result.all.return_value = MagicMock(return_value=[
            ["payment-service", "checkout-service"],
            ["payment-service", "order-service"],
        ])
        builder._gremlin_client.submit.return_value = mock_result

        with patch.object(builder, '_connect', new_callable=AsyncMock):
            with patch.object(builder, '_close', new_callable=AsyncMock):
                result = await builder.compute_blast_radius("payment-service", max_hops=3)

        assert "source_service" in result
        assert "affected_services" in result
        assert "hop_count" in result
        assert "paths" in result
        assert "total_affected" in result

    @pytest.mark.asyncio
    async def test_get_service_dependencies(self, builder):
        """Test getting service dependencies."""
        mock_upstream = MagicMock()
        mock_upstream.all.return_value = MagicMock(return_value=["auth-service"])

        mock_downstream = MagicMock()
        mock_downstream.all.return_value = MagicMock(return_value=["checkout-service"])

        builder._gremlin_client.submit.side_effect = [mock_upstream, mock_downstream]

        with patch.object(builder, '_connect', new_callable=AsyncMock):
            with patch.object(builder, '_close', new_callable=AsyncMock):
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
