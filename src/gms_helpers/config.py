"""
Configuration options for auto-maintenance behavior
"""

class AutoMaintenanceConfig:
    """Configuration for automatic maintenance operations."""
    
    # Whether to run pre-creation validation
    RUN_PRE_VALIDATION = True
    
    # Whether to run post-creation maintenance
    RUN_POST_MAINTENANCE = True
    
    # Whether to automatically fix issues when possible
    AUTO_FIX_ISSUES = True
    
    # Whether to show verbose output during maintenance
    VERBOSE_MAINTENANCE = True
    
    # Whether to block operations if critical errors are found
    BLOCK_ON_CRITICAL_ERRORS = True
    
    # Whether to show detailed reports on failures
    SHOW_DETAILED_REPORTS = True
    
    # Maintenance operations to run (can be disabled individually)
    OPERATIONS = {
        'lint': True,
        'fix_commas': True,
        'validate_paths': True,
        'check_orphans': True
    }

# Global config instance
config = AutoMaintenanceConfig() 