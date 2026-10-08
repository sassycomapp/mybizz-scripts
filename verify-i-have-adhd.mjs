import fs from 'fs';
import path from 'path';

const pluginPath = '/home/dev-p/.config/opencode/plugin/i-have-adhd.mjs';
const mod = await import(pluginPath);
const hooks = await mod.default({});

// 1. config hook: skill discovery + command registration
const cfg = {};
await hooks.config(cfg);
console.log('skills.paths pushed:', JSON.stringify(cfg.skills?.paths));
console.log('skill reachable via pushed path:',
  fs.existsSync(path.join(cfg.skills?.paths?.[0] || '', 'i-have-adhd', 'SKILL.md')));
console.log('command registered:', Boolean(cfg.command?.['i-have-adhd']));
console.log('command description:', cfg.command?.['i-have-adhd']?.description);
console.log('command template head:', (cfg.command?.['i-have-adhd']?.template || '').slice(0, 50));

// 2. always-on transform with flag present
const out = { system: ['BASE SYSTEM PROMPT'] };
await hooks['experimental.chat.system.transform']({}, out);
const sys = out.system[out.system.length - 1];
console.log('--- always-on injection ---');
console.log('header injected:', sys.includes('ADHD MODE ACTIVE (always-on)'));
console.log('ruleset body present:', sys.includes('# i-have-adhd') && sys.includes('Lead with the next action'));
console.log('frontmatter stripped:', !sys.includes('disable-model-invocation'));
console.log('base prompt preserved:', sys.startsWith('BASE SYSTEM PROMPT'));
console.log('injected length:', sys.length);

// 3. flag-absent behaviour
fs.renameSync('/home/dev-p/.config/opencode/.i-have-adhd-always', '/tmp/opencode/flag.bak');
const out2 = { system: ['BASE'] };
await hooks['experimental.chat.system.transform']({}, out2);
console.log('--- flag absent ---');
console.log('no injection:', out2.system[0] === 'BASE');
fs.renameSync('/tmp/opencode/flag.bak', '/home/dev-p/.config/opencode/.i-have-adhd-always');
console.log('flag restored: yes');
