import { StyleSheet, Text, View } from 'react-native';

export default function HomeContent() {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Home Content</Text>
      <Text style={styles.body}>
        This file is part of the generated app content area. Agents should customize
        this content while leaving navigation and header in the template shell.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 14,
    padding: 16,
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#e3e6f2',
  },
  title: {
    fontSize: 19,
    fontWeight: '700',
    color: '#20243a',
    marginBottom: 8,
  },
  body: {
    fontSize: 14,
    lineHeight: 20,
    color: '#4d536e',
  },
});
