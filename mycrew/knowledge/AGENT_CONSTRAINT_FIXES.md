# Agent Constraint Violations & Hallucination Fixes

## Problem Detected

**Error Log Pattern:**
```
BadRequestError: GroqException - "Failed to call a function. Please adjust your prompt."
failed_generation: "import AsyncStorage from '@react-native-async-storage/async-storage'"
```

**Root Cause**: Agent violated its own constraints:
1. Architecture said: **allowed_imports MUST only contain ["react", "react-native"]**
2. Agent tried to use: **@react-native-async-storage/async-storage**
3. Groq guardrails rejected it
4. Agent hallucinated **expo/storage** (non-existent module) to fulfill storage requirement
5. Expo Go threw: **"unable to resolve module 'expo/storage'"**

---

## The Contradiction

### Old Constraints (BROKEN)
```yaml
external_dependencies: (MUST BE EMPTY)
allowed_imports: MUST only contain ["react", "react-native"]
Architecture Summary: "app will remember tasks even after closing"
```

❌ **Impossible to fulfill**: You cannot persist data without a storage library.

---

## The Fix

### New Constraints (CORRECTED)

**Planner Agent:**
- If app needs persistent storage → mention "use @react-native-async-storage/async-storage"
- Not hallucinating "expo/storage" (doesn't exist)

**Architect Agent:**
- Decision Logic:
  - If persistence needed → `external_dependencies: ["@react-native-async-storage/async-storage"]`
  - If no persistence → `external_dependencies: []` (empty)
- For storage files:
  - `allowed_imports`: includes `@react-native-async-storage/async-storage`
  - `allowed_imports` for non-storage files: only `react`, `react-native`

**Feature Builder Agent:**
- ONLY write imports from `allowed_imports`
- If need AsyncStorage → check if it's in `external_dependencies`
- If it's NOT there → don't use it, flag the constraint
- Never hallucinate non-existent modules

---

## Key Rules to Prevent Hallucination

### 1. **Explicit Whitelisting**
```yaml
# agents.yaml - Architect
WHITELIST EXCEPTION - If app requires persistent storage ONLY:
  - @react-native-async-storage/async-storage (this is the ONE allowed external package)
```

### 2. **Clear Forbidden List**
```yaml
BANNED MODULES (THESE DO NOT EXIST - never hallucinate these):
  - expo/storage
  - expo/filesystem
  - expo-sqlite (requires native module)
  - expo-async-storage (doesn't exist)
```

### 3. **Architecture Controls Dependencies**
```yaml
# Architect specifies what's allowed
external_dependencies: ["@react-native-async-storage/async-storage"]  # includes or empty

# Feature builder respects it
Do NOT call track_dependency.
Do NOT use anything not in external_dependencies.
```

### 4. **Constraint Alignment**
```yaml
# Plan: "needs to remember tasks"
# Architecture: external_dependencies includes async-storage
# Implementation: async-storage used in src/utils/storage.js only
# NO contradiction: All parts agree
```

---

## Updated Files

### [agents.yaml](../config/agents.yaml)
- **Planner**: Added "WHITELIST EXCEPTION" section
- **Architect**: Added decision logic for persistence vs. no-persistence
- **Feature Builder**: Added rule "Do NOT use anything not in allowed_imports"

### [tasks.yaml](../config/tasks.yaml)
- **design_architecture**: External dependencies are now "EMPTY unless async-storage needed"
- **implement_mvp_features**: "Do NOT call track_dependency. Architecture.external_dependencies is already set."

### [EXPO_SDK_54_IMPORTS.md](../EXPO_SDK_54_IMPORTS.md)
- Added "Persistent Storage (The ONE Exception)" section
- Added "The @react-native-async-storage/async-storage Exception" subsection
- Updated ❌ WRONG examples to show `expo/storage` is hallucination
- Updated ✅ CORRECT examples with proper storage.js pattern
- Added **Critical Anti-Pattern** warning

---

## Testing This Fix

### Scenario 1: Todo app WITH persistence
```
Planner Output:
  Features include: "store tasks persistently using async-storage"
  
Architect Output:
  external_dependencies: ["@react-native-async-storage/async-storage"]
  src/utils/storage.js allowed_imports: ["react-native", "@react-native-async-storage/async-storage"]
  
Feature Builder:
  Writes src/utils/storage.js with AsyncStorage code
  App.js imports from storage.js (not AsyncStorage directly)
  No hallucination of expo/storage
```

### Scenario 2: Todo app WITHOUT persistence
```
Planner Output:
  Features are session-only (no persistence mentioned)
  
Architect Output:
  external_dependencies: []  (empty)
  allowed_imports: only ["react", "react-native"]
  
Feature Builder:
  Uses useState only
  No attempt to use AsyncStorage
  No hallucination
```

---

## Guardrails by Role

### Planner
- ✅ Can suggest "persistent storage"
- ❌ Cannot suggest "expo/storage", "expo/filesystem", or other non-existent modules
- ✅ Must mention: "use @react-native-async-storage/async-storage if persistence needed"

### Architect
- ✅ Can include @react-native-async-storage/async-storage in external_dependencies
- ✅ Can include it in allowed_imports for storage.js
- ❌ Cannot include it in allowed_imports for other files
- ❌ Cannot include ANY other external packages
- ✅ Must validate: external_dependencies matches available packages

### Feature Builder
- ✅ Must only use imports from allowed_imports
- ✅ If AsyncStorage is needed but NOT in allowed_imports, flag it
- ❌ Cannot hallucinate modules
- ❌ Cannot decide to use AsyncStorage if architect didn't include it
- ✅ Must validate every import before writing

---

## Error Handling

If Feature Builder encounters this error:
```
BadRequestError: GroqException - "Failed to call a function"
```

It means:
1. Agent tried to write code with imports NOT in allowed_imports
2. Groq's guardrails rejected it
3. Agent needs to respect the allowed_imports constraint

**Solution**: Re-read allowed_imports, remove unauthorized imports, retry.

---

## Future Prevention

1. **Training Data**: This file documents the pattern so models learn from it
2. **Prompt Enforcement**: agents.yaml now explicitly forbids hallucination
3. **Validation Layer**: Feature builder must validate imports before tool calls
4. **Knowledge Base**: EXPO_SDK_54_IMPORTS.md explicitly lists what EXISTS vs. FANTASIES

---

*Last Updated: April 17, 2026 — Post-mortem of tool_use_failed error*
