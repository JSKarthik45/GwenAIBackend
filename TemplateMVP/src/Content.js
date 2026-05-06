import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

const Content = () => {
  return (
    <View style={styles.container}>
      <Text style={styles.text}>Loading your app...</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  text: { fontSize: 16, color: '#6b7280' },
});

export default Content;
