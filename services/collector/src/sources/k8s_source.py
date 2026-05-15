"""
Kubernetes Source Collector for ChangeTrace

Collects change events from Kubernetes API:
- Deployment/StatefulSet/DaemonSet changes
- ConfigMap/Secret changes
- Service/Ingress changes
- Pod lifecycle events (for correlation)

Uses Kubernetes watch API for real-time events.
Can run against local kind/minikube for development or AKS for production.
"""

import asyncio
import base64
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
from pydantic import BaseModel, Field

from ..models.change_event import (
    ChangeEvent,
    ChangeType,
    ChangeSource,
    ChangeStatus,
    KubernetesChangeDetail,
    ResourceReference,
)

logger = logging.getLogger(__name__)


class K8sConfig(BaseModel):
    """Configuration for Kubernetes source"""
    # Connection
    kubeconfig_path: Optional[str] = None
    context: Optional[str] = None
    in_cluster: bool = False  # Use in-cluster config
    
    # Namespace filters
    namespaces: List[str] = Field(default_factory=lambda: ["default", "production", "staging"])
    exclude_namespaces: List[str] = Field(default_factory=lambda: ["kube-system", "kube-public", "kube-node-lease"])
    
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
    label_selector: Optional[str] = None
    annotation_selector: Optional[str] = None


class K8sResourceEvent(BaseModel):
    """Kubernetes resource event"""
    event_type: str  # ADDED, MODIFIED, DELETED
    resource_type: str
    namespace: str
    name: str
    uid: str
    resource_version: str
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    spec: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class K8sSource:
    """
    Kubernetes change event collector.
    
    Uses watch API for real-time events, with polling fallback.
    """
    
    def __init__(self, config: K8sConfig):
        self.config = config
        self._apps_v1: Optional[client.AppsV1Api] = None
        self._core_v1: Optional[client.CoreV1Api] = None
        self._networking_v1: Optional[client.NetworkingV1Api] = None
        self._watchers: List[watch.Watch] = []
        self._running = False
        self._last_poll_time: Dict[str, datetime] = {}
    
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
    
    def _should_process_resource(self, labels: Dict[str, str], annotations: Dict[str, str]) -> bool:
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
    
    def _parse_label_selector(self, selector: str) -> List[tuple]:
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
        
        # Extract spec based on resource type
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
        )
    
    def _spec_to_dict(self, spec: Any) -> Dict[str, Any]:
        """Convert Kubernetes spec object to dict"""
        if hasattr(spec, "to_dict"):
            return spec.to_dict()
        elif hasattr(spec, "__dict__"):
            return {k: v for k, v in spec.__dict__.items() if not k.startswith("_")}
        return {}
    
    def k8s_event_to_change_event(self, event: K8sResourceEvent) -> Optional[ChangeEvent]:
        """Convert Kubernetes resource event to ChangeEvent"""
        # Skip if namespace not in scope
        if not self._should_process_namespace(event.namespace):
            return None
        
        # Skip if labels don't match
        if not self._should_process_resource(event.labels, event.annotations):
            return None
        
        # Determine change type
        if event.event_type == "ADDED":
            change_type = ChangeType.CONFIG_CHANGE
            status = ChangeStatus.SUCCEEDED
        elif event.event_type == "MODIFIED":
            change_type = ChangeType.CONFIG_CHANGE
            status = ChangeStatus.SUCCEEDED
        elif event.event_type == "DELETED":
            change_type = ChangeType.CONFIG_CHANGE
            status = ChangeStatus.SUCCEEDED
        else:
            return None
        
        # Extract service name from labels
        service_name = event.labels.get("app", event.labels.get("app.kubernetes.io/name", event.name))
        
        # Build resource reference
        resource_ref = ResourceReference(
            api_version=self._get_api_version(event.resource_type),
            kind=event.resource_type,
            name=event.name,
            namespace=event.namespace,
            uid=event.uid,
            labels=event.labels,
            annotations=event.annotations,
        )
        
        # Build change detail
        change_detail = KubernetesChangeDetail(
            resource=resource_ref,
            operation=event.event_type,
            diff=event.spec if event.event_type == "MODIFIED" else None,
            previous_manifest=None,  # Would need to store previous state
            new_manifest=event.spec if event.event_type in ["ADDED", "MODIFIED"] else None,
        )
        
        # Determine environment from namespace
        environment = self._namespace_to_environment(event.namespace)
        
        return ChangeEvent(
            change_type=change_type,
            source=ChangeSource.KUBERNETES,
            status=status,
            timestamp=event.timestamp,
            service_name=service_name,
            environment=environment,
            namespace=event.namespace,
            author="kubernetes-controller",  # Could be extracted from annotations
            description=f"Kubernetes {event.resource_type} {event.event_type.lower()}: {event.name}",
            summary=f"{event.resource_type} {event.name} {event.event_type.lower()} in {event.namespace}",
            kubernetes_changes=[change_detail],
            labels={
                "k8s.event_type": event.event_type,
                "k8s.resource_type": event.resource_type,
                "k8s.namespace": event.namespace,
                "k8s.resource_version": event.resource_version,
            },
            correlation_id=event.uid,
        )
    
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
    
    async def poll_deployments(self, namespace: str) -> List[ChangeEvent]:
        """Poll for deployment changes"""
        if not self._apps_v1:
            await self.initialize()
        
        events = []
        last_poll = self._last_poll_time.get(f"deployments/{namespace}")
        
        try:
            deployments = self._apps_v1.list_namespaced_deployment(
                namespace=namespace,
                label_selector=self.config.label_selector,
            )
            
            for dep in deployments.items:
                # Check if modified since last poll
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
    
    async def poll_all_namespaces(self) -> List[ChangeEvent]:
        """Poll all configured namespaces for changes"""
        all_events = []
        
        for namespace in self.config.namespaces:
            if not self._should_process_namespace(namespace):
                continue
            
            if self.config.watch_deployments:
                events = await self.poll_deployments(namespace)
                all_events.extend(events)
            
            # Add other resource types similarly...
        
        return all_events
    
    async def start_watching(self) -> AsyncGenerator[ChangeEvent, None]:
        """Start watching all resource types in all namespaces"""
        self._running = True
        
        # Create watch tasks for each namespace and resource type
        tasks = []
        
        for namespace in self.config.namespaces:
            if not self._should_process_namespace(namespace):
                continue
            
            if self.config.watch_deployments:
                tasks.append(self._watch_and_convert(self.watch_deployments(namespace)))
            if self.config.watch_statefulsets:
                tasks.append(self._watch_and_convert(self.watch_statefulsets(namespace)))
            if self.config.watch_daemonsets:
                tasks.append(self._watch_and_convert(self.watch_daemonsets(namespace)))
            if self.config.watch_configmaps:
                tasks.append(self._watch_and_convert(self.watch_configmaps(namespace)))
            if self.config.watch_secrets:
                tasks.append(self._watch_and_convert(self.watch_secrets(namespace)))
            if self.config.watch_services:
                tasks.append(self._watch_and_convert(self.watch_services(namespace)))
            if self.config.watch_ingresses:
                tasks.append(self._watch_and_convert(self.watch_ingresses(namespace)))
        
        # Run all watchers concurrently
        for task in asyncio.as_completed(tasks):
            try:
                async for event in await task:
                    yield event
            except Exception as e:
                logger.error(f"Watcher error: {e}")
    
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