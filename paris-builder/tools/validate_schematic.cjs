// Independent JavaScript parser and Minecraft 1.21.11 block-registry validation.
const fs = require('fs');
const nbt = require('prismarine-nbt');
const data = require('minecraft-data')('1.21.11');

// prismarine-schematic 1.3.0 parses value-list integer states (for example the
// azalea_leaves distance property) as raw numbers instead of value indices, so
// every read/write round-trip reports a false one-step drift. Replace the
// exported mapping with the registry-correct rule before the parser loads.
const stateMapping = require('prismarine-schematic/lib/states');
const PARSER_WORKAROUND = 'prismarine-schematic 1.3.0 value-list integer state index fix';
stateMapping.getStateId = function getStateId (mcData, name, properties) {
  const block = mcData.blocksByName[name];
  if (!block) { console.log(`Unknown block ${name} replacing with air`); return 0; }
  let data = 0;
  for (const [key, value] of properties) {
    let offset = 1;
    for (let i = block.states.length - 1; i >= 0; i--) {
      const state = block.states[i];
      if (state.name !== key) { offset *= state.num_values; continue; }
      if (state.values) data += offset * state.values.indexOf(String(value));
      else if (state.type === 'bool') data += offset * (value === 'true' ? 0 : 1);
      else data += offset * Number(value);
      break;
    }
  }
  return block.minStateId === undefined ? (block.id << 4) + data : block.minStateId + data;
};
const { Schematic } = require('prismarine-schematic');

async function main() {
  const [input, output] = process.argv.slice(2);
  if (!input) throw new Error('Usage: node tools/validate_schematic.cjs INPUT.schem [OUTPUT.json]');
  const buffer = fs.readFileSync(input);
  const parsed = await nbt.parse(buffer);
  const root = nbt.simplify(parsed.parsed);
  const issues = [];
  if (root.Version !== 2 || root.DataVersion !== data.version.dataVersion) issues.push('Wrong format or Minecraft DataVersion');
  for (const state of Object.keys(root.Palette)) {
    const match = /^(minecraft:)([a-z0-9_]+)(?:\[([^\]]+)\])?$/.exec(state);
    if (!match) { issues.push(`Malformed or non-vanilla state: ${state}`); continue; }
    const block = data.blocksByName[match[2]];
    if (!block) { issues.push(`Unknown block: ${state}`); continue; }
    const entries = match[3] ? match[3].split(',').map(p => p.split('=')) : [];
    const props = Object.fromEntries(entries);
    if (entries.length !== Object.keys(props).length) issues.push(`Duplicate property: ${state}`);
    const expected = Object.fromEntries(block.states.map(s => [s.name, s]));
    for (const [key, value] of Object.entries(props)) {
      const spec = expected[key];
      if (!spec) { issues.push(`Unknown property ${key}: ${state}`); continue; }
      const values = spec.type === 'bool' ? ['true', 'false'] : spec.values?.map(String);
      if (values ? !values.includes(value) : !/^\d+$/.test(value) || Number(value) >= spec.num_values) {
        issues.push(`Invalid ${key}=${value}: ${state}`);
      }
    }
    for (const key of Object.keys(expected)) {
      if (!(key in props)) issues.push(`Missing explicit ${key}: ${state}`);
    }
  }
  let independentRead = null;
  if (!issues.length) {
    const schematic = await Schematic.read(buffer, '1.21.11');
    const expected = root.Width * root.Height * root.Length;
    if (schematic.blocks.length !== expected) issues.push('Decoded count mismatch');
    if (schematic.blocks.some(i => i < 0 || i >= schematic.palette.length)) issues.push('Palette reference outside range');
    const again = await Schematic.read(await schematic.write(), '1.21.11');
    let changes = 0;
    for (let i = 0; i < expected; i++) {
      if (schematic.palette[schematic.blocks[i]] !== again.palette[again.blocks[i]]) changes++;
    }
    if (changes) issues.push(`${changes} block states changed during independent round-trip`);
    independentRead = {format: 'Sponge v2', version: schematic.version, dimensions: schematic.size,
      count: schematic.blocks.length, palette_states: schematic.palette.length, roundtrip_changed_voxels: changes};
  }
  const report = {status: issues.length ? 'FAIL' : 'PASS', registry_version: data.version.minecraftVersion,
    parser: 'prismarine-schematic@1.3.0', parser_workaround: PARSER_WORKAROUND, issues, independent_read: independentRead,
    note: 'Independent file read/write and registry checks; not a game-client paste test.'};
  if (output) fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
  if (issues.length) process.exitCode = 1;
}
main().catch(error => { console.error(error); process.exitCode = 1; });
