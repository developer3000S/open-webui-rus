const fs = require('fs');
const path = require('path');
const { compile } = require('svelte/compiler');

const file = process.argv[2];
const src = fs.readFileSync(file, 'utf8');
const { warnings, ast } = compile(src, { filename: file });

const w = warnings.filter((x) => x.code === 'element_invalid_self_closing_tag');
console.log('warnings:', w.length);
for (const warn of w) {
	console.log(JSON.stringify({ line: warn.start?.line, col: warn.start?.column, pos: warn.start?.offset ?? warn.start?.character ?? 'NO-OFFSET', frame: (warn.frame || '').split('\n')[0] }));
}

const found = [];
const walk = (node) => {
	if (node && typeof node === 'object') {
		if (node.type === 'Element' || node.type === 'InlineComponent' || node.type === 'Slot' || node.type === 'Head' || node.type === 'Window' || node.type === 'Component' || node.type === 'SvelteComponent' || node.type === 'SvelteElement') {
			const slice = typeof node.start === 'number' && typeof node.end === 'number' ? src.slice(node.start, node.end) : null;
			found.push({
				type: node.type,
				name: node.name,
				start: node.start,
				end: node.end,
				children: node.children ? node.children.length : 'n/a',
				endsWith: slice ? JSON.stringify(slice.slice(-6)) : 'NO-SLICE',
				head: slice ? JSON.stringify(slice.slice(0, 20)) : '?',
			});
		}
		for (const k of Object.keys(node)) {
			if (k === 'parent' || k === 'start' || k === 'end') continue;
			const v = node[k];
			if (Array.isArray(v)) v.forEach(walk);
			else if (v && typeof v === 'object' && v.type) walk(v);
		}
	}
};
walk(ast.html);
console.log('\nnodes:');
found.forEach((n) => console.log(JSON.stringify(n)));
