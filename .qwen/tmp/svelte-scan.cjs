const fs = require('fs');
const path = require('path');
const { compile } = require('svelte/compiler');

const componentsDir = path.join(__dirname, '..', '..', 'src');

let count = 0;
function scanComponents(dir) {
	fs.readdirSync(dir).forEach((file) => {
		const fullPath = path.join(dir, file);
		if (fs.statSync(fullPath).isDirectory()) {
			scanComponents(fullPath);
		} else if (file.endsWith('.svelte')) {
			count++;
			try {
				const src = fs.readFileSync(fullPath, 'utf8');
				compile(src, { filename: fullPath });
			} catch (error) {
				console.error('Error in ' + fullPath + ': ' + error.message);
			}
		}
	});
}

scanComponents(componentsDir);
console.error('Scanned ' + count + ' .svelte files under ' + componentsDir);
