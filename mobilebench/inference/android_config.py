"""
Android-specific configuration for evaluation
"""

import re
from typing import Dict, List, Set

class AndroidProjectConfig:
    """Configuration for Android project evaluation"""
    
    # File patterns with relevance weights for Android projects
    FILE_PATTERNS = {
        # High priority - Core Android components
        r'.*/(ui|fragment|activity|service|receiver|provider)/.*\.(java|kt)$': 3.5,
        r'.*/MainActivity\.(java|kt)$': 3.2,
        r'.*/.*Activity\.(java|kt)$': 3.0,
        r'.*/.*Fragment\.(java|kt)$': 3.0,
        r'.*/.*Service\.(java|kt)$': 2.8,
        
        # Business logic and data models
        r'.*/model/.*\.(java|kt)$': 2.8,
        r'.*/entity/.*\.(java|kt)$': 2.8,
        r'.*/data/.*\.(java|kt)$': 2.6,
        r'.*/repository/.*\.(java|kt)$': 2.6,
        r'.*/storage/.*\.(java|kt)$': 2.5,
        r'.*/database/.*\.(java|kt)$': 2.5,
        
        # UI and presentation layer
        r'.*/adapter/.*\.(java|kt)$': 2.3,
        r'.*/viewmodel/.*\.(java|kt)$': 2.3,
        r'.*/presenter/.*\.(java|kt)$': 2.2,
        r'.*/dialog/.*\.(java|kt)$': 2.1,
        
        # Utilities and helpers
        r'.*/util/.*\.(java|kt)$': 2.0,
        r'.*/helper/.*\.(java|kt)$': 2.0,
        r'.*/manager/.*\.(java|kt)$': 1.9,
        r'.*/event/.*\.(java|kt)$': 1.8,
        r'.*/listener/.*\.(java|kt)$': 1.8,
        
        # Configuration and preferences
        r'.*/preferences/.*\.(java|kt)$': 1.8,
        r'.*/settings/.*\.(java|kt)$': 1.8,
        r'.*/config/.*\.(java|kt)$': 1.7,
        
        # Resources and layouts
        r'.*/res/layout/.*\.xml$': 1.6,
        r'.*/res/values/.*\.xml$': 1.5,
        r'.*/res/menu/.*\.xml$': 1.4,
        r'.*/res/drawable/.*\.xml$': 1.3,
        
        # Build and configuration files
        r'.*build\.gradle$': 1.3,
        r'.*gradle\.properties$': 1.2,
        r'.*AndroidManifest\.xml$': 1.4,
        r'.*proguard.*\.pro$': 1.1,
        
        # Documentation
        r'.*README.*\.(md|txt)$': 1.2,
        r'.*CHANGELOG.*\.(md|txt)$': 1.0,
        
        # Lower priority
        r'.*/test/.*\.(java|kt)$': 0.7,
        r'.*/androidTest/.*\.(java|kt)$': 0.6,
        r'.*/instrumentedTest/.*\.(java|kt)$': 0.6,
        
        # Very low priority
        r'.*/(generated|build)/.*': 0.2,
        r'.*/\.gradle/.*': 0.1,
        r'.*\.(png|jpg|jpeg|gif|webp)$': 0.3,
        r'.*\.(so|jar|aar)$': 0.2,
    }

    TEST_DIR_PATTERNS = [
        '/test/',           # Standard test directory
        '/tests/',          # Alternative test directory
        '/androidtest/',    # Android instrumented tests
        '/instrumentedtest/', # Alternative instrumented test naming
        '/androidtestdebug/', # Debug-specific Android tests
        '/unittest/',       # Unit test directory
        '/integrationtest/', # Integration test directory
        '/espresso/',       # Espresso UI tests
        '/robolectric/',    # Robolectric tests
    ]
    
    # Keywords to boost relevance when found in issue text
    ANDROID_KEYWORDS = [
        # Core Android concepts
        'activity', 'fragment', 'service', 'receiver', 'provider',
        'intent', 'bundle', 'context', 'application',
        
        # UI and interaction
        'view', 'layout', 'adapter', 'recyclerview', 'listview',
        'button', 'textview', 'edittext', 'imageview',
        'click', 'touch', 'swipe', 'gesture', 'scroll',
        
        # Lifecycle and state
        'lifecycle', 'onCreate', 'onResume', 'onPause', 'onDestroy',
        'savedInstanceState', 'configuration', 'rotation',
        
        # Data and storage
        'database', 'sqlite', 'room', 'shared preferences',
        'storage', 'file', 'cache', 'repository',
        
        # Media and playback
        'media', 'audio', 'video', 'playback', 'player',
        'stream', 'podcast', 'episode', 'feed',
        
        # Networking
        'network', 'http', 'api', 'request', 'response',
        'download', 'upload', 'sync', 'offline',
        
        # Permissions and security
        'permission', 'security', 'authentication', 'authorization',
        
        # Performance
        'memory', 'leak', 'performance', 'optimization',
        'background', 'foreground', 'thread', 'async',
        
        # Android-specific libraries and frameworks
        'androidx', 'support library', 'material design',
        'eventbus', 'glide', 'retrofit', 'okhttp',
        
        # AntennaPod specific (customize for your app)
        'feed', 'episode', 'subscription', 'download',
        'playback', 'queue', 'history', 'settings'
    ]
    
    # File extensions to include
    INCLUDED_EXTENSIONS = [
        '.java', '.kt', '.xml', '.gradle', '.properties', 
        '.md', '.txt', '.json', '.yml', '.yaml'
    ]
    
    # Directories to exclude
    EXCLUDED_DIRECTORIES = {
        'build', 'generated', '.gradle', '.idea', 
        'node_modules', '.git', '.svn'
    }
    
    # Maximum context sizes for different scenarios
    MAX_CONTEXT_SIZES = {
        'small': 30000,    # For quick iterations
        'medium': 75000,   # Default for most cases
        'large': 150000,   # For complex issues
        'xlarge': 300000   # For comprehensive analysis
    }
    
    @classmethod
    def get_context_size(cls, complexity: str = 'medium') -> int:
        """Get maximum context size for given complexity"""
        return cls.MAX_CONTEXT_SIZES.get(complexity, cls.MAX_CONTEXT_SIZES['medium'])
    
    @classmethod
    def is_android_project(cls, file_paths: Set[str]) -> bool:
        """Detect if this is an Android project"""
        android_indicators = [
            'AndroidManifest.xml',
            'build.gradle',
            'gradle.properties',
            'res/values/',
            'src/main/java/',
            'src/main/kotlin/'
        ]
        
        for indicator in android_indicators:
            if any(indicator in path for path in file_paths):
                return True
        return False
    
    @classmethod
    def get_project_type_config(cls, file_paths: Set[str]) -> Dict:
        """Get configuration based on detected project type"""
        if cls.is_android_project(file_paths):
            return {
                'patterns': cls.FILE_PATTERNS,
                'keywords': cls.ANDROID_KEYWORDS,
                'max_files': 25,  # Slightly higher for Android complexity
                'chunk_size': cls.get_context_size('medium')
            }
        else:
            # Generic configuration for non-Android projects
            return {
                'patterns': {
                    r'.*\.(java|kt|py|js|ts|cpp|c|h)$': 2.0,
                    r'.*\.(xml|json|yml|yaml)$': 1.5,
                    r'.*\.(md|txt|rst)$': 1.2,
                    r'.*/test/.*': 0.5,
                },
                'keywords': ['main', 'core', 'util', 'service', 'model'],
                'max_files': 20,
                'chunk_size': cls.get_context_size('medium')
            }


# Usage example configuration
EVALUATION_CONFIG = {
    'default': {
        'prompt_style': 'style-3',
        'file_source': 'oracle',
        'enable_smart_selection': True,
        'enable_caching': True,
        'chunk_large_contexts': True,
        'max_files': 20,
    },
    
    'android_optimized': {
        'prompt_style': 'style-3',
        'file_source': 'oracle',
        'enable_smart_selection': True,
        'enable_caching': True,
        'chunk_large_contexts': True,
        'max_files': 25,  # More files for Android complexity
        'context_size': 'medium',
    },
    
    'quick_iteration': {
        'prompt_style': 'style-3',
        'file_source': 'oracle',
        'enable_smart_selection': True,
        'enable_caching': True,
        'chunk_large_contexts': True,
        'max_files': 15,
        'context_size': 'small',
    },
    
    'comprehensive': {
        'prompt_style': 'style-3',
        'file_source': 'oracle',
        'enable_smart_selection': True,
        'enable_caching': True,
        'chunk_large_contexts': True,
        'max_files': 35,
        'context_size': 'large',
    }
}