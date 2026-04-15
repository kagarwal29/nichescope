"""Utility functions for error handling and logging."""

import functools
import logging
from typing import Any, Callable

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def handle_endpoint_errors(func: Callable) -> Callable:
    """Decorator to handle errors in endpoint functions gracefully.
    
    Logs the error and returns a 500 response instead of crashing.
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            # Re-raise HTTP exceptions (they're intentional)
            raise
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=e)
            raise HTTPException(
                status_code=500,
                detail="Internal server error"
            )
    return wrapper
