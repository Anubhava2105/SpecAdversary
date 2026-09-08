// Control-character ranges stripped from untrusted model/provider text.
// Built from code points (not escape sequences) so the source file itself
// never contains a control character.
const RANGES: Array<[number, number]> = [
  [0x00, 0x08],
  [0x0b, 0x0c],
  [0x0e, 0x1f],
  [0x7f, 0x7f],
];

const hex = (n: number) => n.toString(16).padStart(4, '0');
const CONTROL_CHARS = new RegExp(
  `[${RANGES.map(([a, b]) => `\\u${hex(a)}-\\u${hex(b)}`).join('')}]`,
  'g',
);

/** Strip control characters from untrusted model/provider text. */
export const safeText = (value: string) => value.replace(CONTROL_CHARS, '');
