const fs = require('fs');
const path = require('path');
const { compile } = require('svelte/compiler');

const srcDir = path.join(__dirname, '..', '..', 'src');
const APPLY = process.argv.includes('--apply');

// Void elements can never take a closing tag; SVG shape primitives are void in HTML parsing too.
const VOID_TAGS = new Set([
	'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr',
	'path','circle','rect','line','ellipse','polygon','polyline','stop','use','animatetransform',
]);

function analyze(filePath) {
	const content = fs.readFileSync(filePath, 'utf8');
	let ast, warnings;
	try {
		({ ast, warnings } = compile(content, { filename: filePath }));
	} catch (e) {
		return { error: 'COMPILE_ERROR: ' + e.message };
	}

	// The compiler's own offsets are the source of truth for what it complains about.
	const warned = new Set(warnings.filter((w) => w.code === 'element_invalid_self_closing_tag').map((w) => w.start?.character));
	if (!warned.size) return { fixed: 0 };

	const targets = [];
	const walk = (node) => {
		if (!node || typeof node !== 'object') return;
		if (node.type === 'Element' && warned.has(node.start)) targets.push(node);
		for (const k of Object.keys(node)) {
			if (k === 'parent') continue;
			const v = node[k];
			if (Array.isArray(v)) v.forEach(walk);
			else if (v && typeof v === 'object' && v.type) walk(v);
		}
	};
	if (ast.html) walk(ast.html);

	const skipped = [];
	const fixes = [];
	for (const n of targets) {
		const slice = content.slice(n.start, n.end);
		if (!slice.endsWith('/>')) {
			skipped.push(`${n.name}: slice does not end with "/>" -> ${JSON.stringify(slice.slice(-12))}`);
			continue;
		}
		if (VOID_TAGS.has(n.name)) {
			skipped.push(`${n.name}: void element`);
			continue;
		}
		fixes.push({ start: n.start, end: n.end, name: n.name });
	}

	if (!fixes.length) return { fixed: 0, warned: warned.size, targets: targets.length, skipped };

	// Apply from the end backwards so earlier offsets stay valid.
	fixes.sort((a, b) => b.start - a.start);
	let out = content;
	for (const { start, end, name } of fixes) {
		out = out.slice(0, start) + out.slice(start, end - 2) + '>' + `</${name}>` + out.slice(end);
	}

	if (APPLY) fs.writeFileSync(filePath, out, 'utf8');
	return { fixed: fixes.length, warned: warned.size, targets: targets.length, skipped };
}

let total = 0, files = 0, mismatch = 0;
const problems = [];
function walkDir(dir) {
	for (const file of fs.readdirSync(dir)) {
		const full = path.join(dir, file);
		if (fs.statSync(full).isDirectory()) walkDir(full);
		else if (file.endsWith('.svelte')) {
			const r = analyze(full);
			if (r.error) { problems.push(full + ' ' + r.error); continue; }
			if (r.fixed) {
				total += r.fixed;
				files++;
				if (r.fixed !== r.warned) { mismatch++; problems.push(`MISMATCH ${path.relative(srcDir, full)}: fixed=${r.fixed} warned=${r.warned} targets=${r.targets} skipped=${JSON.stringify(r.skipped)}`); }
				else if (r.skipped?.length) problems.push(`SKIPPED ${path.relative(srcDir, full)}: ${JSON.stringify(r.skipped)}`);
			}
		}
	}
}
walkDir(srcDir);
console.log(`${APPLY ? 'FIXED' : 'DRY-RUN'}: ${total} tags in ${files} files (offset mismatches: ${mismatch})`);
problems.forEach((p) => console.log('  ' + p));
