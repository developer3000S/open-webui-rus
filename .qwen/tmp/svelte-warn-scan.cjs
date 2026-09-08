const fs = require('fs');
const path = require('path');
const { compile } = require('svelte/compiler');

const src = path.join(__dirname, '..', '..', 'src');
const counts = {};
const hits = [];
let files = 0;

function walk(dir) {
	for (const file of fs.readdirSync(dir)) {
		const full = path.join(dir, file);
		if (fs.statSync(full).isDirectory()) walk(full);
		else if (file.endsWith('.svelte')) {
			files++;
			try {
				const code = fs.readFileSync(full, 'utf8');
				const { warnings } = compile(code, { filename: full });
				for (const w of warnings) {
					counts[w.code] = (counts[w.code] || 0) + 1;
					if (w.code === 'element_invalid_self_closing_tag') {
						hits.push(full.replace(src + path.sep, '') + ':' + w.start?.line);
					}
				}
			} catch (e) {
				counts['COMPILE_ERROR'] = (counts['COMPILE_ERROR'] || 0) + 1;
				hits.push('HARD ERROR ' + full + ': ' + e.message);
			}
		}
	}
}

walk(src);
console.log('files scanned:', files);
console.log('warning counts:', JSON.stringify(counts, null, 2));
console.log('self-closing hits (' + hits.length + '):');
hits.forEach((h) => console.log('  ' + h));
