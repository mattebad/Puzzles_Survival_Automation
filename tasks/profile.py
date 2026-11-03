"""Single source of truth for the active runtime profile and native-evidence provenance tag.

BlueStacks is the runtime.  This module is a dependency-free leaf so ``tasks``,
``safe_action_core`` and tests can share one value without import cycles.
"""

ACTIVE_RUNTIME_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
BLUESTACKS_NATIVE_TARGET_PROVENANCE = "bluestacks-native"
