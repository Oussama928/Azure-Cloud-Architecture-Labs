"""
Structured Logging with Correlation IDs for ChangeTrace.

Provides consistent logging across all services with trace context propagation.
"""

import contextvars
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Context variables for trace propagation
trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)
span_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("span_id", default=None)
service_name_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("service_name", default=None)
operation_name_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("operation_name", default=None)


@dataclass
class LogContext:
    """Structured log context with trace information."""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    service_name: str = "unknown"
    operation_name: str = "unknown"
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for structured logging."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "service_name": self.service_name,
            "operation_name": self.operation_name,
            **self.extra,
        }
    
    def set_context_vars(self) -> None:
        """Set context variables for automatic propagation."""
        trace_id_var.set(self.trace_id)
        span_id_var.set(self.span_id)
        service_name_var.set(self.service_name)
        operation_name_var.set(self.operation_name)
    
    @classmethod
    def from_context(cls) -> "LogContext":
        """Create LogContext from current context variables."""
        return cls(
            trace_id=trace_id_var.get() or str(uuid.uuid4()),
            span_id=span_id_var.get() or str(uuid.uuid4())[:8],
            service_name=service_name_var.get() or "unknown",
            operation_name=operation_name_var.get() or "unknown",
        )


class StructuredFormatter(logging.Formatter):
    """JSON formatter with trace context."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Get trace context
        trace_id = trace_id_var.get()
        span_id = span_id_var.get()
        service_name = service_name_var.get()
        operation_name = operation_name_var.get()
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id,
            "span_id": span_id,
            "service_name": service_name,
            "operation_name": operation_name,
        }
        
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "name", "pathname", "process", "processName",
                "relativeCreated", "thread", "threadName", "exc_info",
                "exc_text", "stack_info"
            }:
                log_entry[key] = value
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry, default=str)


def setup_structured_logging(
    service_name: str,
    level: int = logging.INFO,
    json_output: bool = True,
) -> logging.Logger:
    """
    Set up structured logging for a service.
    Returns Configured logger instance
        
    """
    logger = logging.getLogger(service_name)
    logger.setLevel(level)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    handler = logging.StreamHandler(sys.stdout)
    
    if json_output:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | "
                "trace_id=%(trace_id)s span_id=%(span_id)s | %(message)s"
            )
        )
    
    logger.addHandler(handler)
    logger.propagate = False
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger with structured formatting."""
    return logging.getLogger(name)


class LogContextManager:
    """Context manager for setting log context."""
    
    def __init__(
        self,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        service_name: Optional[str] = None,
        operation_name: Optional[str] = None,
        **extra: Any,
    ):
        self.context = LogContext(
            trace_id=trace_id or str(uuid.uuid4()),
            span_id=span_id or str(uuid.uuid4())[:8],
            service_name=service_name or "unknown",
            operation_name=operation_name or "unknown",
            extra=extra,
        )
        self.tokens: list = []
    
    def __enter__(self) -> LogContext:
        self.context.set_context_vars()
        return self.context
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Reset context variables
        trace_id_var.set(None)
        span_id_var.set(None)
        service_name_var.set(None)
        operation_name_var.set(None)


def log_with_context(
    logger: logging.Logger,
    level: int,
    message: str,
    **extra: Any,
) -> None:
    """Log a message with current trace context."""
    context = LogContext.from_context()
    extra.update(context.to_dict())
    logger.log(level, message, extra=extra)


# Convenience functions
def info(logger: logging.Logger, message: str, **extra: Any) -> None:
    log_with_context(logger, logging.INFO, message, **extra)


def warning(logger: logging.Logger, message: str, **extra: Any) -> None:
    log_with_context(logger, logging.WARNING, message, **extra)


def error(logger: logging.Logger, message: str, **extra: Any) -> None:
    log_with_context(logger, logging.ERROR, message, **extra)


def debug(logger: logging.Logger, message: str, **extra: Any) -> None:
    log_with_context(logger, logging.DEBUG, message, **extra)


def critical(logger: logging.Logger, message: str, **extra: Any) -> None:
    log_with_context(logger, logging.CRITICAL, message, **extra)