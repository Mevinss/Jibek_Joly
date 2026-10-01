/** Kinematic demo: constant average speed, not an ATO command or energy model. */
export function approachAdvice({ distanceKm, nowMin, slotMin, capKmh }) {
  if (![distanceKm, nowMin, slotMin, capKmh].every(Number.isFinite)
      || distanceKm <= 0 || capKmh <= 0 || nowMin < 0 || slotMin < 0) {
    return { status: 'INVALID', speedKmh: null };
  }
  const remainingMin = slotMin - nowMin;
  if (remainingMin <= 0) return { status: 'EXPIRED', speedKmh: null };
  const speedKmh = distanceKm * 60 / remainingMin;
  if (speedKmh > capKmh) return { status: 'UNREACHABLE', speedKmh: null, remainingMin };
  if (speedKmh < 5) return { status: 'HOLD', speedKmh: null, remainingMin };
  return { status: 'AVAILABLE', speedKmh, remainingMin };
}
