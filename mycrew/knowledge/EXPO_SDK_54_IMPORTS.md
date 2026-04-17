# Expo SDK 54 Import Rules (Single-Screen Mode)

## Goal
Keep generated apps reliable in Expo Go and avoid module resolution errors.

## Allowed Imports

### Core (always allowed)
- `react`
- `react-native`

### Storage (allowed only when persistence is required)
- `@react-native-async-storage/async-storage`

Use storage only in `src/utils/storage.js`.

## Forbidden Imports
- `expo/storage` (does not exist)
- `expo/filesystem` (does not exist)
- `expo-file-system` (not allowed in this flow)
- `expo-sqlite` (not allowed in this flow)
- `react-navigation` and `@react-navigation/*`
- Any `@react-native-*` package except `@react-native-async-storage/async-storage`

## Architecture Targets
- Single screen only (no tabs, no stacks, no routing)
- 5-7 files total
- Compact files for reliable tool calls:
  - `App.js`: 120-180 lines
  - Components: 70-140 lines
  - Utils: 50-120 lines

## Reliability Rules
- One file per `file_writer` call
- Keep payloads compact
- Split large logic into helper files under `src/utils/`
- Never import modules outside `allowed_imports`

## Storage Pattern

`src/utils/storage.js`
```javascript
import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'app:data';

export async function saveData(value) {
  await AsyncStorage.setItem(KEY, JSON.stringify(value));
}

export async function loadData() {
  const raw = await AsyncStorage.getItem(KEY);
  return raw ? JSON.parse(raw) : [];
}
```

`App.js`
```javascript
import { saveData, loadData } from './src/utils/storage';
```

## Anti-Hallucination Check
If you see `expo/storage` in output, treat it as invalid and regenerate.

Last updated: April 2026
