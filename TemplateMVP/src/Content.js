import { StyleSheet, Text, View } from 'react-native';

export default function Content() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Single Page App</Text>
      <Text style={styles.body}>This template is now a one-page Expo app scaffold.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    backgroundColor: '#f5f7fb',
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#111827',
    textAlign: 'center',
    marginBottom: 12,
  },
  body: {
    fontSize: 16,
    lineHeight: 24,
    color: '#4b5563',
    textAlign: 'center',
  },
});