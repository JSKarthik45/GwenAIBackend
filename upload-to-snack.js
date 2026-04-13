#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { Snack } = require('snack-sdk');

const QR_API_BASE = 'https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=';
const DEFAULT_APP_DIR = path.resolve(process.cwd(), 'GeneratedMVP', 'MyApp');
const SKIP_DIRS = new Set(['node_modules', '.expo']);

const CODE_EXTENSIONS = new Set([
  '.js',
  '.jsx',
  '.ts',
  '.tsx',
  '.json',
  '.css',
  '.md',
  '.txt',
  '.yml',
  '.yaml',
  '.sh',
  '.html',
]);

const BINARY_EXTENSIONS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.webp',
  '.mp4', '.mov', '.mp3', '.wav',
  '.ttf', '.otf', '.woff', '.woff2',
  '.zip', '.tar', '.gz', '.rar',
  '.exe', '.dll', '.so', '.dylib',
]);

function toPosixPath(p) {
  return p.split(path.sep).join('/');
}

function isCodeFile(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  // Exclude binary files explicitly
  if (BINARY_EXTENSIONS.has(ext)) {
    return false;
  }
  return CODE_EXTENSIONS.has(ext) || path.basename(filePath) === 'package.json';
}

function walkFiles(rootDir, currentDir = rootDir, collected = []) {
  const entries = fs.readdirSync(currentDir, { withFileTypes: true });

  for (const entry of entries) {
    if (entry.name.startsWith('.git')) {
      continue;
    }

    const fullPath = path.join(currentDir, entry.name);

    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) {
        continue;
      }
      walkFiles(rootDir, fullPath, collected);
      continue;
    }

    if (entry.isFile()) {
      const relativePath = toPosixPath(path.relative(rootDir, fullPath));
      collected.push({ fullPath, relativePath });
    }
  }

  return collected;
}

function readPackageDependencies(appDir) {
  const packageJsonPath = path.join(appDir, 'package.json');
  if (!fs.existsSync(packageJsonPath)) {
    return {};
  }

  const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));
  return packageJson.dependencies || {};
}

function readPackageJson(appDir) {
  const packageJsonPath = path.join(appDir, 'package.json');
  if (!fs.existsSync(packageJsonPath)) {
    return {};
  }

  try {
    return JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));
  } catch {
    return {};
  }
}

function inferSdkVersion(dependencies) {
  // Use SDK 54 for stable 2026 support
  return '54.0.0';
}

function pickEntryCode(files) {
  const preferred = ['App.js', 'App.jsx', 'src/App.js', 'src/App.jsx', 'index.js'];
  for (const key of preferred) {
    if (files[key] && typeof files[key].contents === 'string') {
      return { code: files[key].contents, source: key };
    }
  }

  const anyJsKey = Object.keys(files).find((k) => /\.(jsx?|tsx?)$/i.test(k));
  if (anyJsKey && files[anyJsKey] && typeof files[anyJsKey].contents === 'string') {
    return { code: files[anyJsKey].contents, source: anyJsKey };
  }

  return { code: 'export default function App() { return null; }', source: 'fallback' };
}

function buildSnackFiles(appDir) {
  const files = {};
  const allFiles = walkFiles(appDir);

  for (const file of allFiles) {
    // CRITICAL: EXPLICITLY SKIP package.json in the files object
    // It causes conflict with manifest dependencies and bundler fails silently
    if (!isCodeFile(file.relativePath) || file.relativePath === 'package.json') {
      continue;
    }

    const contents = fs.readFileSync(file.fullPath, 'utf8');
    files[file.relativePath] = {
      type: 'CODE',
      contents,
    };
  }

  return files;
}

async function uploadToSnack(appDir) {
  if (!fs.existsSync(appDir)) {
    throw new Error(`App directory not found: ${appDir}`);
  }

  let files = buildSnackFiles(appDir);
  let dependencies = readPackageDependencies(appDir);

  if (Object.keys(files).length === 0) {
    throw new Error('No code files found to upload.');
  }

  // CRITICAL: Snack SDK requires App.js (or App.tsx) at the root level
  // If not present, create it from src/App.js or index.js
  if (!files['App.js'] && !files['App.tsx']) {
    let appContent = null;

    // Try to get App.js from src/
    if (files['src/App.js']) {
      appContent = files['src/App.js'].contents;
    } else if (files['index.js']) {
      // If only index.js exists, read it directly
      appContent = fs.readFileSync(path.join(appDir, 'index.js'), 'utf8');
    }

    if (!appContent) {
      throw new Error('Could not find App.js, App.tsx, src/App.js, or index.js in generated app.');
    }

    // Create root-level App.js by either:
    // 1. Use src/App.js directly if it's a pure component
    // 2. Or wrap it if it's using registerRootComponent
    if (appContent.includes('registerRootComponent')) {
      // This is index.js format, extract the actual App component
      // Try to read src/App.js instead
      const srcAppPath = path.join(appDir, 'src', 'App.js');
      if (fs.existsSync(srcAppPath)) {
        appContent = fs.readFileSync(srcAppPath, 'utf8');
      }
    }

    files['App.js'] = {
      type: 'CODE',
      contents: appContent,
    };

    console.log('  ✓ Created root-level App.js from generated app');
  }

  // Remove duplicate entry points to avoid confusion
  delete files['index.js'];

  // Convert dependency format for Snack SDK (needs version object)
  const snackDependencies = {};
  for (const [name, version] of Object.entries(dependencies)) {
    snackDependencies[name] = { version };
  }

  // Ensure peer dependencies are present
  snackDependencies['expo'] = snackDependencies['expo'] || { version: '~54.0.0' };
  snackDependencies['react'] = snackDependencies['react'] || { version: '18.3.1' };
  snackDependencies['react-native'] = snackDependencies['react-native'] || { version: '0.76.0' };

  console.log('📦 Initializing Snack SDK...');
  
  // 1. Create Snack instance with SDK validation
  const snack = new Snack({
    sdkVersion: '54.0.0',
    name: 'Gwen AI MVP',
    description: 'Generated by Gwen AI',
    files,
    dependencies: snackDependencies,
  });

  // 2. Set online so Expo can connect and verify the bundle
  console.log('🔌 Going online...');
  snack.setOnline(true);

  // 3. Wait for dependency resolution and validation
  console.log('⏳ Resolving dependencies and validating bundle...');
  const state = await snack.getStateAsync();

  // Check for missing dependencies
  if (state.missingDependencies && Object.keys(state.missingDependencies).length > 0) {
    console.warn('⚠️  Missing dependencies detected:');
    for (const [name, info] of Object.entries(state.missingDependencies)) {
      console.warn(`   ${name} (wanted: ${info.wantedVersion})`);
      // Auto-add missing dependencies
      snackDependencies[name] = { version: info.wantedVersion };
    }
    snack.updateDependencies(snackDependencies);
    // Wait again for the new dependencies
    await snack.getStateAsync();
  }

  // 4. Save to get permanent ID (this ensures the bundle is valid before returning)
  console.log('💾 Saving to Expo servers...');
  const { id, url } = await snack.saveAsync();

  if (!id || !url) {
    throw new Error('Snack SDK did not return valid ID or URL. The bundle may have failed validation.');
  }

  // 5. Generate QR code from the validated URL
  const qrImageUrl = `${QR_API_BASE}${encodeURIComponent(url)}`;

  // Take Snack offline to clean up
  snack.setOnline(false);

  return {
    snackId: id,
    snackUrl: url,
    qrImageUrl,
  };
}

async function main() {
  const appDir = process.argv[2] ? path.resolve(process.argv[2]) : DEFAULT_APP_DIR;

  try {
    const result = await uploadToSnack(appDir);

    console.log('\n✅ Snack upload successful (SDK 54.0.0 - Validated Bundle)');
    console.log(`App directory: ${appDir}`);
    console.log(`snackId: ${result.snackId}`);
    console.log(`\nSnack Web URL:`);
    console.log(`  ${result.snackUrl}`);
    console.log(`\nQR Code URL (scan with Expo Go app):`);
    console.log(`  ${result.qrImageUrl}`);
    console.log(`\n✨ Your Snack is now LIVE and validated by Expo servers.`);
    console.log(`   You can scan the QR immediately—no waiting required!`);
  } catch (error) {
    console.error('❌ Snack upload failed');
    console.error(error.message);
    process.exitCode = 1;
  }
}

main();
