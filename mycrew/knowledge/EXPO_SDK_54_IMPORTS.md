# Expo SDK 54 Import Rules (Multi-Screen MVP Mode)

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
- Multi-screen MVP with exactly 3 screens: `HomeScreen`, `HistoryScreen`, `SettingsScreen`
- Manual screen switching with React state (no navigation library)
- Include SafeAreaView app shell
- Include top header with current screen title
- Include bottom navbar for screen switching
- 7-9 files total
- Compact files for reliable tool calls:
  - `App.js`: 60-90 lines
  - Screens: 30-80 lines
  - Components: 25-70 lines
  - Utils: 25-70 lines

## Reliability Rules
- One file per `file_writer` call
- Keep payloads compact
- Split large logic into helper files under `src/utils/`
- Never import modules outside `allowed_imports`
- Never output markdown/json fences before tool calls
- Never output narrative text before tool calls

## Screen Shell Pattern
- `App.js` owns the current screen state
- `src/components/TopHeader.js` renders the active screen title
- `src/components/BottomNavbar.js` switches screens via callbacks
- `src/screens/HomeScreen.js`, `HistoryScreen.js`, `SettingsScreen.js` render content only

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

## UI Shell Checklist
- App uses `SafeAreaView`
- Top header shows active screen name
- Bottom navbar switches screens via local state
- No react-navigation dependency

Last updated: April 2026
