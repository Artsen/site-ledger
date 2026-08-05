export function deterministicCoordinates(id: string) {
  const angle = unitHash(`${id}:angle`) * Math.PI * 2;
  const radius = Math.sqrt(unitHash(`${id}:radius`)) * 420;
  const depthAngle = unitHash(`${id}:depth`) * Math.PI * 2;
  const depthRadius = Math.sqrt(unitHash(`${id}:depth-radius`)) * 260;
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius,
    z: Math.sin(depthAngle) * depthRadius
  };
}

export function stableHash(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function unitHash(value: string) {
  return mixHash(stableHash(value)) / 0xffffffff;
}

function mixHash(value: number) {
  let hash = value >>> 0;
  hash ^= hash >>> 16;
  hash = Math.imul(hash, 0x7feb352d);
  hash ^= hash >>> 15;
  hash = Math.imul(hash, 0x846ca68b);
  hash ^= hash >>> 16;
  return hash >>> 0;
}
