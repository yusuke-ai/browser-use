import re
import logging
from typing import Dict, Callable, Any
from urllib.parse import urlparse

from browser_use.browser.context import BrowserContext

logger = logging.getLogger(__name__)

class DomainHandler:
    """
    A system that registers and executes domain-specific operations 
    when a page is first accessed.
    """
    
    def __init__(self):
        # Dictionary mapping domain patterns to handler functions
        self.domain_handlers: Dict[str, Callable] = {}
        # Set to track domains that have already been processed
        self.processed_domains: set = set()
        
    def register(self, domain_pattern: str, handler: Callable[[BrowserContext], Any]):
        """
        Register a handler function for a specific domain pattern.
        
        Args:
            domain_pattern (str): Domain pattern to match (supports regex)
            handler (Callable): Function to execute when domain is first accessed
        """
        self.domain_handlers[domain_pattern] = handler
        logger.debug(f"Registered handler for domain pattern: {domain_pattern}")
        
    def find_handler(self, url: str) -> Callable | None:
        """
        Find a handler for the given URL.
        
        Args:
            url (str): The URL to find a handler for
            
        Returns:
            Callable | None: The handler function or None if no matching handler
        """
        try:
            domain = urlparse(url).netloc.lower()
            # Remove port number if present
            if ':' in domain:
                domain = domain.split(':')[0]
                
            for pattern, handler in self.domain_handlers.items():
                # Support both exact domain matches and regex patterns
                if (pattern == domain or 
                    pattern == f"*.{domain}" or 
                    domain.endswith(f".{pattern}") or
                    re.match(pattern, domain)):
                    return handler
                    
            return None
        except Exception as e:
            logger.error(f"Error finding handler for URL {url}: {str(e)}")
            return None
            
    def check_and_execute(self, browser: BrowserContext) -> None:
        """
        Check if the current page's domain has a registered handler and execute it
        if it hasn't been processed yet.
        
        Args:
            browser (BrowserContext): The browser context object
        """
        async def _execute_handler():
            try:
                page = await browser.get_current_page()
                url = page.url
                domain = urlparse(url).netloc.lower()
                
                # Skip if this domain has already been processed
                if domain in self.processed_domains:
                    logger.debug(f"Domain {domain} already processed, skipping")
                    return
                    
                handler = self.find_handler(url)
                if handler:
                    logger.info(f"Executing first-visit handler for domain: {domain}")
                    await handler(browser)
                    # Mark this domain as processed
                    self.processed_domains.add(domain)
                    logger.debug(f"Marked domain {domain} as processed")
            except Exception as e:
                logger.error(f"Error executing domain handler: {str(e)}")
                
        # Return the async function to be executed
        return _execute_handler()
        
    def reset(self) -> None:
        """Reset the processed domains set."""
        self.processed_domains.clear()
        logger.debug("Reset processed domains tracking")