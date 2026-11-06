/** Simple per-IP sliding window rate limiter (in-memory, best-effort on Workers). */

interface Bucket {
  timestamps: number[];
}

const buckets = new Map<string, Bucket>();

export function clientIp(request: Request): string {
  return (
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    "unknown"
  );
}

export function checkRateLimit(
  key: string,
  opts: { limitPerMinute: number },
): { allowed: boolean; remaining: number; reset_ms: number } {
  const limitPerMinute = opts.limitPerMinute;
  const now = Date.now();
  const windowMs = 60_000;
  let bucket = buckets.get(key);
  if (!bucket) {
    bucket = { timestamps: [] };
    buckets.set(key, bucket);
  }
  bucket.timestamps = bucket.timestamps.filter((t) => now - t < windowMs);
  if (bucket.timestamps.length >= limitPerMinute) {
    const oldest = bucket.timestamps[0] || now;
    return {
      allowed: false,
      remaining: 0,
      reset_ms: Math.max(0, windowMs - (now - oldest)),
    };
  }
  bucket.timestamps.push(now);
  // Cap map size to avoid unbounded growth on unique IPs.
  if (buckets.size > 5000) {
    const first = buckets.keys().next().value;
    if (first) buckets.delete(first);
  }
  return {
    allowed: true,
    remaining: Math.max(0, limitPerMinute - bucket.timestamps.length),
    reset_ms: windowMs,
  };
}
