import fs from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';

const root = path.resolve(import.meta.dirname, '..');

const mark = (foreground = '#ffffff', background = '#111827') => Buffer.from(`
<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <rect x="36" y="36" width="440" height="440" rx="112" fill="${background}"/>
  <path d="M142 402 L256 112 L370 402 M184 306 H328" fill="none"
        stroke="${foreground}" stroke-width="64" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`);

async function png(size, dark = false) {
  return sharp(dark ? mark('#111827', '#ffffff') : mark()).resize(size, size).png().toBuffer();
}

function icoFromPng(image) {
  const header = Buffer.alloc(22);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(1, 4);
  header.writeUInt8(32, 6);
  header.writeUInt8(32, 7);
  header.writeUInt16LE(1, 10);
  header.writeUInt16LE(32, 12);
  header.writeUInt32LE(image.length, 14);
  header.writeUInt32LE(22, 18);
  return Buffer.concat([header, image]);
}

const directories = ['static/static', 'backend/avexie/static'];
for (const directory of directories) {
  const target = path.join(root, directory);
  await fs.writeFile(path.join(target, 'favicon.svg'), mark());
  await fs.writeFile(path.join(target, 'favicon.png'), await png(512));
  await fs.writeFile(path.join(target, 'favicon-96x96.png'), await png(96));
  await fs.writeFile(path.join(target, 'apple-touch-icon.png'), await png(180));
  await fs.writeFile(path.join(target, 'web-app-manifest-192x192.png'), await png(192));
  await fs.writeFile(path.join(target, 'web-app-manifest-512x512.png'), await png(512));
  await fs.writeFile(path.join(target, 'logo.png'), await png(500));
  await fs.writeFile(path.join(target, 'splash.png'), await png(500));
  await fs.writeFile(path.join(target, 'splash-dark.png'), await png(500, true));
  await fs.writeFile(path.join(target, 'favicon.ico'), icoFromPng(await png(32)));
}

await fs.writeFile(path.join(root, 'static/favicon.png'), await png(512));
await fs.writeFile(path.join(root, 'backend/avexie/static/swagger-ui/favicon.png'), await png(144));
