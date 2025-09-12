#!/usr/bin/env python3
"""
Show the actual prompt used by the patch-based stub generator.
"""

import sys
from pathlib import Path

# Add validation module to path
sys.path.insert(0, str(Path(__file__).parent))

from patch_based_stub_generator import PatchBasedStubGenerator


def show_patch_prompt():
    """Show the actual prompt used for patch generation."""
    
    # Create generator instance
    generator = PatchBasedStubGenerator()
    
    # Example inputs similar to what would be used in validation
    build_log = """
    e: file:///workspace/_type_core/preference/api/src/commonMain/kotlin/net/thunderbird/core/preference/privacy/PrivacySettings.kt:7:23 Unresolved reference 'privacy'
    e: file:///workspace/_type_core/preference/api/src/commonMain/kotlin/net/thunderbird/core/preference/privacy/PrivacySettings.kt:8:23 Unresolved reference 'privacy'
    e: file:///workspace/app-thunderbird/src/debug/kotlin/net/thunderbird/android/ui/settings/privacy/PrivacySettingsViewModel.kt:12:52 Unresolved reference 'PrivacySettings'
    BUILD FAILED with compilation errors
    """
    
    test_patch = """
    diff --git a/app-thunderbird/src/test/kotlin/net/thunderbird/android/ui/settings/privacy/PrivacySettingsViewModelTest.kt b/app-thunderbird/src/test/kotlin/net/thunderbird/android/ui/settings/privacy/PrivacySettingsViewModelTest.kt
    new file mode 100644
    index 0000000..abc1234
    --- /dev/null
    +++ b/app-thunderbird/src/test/kotlin/net/thunderbird/android/ui/settings/privacy/PrivacySettingsViewModelTest.kt
    @@ -0,0 +1,15 @@
    +package net.thunderbird.android.ui.settings.privacy
    +
    +import net.thunderbird.core.preference.privacy.PrivacySettings
    +import org.junit.Test
    +
    +class PrivacySettingsViewModelTest {
    +    @Test
    +    fun testPrivacySettings() {
    +        val settings = PrivacySettings()
    +        // Test implementation
    +    }
    +}
    """
    
    oracle_files = {
        "_type_core/preference/api/src/commonMain/kotlin/net/thunderbird/core/preference/privacy/PrivacySettings.kt": """
package net.thunderbird.core.preference.privacy

data class PrivacySettings(
    val enablePrivacyMode: Boolean = false,
)
"""
    }
    
    # Generate the comprehensive prompt
    prompt = generator._create_comprehensive_prompt(build_log, test_patch, oracle_files)
    
    print("="*80)
    print("PATCH-BASED STUB GENERATION PROMPT")
    print("="*80)
    print()
    print(prompt)
    print()
    print("="*80)
    print(f"Prompt length: {len(prompt)} characters")
    print("="*80)


if __name__ == "__main__":
    show_patch_prompt()
