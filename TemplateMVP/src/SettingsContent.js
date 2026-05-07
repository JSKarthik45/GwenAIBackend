import { StyleSheet, Text, View } from 'react-native';

export default function SettingsContent() {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Settings Content</Text>
      <Text style={styles.body}>
        Keep your controls and toggles in this screen content file. The shared
        navigation structure already exists in TemplateMVP App.js.
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
