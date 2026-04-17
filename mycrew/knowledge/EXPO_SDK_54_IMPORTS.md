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
  Alert,
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

### Single File MVP
```javascript
// App.js (at ROOT)
import React, { useState } from 'react';
import { View, Text, StyleSheet, Button, TextInput } from 'react-native';

export default function App() {
  const [count, setCount] = useState(0);
  
  return (
    <View style={styles.container}>
      <Text>Count: {count}</Text>
      <Button title="Increment" onPress={() => setCount(count + 1)} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
```

### Multi-File with Components
```
App.js (ROOT - only imports allowed: react, react-native)
src/TodoItem.js (utility component - only imports in allowed_imports list)
```

**App.js allowed_imports:**
```
["react", "react-native", "./src/TodoItem"]
```

**src/TodoItem.js allowed_imports:**
```
["react", "react-native"]
```

---

## 🚨 Error Prevention Checklist

For EVERY file architecture specifies:

- [ ] **allowed_imports** does NOT include any forbidden modules
- [ ] **All imports** used in the code are in that file's allowed_imports
- [ ] **No expo/* imports** unless they're core Expo API (which don't exist for MVP)
- [ ] **No external packages** unless explicitly approved by architect
- [ ] **React & React-Native only** for most MVP cases
- [ ] **No navigation** unless explicitly required
- [ ] **Local state only** (useState, useReducer, useRef)

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

**ALLOWED**: `react`, `react-native` standard exports, local state  
**FORBIDDEN**: Any module not explicitly listed above  

**If you need storage/persistence**: Use `useState` with local state only for MVP.  
**If you need advanced features**: They are out of scope for minimal MVP. Redesign.  

---

*Last Updated: April 2026 for Expo SDK 54*
