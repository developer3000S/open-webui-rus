const { compile } = require('svelte/compiler');
const fs = require('fs');
const path = require('path');

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.name.endsWith('.svelte')) out.push(p);
  }
  return out;
}

let hard = 0;
const files = walk('src');
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8');
  try {
    compile(src, { filename: f });
  } catch (err) {
    hard++;
    console.log('HARD ' + f + ' :: ' + String(err.message).split('\n')[0]);
  }
}
console.log('SCANNED=' + files.length);
console.log('HARD_ERRORS_COUNT=' + hard);
