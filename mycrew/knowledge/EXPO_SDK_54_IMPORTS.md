# Expo SDK 54 - Valid Imports Reference

## Overview
This document lists the ONLY modules that can be imported in Expo SDK 54 React Native JSX applications running in Expo Go.

**CRITICAL RULE**: Any import NOT listed here will cause `unable to resolve module` errors.

---

## ✅ SAFE & AVAILABLE Modules

### React & React Hooks
```javascript
import React, { useState, useEffect, useCallback, useRef, useMemo, useReducer } from 'react';
import { Fragment } from 'react';
```

### React Native Core (Standard Exports)
```javascript
import {
  View,
  Text,
  StyleSheet,
  Button,
  TextInput,
  ScrollView,
  FlatList,
  SectionList,
  TouchableOpacity,
  TouchableHighlight,
  TouchableWithoutFeedback,
  Pressable,
  Modal,

  Image,
  ActivityIndicator,
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
  Dimensions,
  StatusBar,
  AppRegistry
} from 'react-native';
```

### React Native Components (Less Common but Available)
```javascript
import {
  Switch,
  Picker,
  Slider,
  SegmentedControlIOS,
  DatePickerAndroid,
  TimePickerAndroid,
  AppState,
  Keyboard,
  PermissionsAndroid,
  Share,
  Vibration,
} from 'react-native';
```

---

## ❌ STRICTLY FORBIDDEN (Will Cause Errors)

### Storage/File System (Do NOT use these)
- ❌ `expo/storage` - DOES NOT EXIST
- ❌ `expo-sqlite` - Not in Expo Go
- ❌ `expo-file-system` - Not in Expo Go
- ❌ `expo/filesystem` - DOES NOT EXIST
- ❌ `@react-native-async-storage/async-storage` - Use local state instead

### Navigation (Not included in minimal MVP)
- ❌ `react-navigation` - NOT AVAILABLE
- ❌ `@react-navigation/*` - NOT AVAILABLE
- ❌ `react-native-navigation` - NOT AVAILABLE

### Other Packages (Not in Expo SDK 54)
- ❌ `@react-native-*` (any package starting with this)
- ❌ `lodash`
- ❌ `axios`
- ❌ `fetch-polyfill`
- ❌ Redux/MobX/Zustand
- ❌ `react-native-storage`

---

## 📋 Valid Architecture Patterns

### Complex Single-Screen App (5-7 files)

```
App.js (ROOT, 300-400 lines)
  - Main screen container, orchestrates all state
  - Renders component tree
  
src/components/
  - Header.js (100-150 lines) - App header with title/controls
  - InputForm.js (150-200 lines) - User input section
  - ItemList.js (150-200 lines) - Display filtered/styled list
  - ItemCard.js (100-150 lines) - Individual list item component
  
src/utils/
  - helpers.js (100-150 lines) - Filter, sort, format functions
  - constants.js (50-100 lines) - Colors, strings, defaults
```

**Typical App.js structure** (300-400 lines):
```javascript
import React, { useState, useEffect, useCallback, useReducer } from 'react';
import { View, Text, StyleSheet, ScrollView, SafeAreaView } from 'react-native';
import Header from './src/components/Header';
import InputForm from './src/components/InputForm';
import ItemList from './src/components/ItemList';
import { processItems, filterByCategory } from './src/utils/helpers';

export default function App() {
  // Multiple state pieces
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState('all');
  const [sortBy, setSortBy] = useState('date');
  const [showInput, setShowInput] = useState(false);
  
  // Derived state/memoization
  const filteredItems = useCallback(() => {
    // Filter and sort logic (20-30 lines)
    return filterByCategory(items, filter);
  }, [items, filter]);
  
  // Multiple event handlers
  const handleAddItem = useCallback((newItem) => {
    // Process and validate (10-15 lines)
    setItems([...items, newItem]);
  import { AsyncStorage } from 'react-native'; // WRONG - AsyncStorage removed many versions ago
  import StorageAPI from 'expo/storage'; // WRONG - expo/storage DOES NOT EXIST (hallucination)
  import AsyncStorage from 'expo-async-storage'; // WRONG - does not exist
  import { SQLite } from 'expo-sqlite'; // WRONG - Not available in Expo Go
    setItems(items.filter(item => item.id !== id));
  }, [items]);
  
  // Effects
  useEffect(() => {
    // Side effects (10-20 lines)
  }, [filter]);
  
  return (
    <SafeAreaView style={styles.container}>
      <Header title="My App" />
      {showInput && <InputForm onAdd={handleAddItem} />}
      <ItemList 
        items={filteredItems()} 
        onDelete={handleDeleteItem}
        onFilter={setFilter}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  // Extensive styling (30-50 lines)
  container: { flex: 1, backgroundColor: '#fff' },
  // ... more styles ...
});
```

**Component example** (150-200 lines):
```javascript
// src/components/ItemList.js
import React, { useCallback } from 'react';
import {
  FlatList,
  View,
  StyleSheet,
import ItemCard from './ItemCard';
  const renderItem = useCallback(({ item }) => (
    </TouchableOpacity>
  ), [onDelete]);
  
  return (
    <View style={styles.container}>
      <FlatList
        data={items}
        renderItem={renderItem}
        keyExtractor={item => item.id.toString()}
  **SCOPE**: Single-screen Expo app (NO navigation, 5-7 files, 150-400 lines per file)  
  **CORE ALLOWED**: `react`, `react-native` standard exports, local state via hooks  
  **EXCEPTION**: `@react-native-async-storage/async-storage` in `src/utils/storage.js` ONLY (if persistence needed)  
  **FORBIDDEN**: Any other external packages, navigation, @react-native-*, expo/storage (doesn't exist)
        scrollEnabled
        nestedScrollEnabled
      />
    </View>
  );
    └─ src/utils/
      ├─ storage.js (if persistence needed, with AsyncStorage logic)
      ├─ helpers.js (logic, formatting, validation)
      └─ constants.js (colors, strings, defaults)

const styles = StyleSheet.create({
  // (~50 lines of styling)
});
```

**Helper utilities** (100-150 lines):
```javascript
// src/utils/helpers.js
  - ✅ Persistent storage (if needed) isolated in src/utils/storage.js
export const filterByCategory = (items, category) => {
  // Filter logic (20 lines)
};
      - Storage/persistence → Use @react-native-async-storage/async-storage in src/utils/storage.js ONLY

export const sortItems = (items, sortBy) => {
  // Sort logic (20 lines)
        External APIs/backend → Out of scope. Local data + optional persistence via async-storage.
};
  **Critical Anti-Pattern**: Never use `expo/storage` or `expo/filesystem` - these modules DO NOT EXIST.  
  If an agent suggests them, it's hallucinating. Use `@react-native-async-storage/async-storage` instead.

  *Last Updated: April 2026 for Expo SDK 54 — Fixed hallucination of non-existent modules*
  // Validation (15 lines)
};

export const formatDate = (date) => {
  // Formatting (10 lines)
};

// ... more helpers ...
```

---

## 🚨 Error Prevention Checklist

For EVERY file architecture specifies:

- [ ] **allowed_imports** does NOT include any forbidden modules
- [ ] **All imports** used in the code are in that file's allowed_imports
- [ ] **No expo/* imports** (expo/storage, expo/filesystem, etc.)
- [ ] **No external packages** (all logic uses react + react-native only)
- [ ] **React & React-Native only** - no additional npm packages
- [ ] **NO navigation** (no react-navigation files, no tabs/stacks)
- [ ] **NO multiple screens** (single screen app only)
- [ ] **Local state only** (useState, useReducer, useCallback, etc.)
- [ ] **Proper styling** (using StyleSheet)
- [ ] **Event handlers** for all interactive elements
- [ ] **Component organization** (5-7 files, proper line counts)
- [ ] **No skeleton/TODO code** (everything production-ready)

---

## Examples of COMMON MISTAKES

### ❌ WRONG
```javascript
import { AsyncStorage } from 'react-native'; // AsyncStorage removed from React Native
import StorageAPI from 'expo/storage'; // expo/storage does NOT exist
import { SQLite } from 'expo-sqlite'; // Not available in Expo Go
import { Platform } from 'react-native'; // May not be in allowed_imports
```

### ✅ CORRECT
```javascript
// For data persistence: Use local state + useState
const [todos, setTodos] = useState([]);

// For platform detection: Only if explicitly in allowed_imports
// import { Platform } from 'react-native';

// For UI: Standard React Native components
import { View, Text, Button, TextInput } from 'react-native';
```

---

## Deep Linking & Manifest

For Snack SDK uploads, Expo handles manifest configuration automatically. Do NOT try to:
- ❌ Import or configure `expo-linking`
- ❌ Add `expo-notifications`
- ❌ Use `AppRegistry` directly

Just write React Native JSX. Expo Snack SDK will handle the rest.

---

## Summary

**SCOPE**: Single-screen Expo app (NO navigation, 5-7 files, 150-400 lines per file)  
**ALLOWED**: `react`, `react-native` standard exports, local state, hooks  
**FORBIDDEN**: Any module not explicitly listed above, external packages, navigation

**Architecture Structure**:
```
App.js (ROOT, 300-400 lines)
  ├─ src/components/ (4-6 reusable UI components, 100-250 lines each)
  └─ src/utils/ (1-2 helper modules, 100-150 lines each)
```

**Code Quality**:
- ✅ Proper React hooks (useState, useEffect, useCallback, useReducer)
- ✅ Styled with StyleSheet
- ✅ Event handlers + user feedback
- ✅ Organized components (not monolithic)
- ✅ No skeleton code or TODOs
- ✅ Production-quality implementation

**If you need**:
- Storage/persistence → Use useState to maintain state (no saving to disk for MVP)
- Multiple screens/navigation → Out of scope. Single screen only.
- Advanced features → Keep within single-screen constraints. Use React hooks for state.
- External APIs/backend → Out of scope. Local data only.

---

*Last Updated: April 2026 for Expo SDK 54 — Single-Screen Apps*
