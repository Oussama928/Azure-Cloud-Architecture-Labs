"""
Kubernetes Source Collector for ChangeTrace.

Collects change events from the Kubernetes API, using the watch API for
real-time events.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
from pydantic import BaseModel, Field

from ..models.change_event import (
    ChangeEvent,
    ChangeSource,
    ChangeStatus,
    ChangeType,
    KubernetesChangeDetail,
    ResourceReference,
)

logger = logging.getLogger(__name__)


class K8sConfig(BaseModel):
    """Configuration for Kubernetes source"""
    tenant_id: str | None = None
    cluster_id: str | None = None
    # Connection
    kubeconfig_path: str | None = None
    context: str | None = None
    in_cluster: bool = False  # Use in-cluster config

    # Namespace filters
    namespaces: list[str] = Field(default_factory=lambda: ["default", "production", "staging"])
    exclude_namespaces: list[str] = Field(default_factory=lambda: ["kube-system", "kube-public", "kube-node-lease"])

    # Resource types to watch
    watch_deployments: bool = True
    watch_statefulsets: bool = True
    watch_daemonsets: bool = True
    watch_configmaps: bool = True
    watch_secrets: bool = True
    watch_services: bool = True
    watch_ingresses: bool = True
    watch_pods: bool = False

    # Polling fallback (if watch not available)
    poll_interval_seconds: int = 60
    lookback_hours: int = 24

    # Labels/annotations for filtering
    label_selector: str | None = None
    annotation_selector: str | None = None


class K8sResourceEvent(BaseModel):
    """Kubernetes resource event"""
    event_type: str  # ADDED, MODIFIED, DELETED
    resource_type: str
    namespace: str
    name: str
    uid: str
    resource_version: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    spec: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    tenant_id: str | None = None
    cluster_id: str | None = None


class K8sSource:
    """Kubernetes change event collector."""

    def __init__(self, config: K8sConfig):
        self.config = config
        self._apps_v1: client.AppsV1Api | None = None
        self._core_v1: client.CoreV1Api | None = None
        self._networking_v1: client.NetworkingV1Api | None = None
        self._watchers: list[watch.Watch] = []
        self._running = False
        self._last_poll_time: dict[str, datetime] = {}

    async def initialize(self) -> None:
        """Initialize Kubernetes client"""
        if self.config.in_cluster:
            config.load_incluster_config()
        else:
            config.load_kube_config(
                config_file=self.config.kubeconfig_path,
                context=self.config.context
            )

        self._apps_v1 = client.AppsV1Api()
        self._core_v1 = client.CoreV1Api()
        self._networking_v1 = client.NetworkingV1Api()

        logger.info("Initialized Kubernetes client")

    async def close(self) -> None:
        """Stop all watchers"""
        self._running = False
        for w in self._watchers:
            w.stop()
        self._watchers.clear()

    def _should_process_namespace(self, namespace: str) -> bool:
        """Check if namespace should be processed"""
        if namespace in self.config.exclude_namespaces:
            return False
        if self.config.namespaces and namespace not in self.config.namespaces:
            return False
        return True

    def _should_process_resource(self, labels: dict[str, str], annotations: dict[str, str]) -> bool:
        """Check if resource matches label/annotation selectors"""
        if self.config.label_selector:
            # Simple label selector matching
            for key, value in self._parse_label_selector(self.config.label_selector):
                if labels.get(key) != value:
                    return False

        if self.config.annotation_selector:
            for key, value in self._parse_label_selector(self.config.annotation_selector):
                if annotations.get(key) != value:
                    return False

        return True

    def _parse_label_selector(self, selector: str) -> list[tuple]:
        """Parse label selector string into key-value pairs"""
        pairs = []
        for part in selector.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                pairs.append((k.strip(), v.strip()))
        return pairs

    async def watch_deployments(self, namespace: str) -> AsyncGenerator[K8sResourceEvent, None]:
        """Watch Deployment changes"""
        if not self._apps_v1:
            await self.initialize()

        w = watch.Watch()
        self._watchers.append(w)

        try:
            for event in w.stream(
                self._apps_v1.list_namespaced_deployment,
                namespace=namespace,
                label_selector=self.config.label_selector,
            ):
                if not self._running:
                    break

                obj = event["object"]
                yield self._convert_k8s_event(event["type"], "Deployment", obj)
        except ApiException as e:
            if e.status != 410:  # Gone (resource version too old)
                logger.error(f"Error watching deployments in {namespace}: {e}")
        finally:
            w.stop()
            self._watchers.remove(w)

    async def watch_statefulsets(self, namespace: str) -> AsyncGenerator[K8sResourceEvent, None]:
        """Watch StatefulSet changes"""
        if not self._apps_v1:
            await self.initialize()

        w = watch.Watch()
        self._watchers.append(w)

        try:
            for event in w.stream(
                self._apps_v1.list_namespaced_stateful_set,
                namespace=namespace,
                label_selector=self.config.label_selector,
            ):
                if not self._running:
                    break

                obj = event["object"]
                yield self._convert_k8s_event(event["type"], "StatefulSet", obj)
        except ApiException as e:
            if e.status != 410:
                logger.error(f"Error watching statefulsets in {namespace}: {e}")
        finally:
            w.stop()
            self._watchers.remove(w)

    async def watch_daemonsets(self, namespace: str) -> AsyncGenerator[K8sResourceEvent, None]:
        """Watch DaemonSet changes"""
        if not self._apps_v1:
            await self.initialize()

        w = watch.Watch()
        self._watchers.append(w)

        try:
            for event in w.stream(
                self._apps_v1.list_namespaced_daemon_set,
                namespace=namespace,
                label_selector=self.config.label_selector,
            ):
                if not self._running:
                    break

                obj = event["object"]
                yield self._convert_k8s_event(event["type"], "DaemonSet", obj)
        except ApiException as e:
            if e.status != 410:
                logger.error(f"Error watching daemonsets in {namespace}: {e}")
        finally:
            w.stop()
            self._watchers.remove(w)

    async def watch_configmaps(self, namespace: str) -> AsyncGenerator[K8sResourceEvent, None]:
        """Watch ConfigMap changes"""
        if not self._core_v1:
            await self.initialize()

        w = watch.Watch()
        self._watchers.append(w)

        try:
            for event in w.stream(
                self._core_v1.list_namespaced_config_map,
                namespace=namespace,
                label_selector=self.config.label_selector,
            ):
                if not self._running:
                    break

                obj = event["object"]
                yield self._convert_k8s_event(event["type"], "ConfigMap", obj)
        except ApiException as e:
            if e.status != 410:
                logger.error(f"Error watching configmaps in {namespace}: {e}")
        finally:
            w.stop()
            self._watchers.remove(w)

    async def watch_secrets(self, namespace: str) -> AsyncGenerator[K8sResourceEvent, None]:
        """Watch Secret changes (metadata only, no data)"""
        if not self._core_v1:
            await self.initialize()

        w = watch.Watch()
        self._watchers.append(w)

        try:
            for event in w.stream(
                self._core_v1.list_namespaced_secret,
                namespace=namespace,
                label_selector=self.config.label_selector,
            ):
                if not self._running:
                    break

                obj = event["object"]
                # Don't include secret data in events
                event_obj = self._convert_k8s_event(event["type"], "Secret", obj)
                event_obj.spec = {}  # Clear spec to avoid leaking secrets
                event_obj.tenant_id = self.config.tenant_id
                event_obj.cluster_id = self.config.cluster_id
                yield event_obj
        except ApiException as e:
            if e.status != 410:
                logger.error(f"Error watching secrets in {namespace}: {e}")
        finally:
            w.stop()
            self._watchers.remove(w)

    async def watch_services(self, namespace: str) -> AsyncGenerator[K8sResourceEvent, None]:
        """Watch Service changes"""
        if not self._core_v1:
            await self.initialize()

        w = watch.Watch()
        self._watchers.append(w)

        try:
            for event in w.stream(
                self._core_v1.list_namespaced_service,
                namespace=namespace,
                label_selector=self.config.label_selector,
            ):
                if not self._running:
                    break

                obj = event["object"]
                yield self._convert_k8s_event(event["type"], "Service", obj)
        except ApiException as e:
            if e.status != 410:
                logger.error(f"Error watching services in {namespace}: {e}")
        finally:
            w.stop()
            self._watchers.remove(w)

    async def watch_ingresses(self, namespace: str) -> AsyncGenerator[K8sResourceEvent, None]:
        """Watch Ingress changes"""
        if not self._networking_v1:
            await self.initialize()

        w = watch.Watch()
        self._watchers.append(w)

        try:
            for event in w.stream(
                self._networking_v1.list_namespaced_ingress,
                namespace=namespace,
                label_selector=self.config.label_selector,
            ):
                if not self._running:
                    break

                obj = event["object"]
                yield self._convert_k8s_event(event["type"], "Ingress", obj)
        except ApiException as e:
            if e.status != 410:
                logger.error(f"Error watching ingresses in {namespace}: {e}")
        finally:
            w.stop()
            self._watchers.remove(w)

    def _convert_k8s_event(self, event_type: str, resource_type: str, obj: Any) -> K8sResourceEvent:
        """Convert Kubernetes watch event to our format"""
        metadata = obj.metadata

        spec = {}
        if hasattr(obj, "spec") and obj.spec:
            spec = self._spec_to_dict(obj.spec)

        return K8sResourceEvent(
            event_type=event_type,
            resource_type=resource_type,
            namespace=metadata.namespace or "default",
            name=metadata.name,
            uid=metadata.uid,
            resource_version=metadata.resource_version,
            labels=metadata.labels or {},
            annotations=metadata.annotations or {},
            spec=spec,
            timestamp=datetime.utcnow(),
            tenant_id=self.config.tenant_id,
            cluster_id=self.config.cluster_id,
        )

    def _spec_to_dict(self, spec: Any) -> dict[str, Any]:
        """Convert Kubernetes spec object to dict"""
        if hasattr(spec, "to_dict"):
            return spec.to_dict()
        elif hasattr(spec, "__dict__"):
            return {k: v for k, v in spec.__dict__.items() if not k.startswith("_")}
        return {}

    def k8s_event_to_change_event(self, event: K8sResourceEvent) -> ChangeEvent | None:
        """Convert Kubernetes resource event to ChangeEvent"""
        # Delegate to the pure module-level conversion, preserving namespace
        # filtering via the instance's exclude-namespaces configuration.
        from .k8s_source import k8s_resource_event_to_change_event
        if not self._should_process_namespace(event.namespace):
            return None
        if not self._should_process_resource(event.labels, event.annotations):
            return None
        return k8s_resource_event_to_change_event(event)

    def _get_api_version(self, resource_type: str) -> str:
        """Get API version for resource type"""
        versions = {
            "Deployment": "apps/v1",
            "StatefulSet": "apps/v1",
            "DaemonSet": "apps/v1",
            "ConfigMap": "v1",
            "Secret": "v1",
            "Service": "v1",
            "Ingress": "networking.k8s.io/v1",
            "Pod": "v1",
        }
        return versions.get(resource_type, "v1")

    def _namespace_to_environment(self, namespace: str) -> str:
        """Map namespace to environment"""
        ns_lower = namespace.lower()
        if "prod" in ns_lower:
            return "production"
        elif "staging" in ns_lower or "stage" in ns_lower:
            return "staging"
        elif "dev" in ns_lower:
            return "development"
        elif "test" in ns_lower:
            return "test"
        return "production"

    # Polling fallback methods

    async def poll_deployments(self, namespace: str) -> list[ChangeEvent]:
        """Poll for deployment changes"""
        if not self._apps_v1:
            await self.initialize()

        events = []
        last_poll = self._last_poll_time.get(f"deployments/{namespace}")
        if last_poll is not None:
            last_poll = self._make_aware(last_poll)

        try:
            deployments = self._apps_v1.list_namespaced_deployment(
                namespace=namespace,
                label_selector=self.config.label_selector,
            )

            for dep in deployments.items:
                if last_poll and dep.metadata.creation_timestamp:
                    if dep.metadata.creation_timestamp <= last_poll:
                        continue

                k8s_event = K8sResourceEvent(
                    event_type="MODIFIED",
                    resource_type="Deployment",
                    namespace=namespace,
                    name=dep.metadata.name,
                    uid=dep.metadata.uid,
                    resource_version=dep.metadata.resource_version,
                    labels=dep.metadata.labels or {},
                    annotations=dep.metadata.annotations or {},
                    spec=self._spec_to_dict(dep.spec),
                    timestamp=datetime.utcnow(),
                )

                change_event = self.k8s_event_to_change_event(k8s_event)
                if change_event:
                    events.append(change_event)

            self._last_poll_time[f"deployments/{namespace}"] = datetime.utcnow()

        except ApiException as e:
            logger.error(f"Error polling deployments in {namespace}: {e}")

        return events

    async def _poll_resources(self, namespace: str, resource_type: str, api_call) -> list[ChangeEvent]:
        """Generic poll for any K8s resource type"""
        if not self._apps_v1:
            await self.initialize()

        events = []
        last_poll = self._last_poll_time.get(f"{resource_type}/{namespace}")
        if last_poll is not None:
            last_poll = self._make_aware(last_poll)

        try:
            resources = api_call(namespace, label_selector=self.config.label_selector)
            for item in resources.items:
                if last_poll and item.metadata.creation_timestamp:
                    if item.metadata.creation_timestamp <= last_poll:
                        continue
                k8s_event = K8sResourceEvent(
                    event_type="MODIFIED",
                    resource_type=resource_type,
                    namespace=namespace,
                    name=item.metadata.name,
                    uid=item.metadata.uid,
                    resource_version=item.metadata.resource_version,
                    labels=item.metadata.labels or {},
                    annotations=item.metadata.annotations or {},
                    spec=self._spec_to_dict(getattr(item, 'spec', None)),
                    timestamp=datetime.utcnow(),
                )
                change_event = self.k8s_event_to_change_event(k8s_event)
                if change_event:
                    events.append(change_event)
            self._last_poll_time[f"{resource_type}/{namespace}"] = datetime.utcnow()
        except ApiException as e:
            logger.error(f"Error polling {resource_type} in {namespace}: {e}")

        return events

    @staticmethod
    def _make_aware(dt):
        """Convert naive datetime to UTC-aware"""
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    async def poll_statefulsets(self, namespace: str) -> list[ChangeEvent]:
        return await self._poll_resources(namespace, "StatefulSet", self._apps_v1.list_namespaced_stateful_set)

    async def poll_daemonsets(self, namespace: str) -> list[ChangeEvent]:
        return await self._poll_resources(namespace, "DaemonSet", self._apps_v1.list_namespaced_daemon_set)

    async def poll_configmaps(self, namespace: str) -> list[ChangeEvent]:
        return await self._poll_resources(namespace, "ConfigMap", self._core_v1.list_namespaced_config_map)

    async def poll_secrets(self, namespace: str) -> list[ChangeEvent]:
        return await self._poll_resources(namespace, "Secret", self._core_v1.list_namespaced_secret)

    async def poll_services(self, namespace: str) -> list[ChangeEvent]:
        return await self._poll_resources(namespace, "Service", self._core_v1.list_namespaced_service)

    async def poll_ingresses(self, namespace: str) -> list[ChangeEvent]:
        return await self._poll_resources(namespace, "Ingress", self._networking_v1.list_namespaced_ingress)

    async def poll_all_namespaces(self) -> list[ChangeEvent]:
        """Poll all configured namespaces for changes"""
        all_events = []

        for namespace in self.config.namespaces:
            if not self._should_process_namespace(namespace):
                continue

            if self.config.watch_deployments:
                events = await self.poll_deployments(namespace)
                all_events.extend(events)

            if self.config.watch_statefulsets:
                events = await self.poll_statefulsets(namespace)
                all_events.extend(events)

            if self.config.watch_daemonsets:
                events = await self.poll_daemonsets(namespace)
                all_events.extend(events)

            if self.config.watch_configmaps:
                events = await self.poll_configmaps(namespace)
                all_events.extend(events)

            if self.config.watch_secrets:
                events = await self.poll_secrets(namespace)
                all_events.extend(events)

            if self.config.watch_services:
                events = await self.poll_services(namespace)
                all_events.extend(events)

            if self.config.watch_ingresses:
                events = await self.poll_ingresses(namespace)
                all_events.extend(events)

        return all_events

    async def start_watching(self) -> AsyncGenerator[ChangeEvent, None]:
        """Poll for changes periodically (non-blocking alternative to watch API)"""
        self._running = True
        logger.info(f"Starting K8s polling every {self.config.poll_interval_seconds}s")
        while self._running:
            try:
                events = await self.poll_all_namespaces()
                for event in events:
                    yield event
            except Exception as e:
                logger.error(f"Error polling K8s: {e}")
            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _watch_and_convert(self, watcher_gen: AsyncGenerator[K8sResourceEvent, None]) -> AsyncGenerator[ChangeEvent, None]:
        """Convert K8s events to ChangeEvents"""
        async for k8s_event in watcher_gen:
            change_event = self.k8s_event_to_change_event(k8s_event)
            if change_event:
                yield change_event


async def create_k8s_source(config: K8sConfig) -> K8sSource:
    """Factory function to create and initialize K8s source"""
    source = K8sSource(config)
    await source.initialize()
    return source


# Module-level pure conversion helpers (reused by the customer-agent ingestion
# path and by K8sSource.k8s_event_to_change_event).

def k8s_resource_event_to_change_event(event: K8sResourceEvent) -> ChangeEvent | None:
    """Convert a K8sResourceEvent into a ChangeEvent (namespace-filter aware)."""
    if event.namespace in K8sConfig().exclude_namespaces:
        return None

    if event.event_type in ("ADDED", "MODIFIED", "DELETED"):
        change_type = ChangeType.CONFIG_CHANGE
        status = ChangeStatus.SUCCEEDED
    else:
        return None

    service_name = event.labels.get("app", event.labels.get("app.kubernetes.io/name", event.name))

    resource_ref = ResourceReference(
        api_version=_get_api_version(event.resource_type),
        kind=event.resource_type,
        name=event.name,
        namespace=event.namespace,
        uid=event.uid,
        labels=event.labels,
        annotations=event.annotations,
    )

    change_detail = KubernetesChangeDetail(
        resource=resource_ref,
        operation=event.event_type,
        diff=event.spec if event.event_type == "MODIFIED" else None,
        previous_manifest=None,
        new_manifest=event.spec if event.event_type in ["ADDED", "MODIFIED"] else None,
    )

    return ChangeEvent(
        change_type=change_type,
        source=ChangeSource.KUBERNETES,
        status=status,
        timestamp=event.timestamp,
        service_name=service_name,
        environment=_namespace_to_environment(event.namespace),
        namespace=event.namespace,
        author="kubernetes-controller",
        description=f"Kubernetes {event.resource_type} {event.event_type.lower()}: {event.name}",
        summary=f"{event.resource_type} {event.name} {event.event_type.lower()} in {event.namespace}",
        kubernetes_changes=[change_detail],
        labels={
            "k8s.event_type": event.event_type,
            "k8s.resource_type": event.resource_type,
            "k8s.namespace": event.namespace,
            "k8s.resource_version": event.resource_version,
            "changetrace.tenant_id": event.tenant_id or "",
            "changetrace.cluster_id": event.cluster_id or "",
        },
        correlation_id=event.uid,
    )


def _get_api_version(resource_type: str) -> str:
    versions = {
        "Deployment": "apps/v1",
        "StatefulSet": "apps/v1",
        "DaemonSet": "apps/v1",
        "ConfigMap": "v1",
        "Secret": "v1",
        "Service": "v1",
        "Ingress": "networking.k8s.io/v1",
        "Pod": "v1",
    }
    return versions.get(resource_type, "v1")


def _namespace_to_environment(namespace: str) -> str:
    ns_lower = namespace.lower()
    if "prod" in ns_lower:
        return "production"
    elif "staging" in ns_lower or "stage" in ns_lower:
        return "staging"
    elif "dev" in ns_lower:
        return "development"
    elif "test" in ns_lower:
        return "test"
    return "production"
