import { StatusBar } from 'expo-status-bar';
import {
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import Content from './src/Content';

export default function App() {
  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="dark" translucent={false} backgroundColor="#ffffff" />

      <View style={styles.header}>
        <Text style={styles.headerTitle}>MyApp</Text>
      </View>

      <View style={styles.contentWrap}>
        <Content />
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
});
