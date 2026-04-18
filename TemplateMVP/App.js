import { useMemo, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import {
  SafeAreaView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

import HomeContent from './src/content/HomeContent';
import SettingsContent from './src/content/SettingsContent';

const NAV_ITEMS = [
  { key: 'home', label: 'Home', icon: '⌂' },
  { key: 'settings', label: 'Settings', icon: '⚙' },
];

export default function App() {
  const [activeScreen, setActiveScreen] = useState('home');

  const activeItem = useMemo(
    () => NAV_ITEMS.find((item) => item.key === activeScreen) || NAV_ITEMS[0],
    [activeScreen]
  );

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="dark" translucent={false} backgroundColor="#ffffff" />

      <View style={styles.header}>
        <Text style={styles.headerTitle}>{activeItem.label}</Text>
      </View>

      <View style={styles.contentWrap}>
        {activeScreen === 'home' ? <HomeContent /> : <SettingsContent />}
      </View>

      <View style={styles.navbar}>
        {NAV_ITEMS.map((item) => {
          const isActive = item.key === activeScreen;
          return (
            <TouchableOpacity
              key={item.key}
              style={styles.navItem}
              onPress={() => setActiveScreen(item.key)}
              activeOpacity={0.8}
            >
              <Text style={[styles.navIcon, isActive && styles.navActive]}>{item.icon}</Text>
              <Text style={[styles.navLabel, isActive && styles.navActive]}>{item.label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#f6f7fb',
  },
  header: {
    paddingHorizontal: 18,
    paddingTop: 12,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#d9dbe6',
    backgroundColor: '#ffffff',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#20243a',
    textAlign: 'center',
  },
  contentWrap: {
    flex: 1,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  navbar: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: '#d9dbe6',
    backgroundColor: '#ffffff',
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  navItem: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  navIcon: {
    fontSize: 18,
    color: '#727894',
  },
  navLabel: {
    marginTop: 2,
    fontSize: 12,
    color: '#727894',
  },
  navActive: {
    color: '#1f4bd8',
    fontWeight: '700',
  },
});
